#include "platform.h"
#include "net_ws.h"
#include "config.h"
#include "secrets.h"
#include "ring.h"

#include "transport.h"
#include <esp_random.h>
#include <lwip/sockets.h>

// ---------------------------------------------------------------- 状态
static bool          s_up = false;
static WsTextHandler s_onText = nullptr;

// 接收状态机
enum class Rx : uint8_t { HDR, LEN, PAY };
static Rx       s_rx       = Rx::HDR;
static uint8_t  s_hdr[8];
static uint8_t  s_hdrNeed  = 2, s_hdrGot = 0;
static uint8_t  s_opcode   = 0;     // 本帧 opcode
static uint8_t  s_dataType = 0;     // 分片消息的原始类型(1=text 2=binary)
static bool     s_fin      = true;
static uint32_t s_remain   = 0;     // 本帧还剩多少 payload

static char     s_text[WS_TEXT_MAX];
static size_t   s_textLen = 0;
static bool     s_textOverflow = false;
static uint8_t  s_ctl[128];         // 控制帧 payload <= 125
static size_t   s_ctlLen = 0;
static uint8_t  s_sink[256];        // 读掉丢弃用(不收的音频、超长文本)

static bool     s_acceptAudio = false;
static uint32_t s_rxAudio = 0;

static uint32_t s_lastPingSent = 0;
static uint32_t s_lastPong     = 0;

// 上行组帧缓冲。payload 一律从 WS_HDR_MAX 处开始,帧头按实际长度**倒着贴**在 payload 前面
// (短帧 6 字节头从 +2 起,长帧 8 字节头从 +0 起)—— 于是 payload 的位置是固定的,
// 录音可以直接写进音频缓冲的 payload 区(wsAudioTxBuf),发送时原地加掩码,不用再拷一遍。
//
// 音频和控制/文本帧**必须分两块**:录音攒包的 100 ms 里随时可能要回 pong、发 ping,
// 共用一块的话会把攒了一半的音频覆盖掉。
#define WS_HDR_MAX  8                                   // 2 + 扩展长度 2 + 掩码 4
static int16_t s_txAudio[(WS_HDR_MAX + NET_CHUNK_BYTES) / 2];   // int16_t:payload 区当 PCM 用
static uint8_t s_txCtl[WS_HDR_MAX + 128];               // hello / turn_* / abort / ping / pong

void wsSetTextHandler(WsTextHandler h) { s_onText = h; }
void wsSetAudioAccept(bool on)         { s_acceptAudio = on; }
uint32_t wsRxAudioBytes()              { return s_rxAudio; }
int16_t *wsAudioTxBuf()                { return s_txAudio + WS_HDR_MAX / 2; }

// 只看自己的标志,不碰 socket。
// 以前这里是 s_up && transportConnected() —— 而 NetworkClientSecure::connected() 内部是
// read(&dummy, 0) -> available() -> mbedtls_ssl_read + 一次 lwIP recv。每轮 loop 被调好几次,
// 空闲时 ~500 Hz x 5 次全是白做。TCP 断没断改由 wsPoll 每轮探一次,发送失败也会 wsClose,
// 两条路都会把 s_up 清掉,所以这里的判断不会漏。
bool wsIsConnected()                   { return s_up; }

// ---------------------------------------------------------------- 工具
static const char B64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static void base64_16(const uint8_t *in, char *out25) {
  int o = 0;
  for (int i = 0; i < 15; i += 3) {
    uint32_t v = ((uint32_t)in[i] << 16) | ((uint32_t)in[i + 1] << 8) | in[i + 2];
    out25[o++] = B64[(v >> 18) & 63];
    out25[o++] = B64[(v >> 12) & 63];
    out25[o++] = B64[(v >>  6) & 63];
    out25[o++] = B64[ v        & 63];
  }
  uint32_t v = (uint32_t)in[15] << 16;          // 最后 1 字节,补两个 =
  out25[o++] = B64[(v >> 18) & 63];
  out25[o++] = B64[(v >> 12) & 63];
  out25[o++] = 0x3D;                            // '='
  out25[o++] = 0x3D;
  out25[o]   = 0;
}

