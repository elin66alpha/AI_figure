#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stddef.h>

// 极简 WebSocket 客户端(RFC 6455 客户端侧)。
//
// **为什么不用 Links2004/arduinoWebSockets 之类的现成库**(AGENT.md §7 第 2 条):
// 现成库会把**整帧**组装进 RAM 再回调。服务器一次突发 300 ms = 9600 字节,
// 在 150 KB 的堆上反复要这么大的连续块,离堆碎片化只有一步。
// 这里做到的是:读帧头 -> 读长度 -> **边从 socket 读边直接写进 ring**,
// 全程不落地完整帧,内存恒定。
//
// 用 opcode 区分控制和音频,不自定义帧头(AGENT.md §5.1):
//   Binary frame = 裸 PCM16LE/16 kHz/单声道
//   Text   frame = JSON 控制消息
//
// 背压(AGENT.md §5.3b):ring 没空间时就**不从 socket 读**,TCP 窗口自然反压到
// 服务器。副作用是此时控制帧也读不到 —— 可接受,那会儿唯一需要及时送达的是
// 上行 abort,方向相反不受影响。

typedef void (*WsTextHandler)(const char *json, size_t len);

void wsSetTextHandler(WsTextHandler h);

bool wsConnect();                  // 用 secrets.h 里的地址。阻塞几百 ms,只在 IDLE 调
void wsClose(const char *why);
bool wsIsConnected();

void wsPoll();                     // 每次 loop 调。推进接收状态机 + 保活

bool wsSendText(const char *s);
bool wsSendBinary(const uint8_t *data, size_t n);

// 上行音频帧的 payload 区(NET_CHUNK_SAMPLES 个样本)。录音直接写进这里,
// 再 wsSendBinary(本指针, 字节数) —— 走零拷贝路径,原地加掩码发出。
// 发送之后这块内容已被掩码改写,只能重新填,不能再读。
int16_t *wsAudioTxBuf();

// seq 门控(AGENT.md §5.3a):关掉之后 binary 帧照读不误(否则帧边界就乱了),
// 但读完直接丢弃,不进 ring。abort 之后到下一个 audio_begin 之间就靠它。
void wsSetAudioAccept(bool on);

uint32_t wsRxAudioBytes();
