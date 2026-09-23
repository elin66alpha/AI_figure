#include "session.h"
#include "config.h"
#include "secrets.h"
#include "audio_io.h"
#include "button.h"
#include "cue.h"
#include "led.h"
#include "net_wifi.h"
#include "net_ws.h"
#include "proto.h"
#include "ring.h"

// ---------------------------------------------------------------- 状态
static VoiceState s_st = VoiceState::ERROR_STATE;
static Button     s_btn;

static bool     s_ready      = false;   // 收到 {"t":"ready"} 了吗
static uint32_t s_helloAt    = 0;
static uint32_t s_wsRetryAt  = 0;
static uint32_t s_wsBackoff  = WS_RETRY_MIN_MS;

static int32_t  s_seq        = -1;      // 当前回合号(AGENT.md §5.3a)
static bool     s_audioEnded = false;   // 本回合的 audio_end 到了吗
static bool     s_playStarted = false;  // 预缓冲攒够、功放已开
static uint32_t s_waitStart  = 0;

// 上行组包:攒够 100 ms 才发一帧
static int16_t  s_up16[NET_CHUNK_SAMPLES];
static size_t   s_upFill = 0;
static uint32_t s_upDrops = 0, s_upDropStreak = 0;
static uint32_t s_underruns = 0;

// cue 是阻塞的,不能在 wsPoll 的回调里放 —— 攒个标记,回到 sessionUpdate 再播
enum class PendingCue : uint8_t { NONE, LINK_UP, LINK_DOWN, ERR };
static PendingCue s_cue = PendingCue::NONE;

uint32_t sessionUplinkDrops() { return s_upDrops; }
uint32_t sessionUnderruns()   { return s_underruns; }
VoiceState sessionState()     { return s_st; }

const char *sessionStateName() {
  switch (s_st) {
    case VoiceState::IDLE:        return "IDLE";
    case VoiceState::RECORDING:   return "REC";
    case VoiceState::WAITING:     return "WAIT";
    case VoiceState::PLAYING:     return "PLAY";
    default:                      return "ERR";
  }
}

// ---------------------------------------------------------------- 下行控制消息
static void onText(const char *json, size_t len) {
  ProtoMsg m;
  protoParse(json, len, &m);

  switch (m.t) {
    case MsgType::READY:
      // sr 只用于开机断言,不是用来切换配置的(AGENT.md §4)。
      if (m.sr != SAMPLE_RATE_HZ) {
        Serial.printf("[SESS] !! 服务器说采样率是 %ld,设备是 %d —— 全双工共享时钟,"
                      "这个对不上就没法播\n", (long)m.sr, SAMPLE_RATE_HZ);
        wsClose("采样率不一致");
        return;
      }
      s_ready = true;
      s_st = VoiceState::IDLE;
      s_cue = PendingCue::LINK_UP;
      Serial.printf("[SESS] ready sr=%ld —— 可以按按键说话了\n", (long)m.sr);
      break;

    case MsgType::AUDIO_BEGIN:
      // 只有 WAITING 时才认。打断时序下服务器可能刚好把上一回合的 audio_begin
      // 发了出来,此刻设备已经进 RECORDING —— 认了它会把录音打断,而且播的是
      // 已经被 abort 掉的那一轮的声音。
      if (s_st != VoiceState::WAITING) {
        Serial.printf("[SESS] 忽略 %s 状态下的 audio_begin seq=%ld(过期的回合)\n",
                      sessionStateName(), (long)m.seq);
        break;
      }
      s_seq = m.seq;
      ringReset();
      s_audioEnded  = false;
      s_playStarted = false;
      wsSetAudioAccept(true);            // 从这一刻起 binary 帧才算数
      s_st = VoiceState::PLAYING;
      Serial.printf("[SESS] audio_begin seq=%ld\n", (long)m.seq);
      break;

    case MsgType::AUDIO_END:
      if (m.seq == s_seq) {
        s_audioEnded = true;
        Serial.printf("[SESS] audio_end seq=%ld,ring 里还剩 %u 字节\n",
                      (long)m.seq, (unsigned)ringUsed());
      }
      break;

    case MsgType::ASR:
    case MsgType::REPLY:
      Serial.printf("[SESS] %.*s\n", (int)len, json);   // 仅供串口调试
      break;

    case MsgType::CUE:
      // Stage 11 才真正按 name 播不同的音。现在打出来确认链路通。
      Serial.printf("[SESS] cue name=%s (Stage 11 才处理)\n", m.name);
      break;

    case MsgType::ERROR_MSG:
      Serial.printf("[SESS] 服务器报错 code=%s: %.*s\n", m.name, (int)len, json);
      s_cue = PendingCue::ERR;
      break;

    default:
      // 必须静默忽略未知消息,好让服务器先行升级(AGENT.md §5.2 末句)
      break;
  }
}