// Native nonblocking socket: wait up to the per-frame budget before starting a frame.
static bool writable(uint32_t timeoutMs) {
  int fd = transportFd();
  if (fd < 0) return false;
  fd_set set;
  FD_ZERO(&set);
  FD_SET(fd, &set);
  struct timeval tv;
  tv.tv_sec  = timeoutMs / 1000;
  tv.tv_usec = (timeoutMs % 1000) * 1000;
  return select(fd + 1, nullptr, &set, nullptr, &tv) > 0 && FD_ISSET(fd, &set);
}

// 组一个**带掩码**的帧发出去。客户端 -> 服务器必须掩码(RFC 6455 §5.3),
// Python 的 websockets 库遇到没掩码的帧会直接关连接。
//
// payload 已经在 wsAudioTxBuf() 里(录音路径)就不拷,原地加掩码;其他情况先拷进对应缓冲。
// 无论哪种,调用之后缓冲里的 payload 都已被掩码改写 —— 调用方不能再指望它。
static bool sendFrame(uint8_t opcode, const uint8_t *payload, size_t len, uint32_t timeoutMs) {
  if (!s_up) return false;

  const bool audio = (opcode == 0x2);
  uint8_t *const base = audio ? (uint8_t *)s_txAudio : s_txCtl;
  const size_t   cap  = audio ? NET_CHUNK_BYTES : sizeof(s_txCtl) - WS_HDR_MAX;
  if (len > cap) return false;

  uint8_t *const pl = base + WS_HDR_MAX;
  if (len && payload != pl) memcpy(pl, payload, len);

  const size_t h = (len < 126) ? 6 : 8;
  uint8_t *const f = pl - h;
  f[0] = 0x80 | opcode;                      // FIN=1,上行不分片
  if (len < 126) {
    f[1] = 0x80 | (uint8_t)len;
  } else {
    f[1] = 0x80 | 126;
    f[2] = (uint8_t)(len >> 8);
    f[3] = (uint8_t)(len & 0xFF);
  }

  uint8_t *const mask = pl - 4;              // 两种头的最后 4 字节都是掩码
  const uint32_t r = esp_random();
  memcpy(mask, &r, 4);
  for (size_t i = 0; i < len; i++) pl[i] ^= mask[i & 3];
  const size_t total = h + len;

  // Keep one deadline for select and TLS writes; a partial WS frame closes the stream.
  const uint32_t started = appMillis();
  if (!writable(timeoutMs)) return false;

  const uint32_t elapsed = appMillis() - started;
  if (elapsed >= timeoutMs) return false;
  size_t w = transportWrite(f, total, timeoutMs - elapsed);
  if (w != total) {
    // 半帧已经出去了,流就错位了,后面所有帧都会解析错。
    // 直接掐掉等重连,比带着错位继续跑干净得多。
    wsClose("上行只写出了半帧");
    return false;
  }
  return true;
}

bool wsSendText(const char *s) {
  return sendFrame(0x1, (const uint8_t *)s, strlen(s), WS_SEND_TIMEOUT_MS);
}

bool wsSendBinary(const uint8_t *data, size_t n) {
  return sendFrame(0x2, data, n, WS_AUDIO_SEND_TIMEOUT_MS);
}

// ---------------------------------------------------------------- 连接
void wsClose(const char *why) {
  if (s_up && why) printf("[WS] 断开:%s\n", why);
  transportClose();
  s_up = false;
  s_rx = Rx::HDR;
  s_hdrNeed = 2; s_hdrGot = 0;
  s_remain = 0;
  s_textLen = 0; s_textOverflow = false;
  s_acceptAudio = false;
}

