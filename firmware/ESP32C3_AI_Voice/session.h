#pragma once
#include <Arduino.h>

// 设备状态机。规格见 AGENT.md §8。
//
// rev.1 的 ASR_FINALIZING / LLM_THINKING / TTS_FETCHING 三个状态合并成了 WAITING:
// 设备不知道服务器走到哪一步,硬猜只会猜错。想要分段提示音就由服务器发
// {"t":"cue"} 驱动 —— 服务器知道真实进度,比设备猜准。
//
// 超时也跟着简化:设备只保留一个总超时(WAITING_TIMEOUT_MS,从 turn_end 起算
// 到收到 audio_begin),分段超时归服务器管。

enum class VoiceState : uint8_t {
  IDLE,          // 功放关,等按键。WS 已连接且已收到 ready
  RECORDING,     // 按住:边录边推 100 ms PCM 帧
  WAITING,       // 松开:已发 turn_end,等服务器
  PLAYING,       // 收到 audio_begin,播放中(仍在下载)
  ERROR_STATE,   // WiFi 或 WS 断了。此状态下按键 = 立刻重连
};

void        sessionBegin();
void        sessionUpdate();          // 每次 loop 调一次
VoiceState  sessionState();
const char *sessionStateName();

// 进遥测用
uint32_t sessionUplinkDrops();        // 上行因为拥塞被整帧丢掉的次数
uint32_t sessionUnderruns();          // 播放时 ring 见底的次数