// ---------------------------------------------------------------- 内部动作
static void stopAudioAll() {
  if (audioIsCapturing()) audioStopCapture();
  if (audioIsPlaying())   audioStopPlayback();
  ringReset();
  wsSetAudioAccept(false);
  s_upFill = 0;
  s_audioEnded = false;
  s_playStarted = false;
}

static void enterError(const char *why) {
  if (s_st == VoiceState::ERROR_STATE) return;
  Serial.printf("[SESS] -> ERROR (%s)\n", why);
  stopAudioAll();
  s_ready = false;
  s_st = VoiceState::ERROR_STATE;
  s_cue = PendingCue::LINK_DOWN;
}

static void startRecording() {
  if (!wsSendText(PROTO_TURN_START)) { enterError("turn_start 发不出去"); return; }
  if (!audioStartCapture())          { enterError("录音启动失败");        return; }
  s_upFill = 0;
  s_upDropStreak = 0;
  s_st = VoiceState::RECORDING;
  ledSet(LedMode::ON);
  Serial.println("[SESS] turn_start —— 录音中");
}

// 打断。AGENT.md §8:**先发 abort 再关功放** ——
// abort 是上行,不受下行缓冲拥塞影响,越早发服务器越早停止烧 token。
static void bargeIn() {
  wsSendText(PROTO_ABORT);
  stopAudioAll();
  s_seq = -1;                 // 到下一个 audio_begin 之前的 binary 帧全丢
  Serial.println("[SESS] abort(打断)");
}

// 把攒着的样本发出去。返回 false 表示链路坏了。
static bool flushUplink() {
  if (s_upFill == 0) return true;
  const bool ok = wsSendBinary((const uint8_t *)s_up16, s_upFill * sizeof(int16_t));
  s_upFill = 0;

  if (ok) { s_upDropStreak = 0; return true; }

  // 整帧丢弃而不是发半帧 —— WS 帧发一半会破坏帧边界。
  // ASR 丢 100 ms 比整条链路卡死强(AGENT.md §9.2)。
  s_upDrops++;
  if (++s_upDropStreak >= WS_UPLINK_DROP_LIMIT) {
    Serial.printf("[SESS] 连续丢了 %u 个上行帧,链路不行了\n", (unsigned)s_upDropStreak);
    return false;
  }
  return true;
}

// ---------------------------------------------------------------- 各状态
static void doRecording() {
  static int16_t frame[FRAME_SAMPLES];

  // audioRead 阻塞 ~20 ms,这就是 RECORDING 状态的节拍器。
  size_t got = audioRead(frame, FRAME_SAMPLES, 25);
  for (size_t i = 0; i < got; i++) {
    s_up16[s_upFill++] = frame[i];
    if (s_upFill >= NET_CHUNK_SAMPLES) {
      if (!flushUplink()) { wsClose("上行持续失败"); return; }
    }
  }

  if (s_btn.tookRelease()) {
    flushUplink();                                   // 把不足 100 ms 的尾巴也发掉
    audioStopCapture();
    if (!wsSendText(PROTO_TURN_END)) { enterError("turn_end 发不出去"); return; }
    s_st = VoiceState::WAITING;
    s_waitStart = millis();
    ledSet(LedMode::BLINK_FAST);
    Serial.println("[SESS] turn_end —— 等服务器");
  }
}

static void doWaiting() {
  if (millis() - s_waitStart > WAITING_TIMEOUT_MS) {
    Serial.printf("[SESS] 等了 %d ms 没等到 audio_begin,放弃\n", WAITING_TIMEOUT_MS);
    wsSendText(PROTO_ABORT);
    s_st = VoiceState::IDLE;
    s_cue = PendingCue::ERR;
  }
}