bool wsConnect() {
  wsClose(nullptr);

  printf("[WS] Connecting %s://%s:%d%s\n", SERVER_USE_TLS ? "wss" : "ws",
         SERVER_HOST, SERVER_PORT, SERVER_WS_PATH);
  if (!transportConnect()) return false;

  uint8_t nonce[16];
  for (int i = 0; i < 16; i += 4) {
    uint32_t r = esp_random();
    memcpy(nonce + i, &r, 4);
  }
  char key[25];
  base64_16(nonce, key);

  // Host 头:默认端口(wss 的 443 / ws 的 80)按 RFC 9110 §7.2 不写端口号。
  // 我们自己的 Python 服务器不校验 Host,但哪天前面多一层反代就会校验,
  // 那种问题的现象是"握手被拒 400",和网络不通长得一模一样,不值得踩。
#if SERVER_USE_TLS
  const bool defaultPort = (SERVER_PORT == 443);
#else
  const bool defaultPort = (SERVER_PORT == 80);
#endif
  char hostHdr[128];
  if (defaultPort) snprintf(hostHdr, sizeof(hostHdr), "%s", SERVER_HOST);
  else             snprintf(hostHdr, sizeof(hostHdr), "%s:%d", SERVER_HOST, SERVER_PORT);

  char request[384];
  const int requestLen = snprintf(request, sizeof(request),
               "GET %s HTTP/1.1\r\n"
               "Host: %s\r\n"
               "Upgrade: websocket\r\n"
               "Connection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n"
               "\r\n",
               SERVER_WS_PATH, hostHdr, key);
  if (requestLen <= 0 || requestLen >= (int)sizeof(request) ||
      transportWrite((const uint8_t *)request, requestLen, WS_SEND_TIMEOUT_MS) != (size_t)requestLen) {
    transportClose();
    return false;
  }

  // 读响应头到空行。只认状态行里的 101。
  //
  // **故意不校验 Sec-WebSocket-Accept。** 校验它要拉 SHA1 + base64,
  // 防的是中间代理串线。rev.4 之前的理由是"设备连的是自己局域网里自己的服务器";
  // rev.5 搬到公网之后这个理由换成了更强的一条:**TLS-PSK 是双向认证的**,
  // 只有握着同一把预共享密钥的对端才能建起这条连接,中间人连 WS 层都到不了。
  // 省下的是代码和堆。这是决定,不是遗漏。
  char line[128];
  size_t n = 0;
  bool got101 = false, firstLine = true;
  const uint32_t t0 = appMillis();
  while (appMillis() - t0 < WS_HANDSHAKE_TIMEOUT_MS) {
    if (!transportConnected()) break;
    uint8_t byte;
    int count = transportRead(&byte, 1);
    int c = count == 1 ? byte : -1;
    if (c < 0) { appDelay(2); continue; }
    if (c == 0x0A) {                                  // '\n'
      line[n] = 0;
      if (firstLine) {
        got101 = (strstr(line, " 101") != nullptr);
        if (!got101) printf("[WS] 握手被拒:%s\n", line);
        firstLine = false;
      }
      if (n == 0 || (n == 1 && line[0] == 0x0D)) {    // 空行 = 头结束
        if (got101) {
          s_up = true;
          s_lastPong = appMillis();
          s_lastPingSent = appMillis();
          printf("%s\n", "[WS] 握手成功");
          return true;
        }
        break;
      }
      n = 0;
    } else if (n + 1 < sizeof(line)) {
      line[n++] = (char)c;
    }
  }

  printf("%s\n", "[WS] 握手失败");
  transportClose();
  return false;
}

// ---------------------------------------------------------------- 接收
static void dispatchControl() {
  switch (s_opcode) {
    case 0x8:                                   // close
      wsClose("服务器发来 close");
      break;
    case 0x9:                                   // ping -> 必须原样回 pong
      sendFrame(0xA, s_ctl, s_ctlLen, WS_AUDIO_SEND_TIMEOUT_MS);   // 播放中也可能收到 ping,别久等
      break;
    case 0xA:                                   // pong
      s_lastPong = appMillis();
      break;
    default:
      break;
  }
}

static void dispatchText() {
  if (s_textOverflow)
    printf("[WS] 控制消息超过 %d 字节,已截断\n", WS_TEXT_MAX);
  if (s_onText && s_textLen) s_onText(s_text, s_textLen);
  s_textLen = 0;
  s_textOverflow = false;
}

