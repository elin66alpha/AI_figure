#include "net_ws.h"
#include "config.h"
#include "secrets.h"
#include "ring.h"

#include <WiFi.h>
#include <esp_random.h>
#include <lwip/sockets.h>

// rev.5:默认走 wss://(TLS-PSK)。SERVER_USE_TLS=0 可以退回明文,
// 用来在局域网里不架 stunnel 直连调试。
//
// 两条路的客户端对象方法签名完全一样(NetworkClientSecure 就是 NetworkClient 的子类),
// 所以下面的收发代码一份,不用分叉。
#ifndef SERVER_USE_TLS
  // 不给默认值是故意的。老的 secrets.h 里没有这个宏 —— 要是这里默默退回明文,
  // 那就是拿着公网地址在裸奔,而且**一切看起来都正常**。宁可编译不过。
  #error "secrets.h 里缺 SERVER_USE_TLS。照 secrets.h.example 补上(公网部署填 1)。"
#endif

#if SERVER_USE_TLS
  #include <NetworkClientSecure.h>
  static NetworkClientSecure s_cli;
  // PSK 空着就等于没鉴权,而 stunnel 那边会直接拒绝握手 ——
  // 与其烧进去再对着串口猜,不如编译期就拦下。
  static_assert(sizeof(PSK_IDENTITY) > 1, "PSK_IDENTITY 是空的,填 secrets.h(见 esp32_server/deploy/README.md §0)");
  static_assert(sizeof(PSK_KEY_HEX) == 65, "PSK_KEY_HEX 必须是 64 位 hex(32 字节)—— 设备侧 MBEDTLS_PSK_MAX_LEN 在 TLS1.3 关闭时就是 32");
#else
  #include <NetworkClient.h>
  static NetworkClient s_cli;
#endif

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

static bool     s_acceptAudio = false;
static uint32_t s_rxAudio = 0;

static uint32_t s_lastPingSent = 0;
static uint32_t s_lastPong     = 0;

// 上行组帧缓冲。最大一帧 = 8 字节头 + 一个 100 ms 音频包。
static uint8_t  s_tx[8 + NET_CHUNK_BYTES];

void wsSetTextHandler(WsTextHandler h) { s_onText = h; }
void wsSetAudioAccept(bool on)         { s_acceptAudio = on; }
uint32_t wsRxAudioBytes()              { return s_rxAudio; }
bool wsIsConnected()                   { return s_up && s_cli.connected(); }

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