static void doPlaying() {
  static int16_t frame[FRAME_SAMPLES];

  if (!s_playStarted) {
    // 攒够预缓冲再起播(AGENT.md §4)。回复很短、没攒够就收到 audio_end 的话,
    // 也得起播,否则会一直等一个永远不来的字节。
    if (ringUsed() >= PREBUFFER_BYTES || s_audioEnded) {
      if (!audioStartPlayback(true)) { enterError("播放启动失败"); return; }
      s_playStarted = true;
      ledSet(LedMode::ON);
      Serial.printf("[SESS] 起播,预缓冲 %u 字节 (%u ms)\n",
                    (unsigned)ringUsed(),
                    (unsigned)(ringUsed() * 1000 / (SAMPLE_RATE_HZ * 2)));
    }
    return;
  }

  size_t n = ringRead((uint8_t *)frame, sizeof(frame));
  if (n > 0) {
    // audioWrite 阻塞到 DMA 腾出空间,这是 PLAYING 状态的节拍器。
    audioWrite(frame, n / sizeof(int16_t), 60);
  } else if (s_audioEnded) {
    audioStopPlayback();                  // 内含补静音 -> drain -> 关功放
    wsSetAudioAccept(false);
    s_st = VoiceState::IDLE;
    Serial.printf("[SESS] 本回合结束。TX 欠载 %lu 次,ring 见底 %lu 次\n",
                  (unsigned long)audioTxUnderruns(), (unsigned long)s_underruns);
  } else {
    // ring 见底但服务器还没说完 —— 网络跟不上。
    // 不用喂静音:auto_clear 已经在硬件层面输出零了(AGENT.md §4)。
    s_underruns++;
    delay(2);
  }
}

// ---------------------------------------------------------------- 对外
void sessionBegin() {
  s_btn.begin(PIN_PTT_BUTTON, BUTTON_DEBOUNCE_MS);
  wsSetTextHandler(onText);
  s_st = VoiceState::ERROR_STATE;
  s_wsRetryAt = 0;
}

void sessionUpdate() {
  s_btn.update();

  // ---- 挂了阻塞的 cue,回到这里才播 ----
  if (s_cue != PendingCue::NONE) {
    PendingCue c = s_cue;
    s_cue = PendingCue::NONE;
    if      (c == PendingCue::LINK_UP)   cueLinkUp();
    else if (c == PendingCue::LINK_DOWN) cueLinkDown();
    else                                 cueError();
  }

  // ---- WiFi ----
  if (!netWifiIsUp()) {
    enterError("WiFi 未连接");
    ledSet(LedMode::BLINK_SLOW);
    if (s_btn.tookPress()) netWifiForceRetry();      // AGENT.md §8
    s_btn.clearEvents();
    return;
  }

  // ---- WS ----
  if (!wsIsConnected()) {
    enterError("WS 未连接");
    ledSet(LedMode::BLINK_SLOW);

    if (s_btn.tookPress()) { s_wsRetryAt = millis(); s_wsBackoff = WS_RETRY_MIN_MS; }
    s_btn.clearEvents();

    if ((int32_t)(millis() - s_wsRetryAt) >= 0) {
      if (wsConnect()) {
        char hello[96];
        size_t n = protoBuildHello(hello, sizeof(hello), DEVICE_ID, FW_VERSION);
        if (n && wsSendText(hello)) {
          s_helloAt = millis();
          s_wsBackoff = WS_RETRY_MIN_MS;
          ledSet(LedMode::BLINK_FAST);
        } else {
          wsClose("hello 发不出去");
        }
      } else {
        s_wsRetryAt = millis() + s_wsBackoff;
        s_wsBackoff *= 2;
        if (s_wsBackoff > WS_RETRY_MAX_MS) s_wsBackoff = WS_RETRY_MAX_MS;
      }
    }
    return;
  }

  wsPoll();
  if (!wsIsConnected()) return;          // wsPoll 里可能刚断掉

  // ---- 等 ready ----
  if (!s_ready) {
    // 握手期间按的键不算数,否则一收到 ready 就会莫名其妙开始录音
    s_btn.clearEvents();
    if (millis() - s_helloAt > WS_HANDSHAKE_TIMEOUT_MS) {
      wsClose("发了 hello 但服务器没回 ready");
      s_wsRetryAt = millis() + s_wsBackoff;
    }
    return;
  }

  // ---- 打断:任意非 IDLE 状态按下按钮(AGENT.md §8) ----
  if (s_btn.tookPress()) {
    if (s_st == VoiceState::IDLE) {
      startRecording();
    } else if (s_st != VoiceState::RECORDING) {
      bargeIn();
      startRecording();
    }
  }

  switch (s_st) {
    case VoiceState::IDLE:      ledSet(LedMode::HEARTBEAT); break;
    case VoiceState::RECORDING: doRecording(); break;
    case VoiceState::WAITING:   doWaiting();   break;
    case VoiceState::PLAYING:   doPlaying();   break;
    default: break;
  }
}