void wsPoll() {
  if (!s_up) return;
  if (!transportConnected()) { wsClose("TCP 断了"); return; }

  // 保活。AGENT.md §5.1:30 s 一次 ping,连续两次无 pong 视为断线。
  const uint32_t now = appMillis();
  if (now - s_lastPingSent >= WS_PING_INTERVAL_MS) {
    s_lastPingSent = now;
    sendFrame(0x9, nullptr, 0, WS_AUDIO_SEND_TIMEOUT_MS);
  }
  if (now - s_lastPong > WS_PONG_TIMEOUT_MS) { wsClose("pong 超时"); return; }

  // 每次 poll 最多搬这么多字节。20 ms 的节拍里真正到达的只有 ~640 字节,
  // 留了 6 倍余量;这个上限的意义是**保证 wsPoll 一定会把控制权还给音频循环**。
  int budget = 4096;

  // 下面直接 read(),不先 available():read() 自己就会先查一遍有没有数据(TLS 下是一次
  // mbedtls_ssl_read(NULL,0)),没有就返回 <= 0。以前每段是 connected() + available() + read()
  // 三次查询,现在一次;连接状态只在上面探一次,read 出错时 client 会自己 stop(),
  // 下一轮 connected() 就会发现。
  while (budget > 0) {
    if (s_rx == Rx::HDR || s_rx == Rx::LEN) {
      int got = transportRead(s_hdr + s_hdrGot, s_hdrNeed - s_hdrGot);
      if (got <= 0) return;
      s_hdrGot += got;
      budget   -= got;
      if (s_hdrGot < s_hdrNeed) continue;

      if (s_rx == Rx::HDR) {
        s_fin    = (s_hdr[0] & 0x80) != 0;
        s_opcode = s_hdr[0] & 0x0F;
        const bool    masked = (s_hdr[1] & 0x80) != 0;
        const uint8_t l7     = s_hdr[1] & 0x7F;

        if (masked) {
          // 服务器发给客户端的帧不允许加掩码(RFC 6455 §5.1)。
          // 真收到说明对面不是我们的服务器,或者中间有东西在改流量。
          wsClose("服务器发来带掩码的帧");
          return;
        }
        // opcode 0 是延续帧,类型要沿用上一帧的
        if (s_opcode == 0x1 || s_opcode == 0x2) s_dataType = s_opcode;

        if (l7 == 126) { s_rx = Rx::LEN; s_hdrNeed = 2; s_hdrGot = 0; continue; }
        if (l7 == 127) { wsClose("帧长超过 64 KB,我们的服务器不会这么发"); return; }
        s_remain = l7;
      } else {
        s_remain = ((uint32_t)s_hdr[0] << 8) | s_hdr[1];
      }

      s_rx = Rx::PAY;
      s_hdrNeed = 2; s_hdrGot = 0;
      s_ctlLen = 0;
      if (s_remain == 0) {                      // 零长度帧(比如空 ping)
        if (s_opcode >= 0x8)                 dispatchControl();
        else if (s_fin && s_dataType == 0x1) dispatchText();
        s_rx = Rx::HDR;
        if (!s_up) return;
      }
      continue;
    }

    // ---- payload ----
    const bool isCtl = (s_opcode >= 0x8);
    const bool isBin = (!isCtl && s_dataType == 0x2);

    // 这一段直接读进它的最终去处,不经过中转缓冲:
    //   音频 -> ring 的连续空闲区;控制帧 -> s_ctl;文本 -> s_text;
    //   装不下的 / 不要的(abort 之后的旧音频)-> s_sink,读掉丢弃,保住帧边界。
    uint8_t *dst;
    size_t   room;
    bool     keep = true;
    if (isBin && s_acceptAudio) {
      // 背压:ring 没地方就**别读**,让 TCP 窗口顶回去(AGENT.md §5.3b)。
      if (ringFree() < 64) return;
      room = ringWriteSpan(&dst);                 // 绕回点前面那一段,下一圈从头接着写
    } else if (isCtl && s_ctlLen < sizeof(s_ctl)) {
      dst  = s_ctl + s_ctlLen;
      room = sizeof(s_ctl) - s_ctlLen;
    } else if (!isCtl && !isBin && s_textLen < WS_TEXT_MAX - 1) {
      dst  = (uint8_t *)s_text + s_textLen;
      room = (WS_TEXT_MAX - 1) - s_textLen;
    } else {
      dst  = s_sink;
      room = sizeof(s_sink);
      keep = false;
      if (!isCtl && !isBin) s_textOverflow = true;
    }

    size_t want = s_remain;
    if (want > room)           want = room;
    if (want > (size_t)budget) want = (size_t)budget;

    int got = transportRead(dst, want);
    if (got <= 0) return;
    s_remain -= got;
    budget   -= got;

    if (keep) {
      if (isBin)      { ringCommit(got); s_rxAudio += got; }
      else if (isCtl) { s_ctlLen += got; }
      else            { s_textLen += got; s_text[s_textLen] = 0; }
    }

    if (s_remain == 0) {
      if (isCtl)                dispatchControl();
      else if (s_fin && !isBin) dispatchText();
      s_rx = Rx::HDR;
      if (!s_up) return;                          // dispatchControl 可能已经关了连接
    }
  }
}