// 在写之前先问一句"socket 现在能写吗"。
//
// 为什么非问不可:NetworkClient::write() 内部是 10 次重试 x 每次 select 等 1 秒,
// 也就是**最坏能阻塞 10 秒**,而且这个上限不受 setTimeout() 控制(setTimeout 只
// 管 SO_SNDTIMEO)。10 秒的阻塞会直接把 20 ms 的音频循环撕碎。
// 先自己 select 一把,把常见的"发送窗口满"挡在 write() 之外。
static bool writable(uint32_t timeoutMs) {
  int fd = s_cli.fd();
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
static bool sendFrame(uint8_t opcode, const uint8_t *payload, size_t len, uint32_t timeoutMs) {
  if (!wsIsConnected()) return false;
  if (len > NET_CHUNK_BYTES) return false;

  size_t h = 0;
  s_tx[h++] = 0x80 | opcode;                 // FIN=1,上行不分片
  if (len < 126) {
    s_tx[h++] = 0x80 | (uint8_t)len;
  } else {
    s_tx[h++] = 0x80 | 126;
    s_tx[h++] = (uint8_t)(len >> 8);
    s_tx[h++] = (uint8_t)(len & 0xFF);
  }

  uint8_t mask[4];
  uint32_t r = esp_random();
  memcpy(mask, &r, 4);
  memcpy(s_tx + h, mask, 4);
  h += 4;

  for (size_t i = 0; i < len; i++) s_tx[h + i] = payload[i] ^ mask[i & 3];
  const size_t total = h + len;

  // 只在 socket 可写时才进 write()。lwIP 的发送缓冲是 5744 字节
  // (CONFIG_LWIP_TCP_SND_BUF_DEFAULT),一个 3208 字节的音频帧通常能一次吃下,
  // 所以"可写"之后基本不会发生部分写。残留风险写在 writable() 上面。
  if (!writable(timeoutMs)) return false;

  size_t w = s_cli.write(s_tx, total);
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
  if (s_up && why) Serial.printf("[WS] 断开:%s\n", why);
  s_cli.stop();
  s_up = false;
  s_rx = Rx::HDR;
  s_hdrNeed = 2; s_hdrGot = 0;
  s_remain = 0;
  s_textLen = 0; s_textOverflow = false;
  s_acceptAudio = false;
}

bool wsConnect() {
  wsClose(nullptr);

#if SERVER_USE_TLS
  Serial.printf("[WS] 连接 wss://%s:%d%s  (TLS-PSK, ident=%s)\n",
                SERVER_HOST, SERVER_PORT, SERVER_WS_PATH, PSK_IDENTITY);

  // 纯 PSK,不装 CA。
  //
  // ⚠️ **不要同时调 setCACert()。** arduino-esp32 3.3.12 的 ssl_client.cpp 里
  // CA / CA-bundle / PSK 是一串 else-if,CA 排在前面 —— 两个都设的话 PSK 会被直接
  // 无视,然后握手挂在一个和 PSK 毫无关系的错误上,很难查。
  //
  // 服务器侧对应 stunnel 的 PSKsecrets(esp32_server/deploy/stunnel.conf),
  // 那边钉死了 TLS 1.2 + 纯 PSK 套件,两条都是必须的:
  //   - 本 core 的预编译 IDF 里 CONFIG_MBEDTLS_SSL_PROTO_TLS1_3 **没开**,设备不会 1.3
  //   - RSA-PSK 会让服务器下发证书链,而 PSK 分支下没装 CA,验证必挂
  s_cli.setPreSharedKey(PSK_IDENTITY, PSK_KEY_HEX);
  s_cli.setHandshakeTimeout(WS_TLS_HANDSHAKE_TIMEOUT_S);   // 这个 API 的单位是**秒**
#else
  Serial.printf("[WS] 连接 ws://%s:%d%s  (明文)\n", SERVER_HOST, SERVER_PORT, SERVER_WS_PATH);
#endif

  // 第三个参数同时是 **TCP connect 预算**和 **TLS 写操作的停滞上限**:
  // ssl_client.cpp 在 connect 时把它存进 socket_timeout,之后 send_ssl_data()
  // 拿它当"多久没有进展就放弃"的窗口,而且**后面再调 setTimeout() 也改不动它**。
  // 所以这个值不能给大:给 10 s 就意味着某次上行可能把 20 ms 的音频循环卡住 10 s。
  // TLS 握手有自己独立的预算(setHandshakeTimeout),不受这里限制。
  if (!s_cli.connect(SERVER_HOST, SERVER_PORT, WS_TCP_CONNECT_TIMEOUT_MS)) {
#if SERVER_USE_TLS
    Serial.println("[WS] 连不上,或者 TLS 握手失败。按顺序查:");
    Serial.println("     1) 域名解析对不对、VPS 的 443 在不在听(ss -lntp)");
    Serial.println("     2) 云厂商**安全组**放行了没 —— 和系统防火墙是两道独立的墙");
    Serial.println("     3) PSK_IDENTITY/PSK_KEY_HEX 和 VPS 的 psk.secrets 对不对得上");
    Serial.println("     4) stunnel 是不是钉在 TLS1.2 + 纯 PSK 套件上");
#else
    Serial.println("[WS] TCP 连不上。查:IP 填对没、服务器在跑没、PC 防火墙放行没");
#endif
    return false;
  }
#if SERVER_USE_TLS
  // AGENT.md §5.6 那张预算表说纯 PSK 的握手峰值 ~67 KB —— 这一行就是"真实数字"。
  // maxAlloc 掉到 HEAP_MIN_MAXALLOC(24 KB)附近就说明余量不够了,别等现场重启才发现。
  Serial.printf("[WS] TLS 握手成功,剩余堆 %u B / 最大可分配块 %u B\n",
                (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getMaxAllocHeap());
#endif
  s_cli.setNoDelay(true);                 // 100 ms 一包的音频,不能让 Nagle 压着
  s_cli.setTimeout(WS_SEND_TIMEOUT_MS);

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

  s_cli.printf("GET %s HTTP/1.1\r\n"
               "Host: %s\r\n"
               "Upgrade: websocket\r\n"
               "Connection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n"
               "\r\n",
               SERVER_WS_PATH, hostHdr, key);

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
  const uint32_t t0 = millis();
  while (millis() - t0 < WS_HANDSHAKE_TIMEOUT_MS) {
    if (!s_cli.connected() && !s_cli.available()) break;
    int c = s_cli.read();
    if (c < 0) { delay(2); continue; }
    if (c == 0x0A) {                                  // '\n'
      line[n] = 0;
      if (firstLine) {
        got101 = (strstr(line, " 101") != nullptr);
        if (!got101) Serial.printf("[WS] 握手被拒:%s\n", line);
        firstLine = false;
      }
      if (n == 0 || (n == 1 && line[0] == 0x0D)) {    // 空行 = 头结束
        if (got101) {
          s_up = true;
          s_lastPong = millis();
          s_lastPingSent = millis();
          Serial.println("[WS] 握手成功");
          return true;
        }
        break;
      }
      n = 0;
    } else if (n + 1 < sizeof(line)) {
      line[n++] = (char)c;
    }
  }

  Serial.println("[WS] 握手失败");
  s_cli.stop();
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
      s_lastPong = millis();
      break;
    default:
      break;
  }
}

static void dispatchText() {
  if (s_textOverflow)
    Serial.printf("[WS] 控制消息超过 %d 字节,已截断\n", WS_TEXT_MAX);
  if (s_onText && s_textLen) s_onText(s_text, s_textLen);
  s_textLen = 0;
  s_textOverflow = false;
}

void wsPoll() {
  if (!s_up) return;
  if (!s_cli.connected()) { wsClose("TCP 断了"); return; }

  // 保活。AGENT.md §5.1:30 s 一次 ping,连续两次无 pong 视为断线。
  const uint32_t now = millis();
  if (now - s_lastPingSent >= WS_PING_INTERVAL_MS) {
    s_lastPingSent = now;
    sendFrame(0x9, nullptr, 0, WS_AUDIO_SEND_TIMEOUT_MS);
  }
  if (now - s_lastPong > WS_PONG_TIMEOUT_MS) { wsClose("pong 超时"); return; }

  // 每次 poll 最多搬这么多字节。20 ms 的节拍里真正到达的只有 ~640 字节,
  // 留了 6 倍余量;这个上限的意义是**保证 wsPoll 一定会把控制权还给音频循环**。
  int budget = 4096;

  while (budget > 0 && s_cli.connected()) {
    if (s_rx == Rx::HDR || s_rx == Rx::LEN) {
      int avail = s_cli.available();
      if (avail <= 0) return;
      int want = (int)s_hdrNeed - (int)s_hdrGot;
      if (want > avail) want = avail;
      int got = s_cli.read(s_hdr + s_hdrGot, want);
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

    int avail = s_cli.available();
    if (avail <= 0) return;

    uint8_t tmp[256];
    size_t want = s_remain;
    if (want > sizeof(tmp))    want = sizeof(tmp);
    if (want > (size_t)avail)  want = (size_t)avail;
    if (want > (size_t)budget) want = (size_t)budget;

    if (isBin && s_acceptAudio) {
      // 背压:ring 没地方就**别读**,让 TCP 窗口顶回去(AGENT.md §5.3b)。
      size_t space = ringFree();
      if (space < 64) return;
      if (want > space) want = space;
    }
    if (want == 0) return;

    int got = s_cli.read(tmp, want);
    if (got <= 0) return;
    s_remain -= got;
    budget   -= got;

    if (isCtl) {
      size_t room = sizeof(s_ctl) - s_ctlLen;
      size_t cp   = ((size_t)got < room) ? (size_t)got : room;
      memcpy(s_ctl + s_ctlLen, tmp, cp);
      s_ctlLen += cp;
    } else if (isBin) {
      // 不收音频时读掉但丢弃,保住帧边界
      if (s_acceptAudio) s_rxAudio += ringWrite(tmp, got);
    } else {
      size_t room = (WS_TEXT_MAX - 1) - s_textLen;
      if ((size_t)got > room) s_textOverflow = true;
      size_t cp = ((size_t)got < room) ? (size_t)got : room;
      memcpy(s_text + s_textLen, tmp, cp);
      s_textLen += cp;
      s_text[s_textLen] = 0;
    }

    if (s_remain == 0) {
      if (isCtl)                dispatchControl();
      else if (s_fin && !isBin) dispatchText();
      s_rx = Rx::HDR;
      if (!s_up) return;                          // dispatchControl 可能已经关了连接
    }
  }
}
