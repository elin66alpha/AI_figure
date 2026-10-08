#pragma once
#include <stdint.h>
#include <stddef.h>

// 设备 ↔ 服务器控制消息的编解码。协议见 AGENT.md §5.2。
//
// **手写字符串匹配,不引 ArduinoJson**(AGENT.md §5.4)。理由是消息就这几种、
// 字段就这几个,而 ArduinoJson 会为每条消息在 150 KB 的堆上开文档对象 ——
// 为了省那点解析代码去换堆碎片不划算。
//
// 上行只有 hello 带参数,其余三条是编译期常量,直接发字面量。

#define PROTO_TURN_START  "{\"t\":\"turn_start\"}"
#define PROTO_TURN_END    "{\"t\":\"turn_end\"}"
#define PROTO_ABORT       "{\"t\":\"abort\"}"

enum class MsgType : uint8_t {
  UNKNOWN,        // 必须静默忽略,好让服务器先行升级(AGENT.md §5.2 末句)
  READY,
  CUE,
  AUDIO_BEGIN,
  AUDIO_END,
  ASR,
  REPLY,
  ERROR_MSG,
};

struct ProtoMsg {
  MsgType t;
  int32_t seq;          // audio_begin / audio_end
  int32_t sr;           // ready
  char    name[24];     // cue 的 name / error 的 code
};

// 把 hello 写进 out,返回长度(失败返回 0)。
size_t protoBuildHello(char *out, size_t cap, const char *dev, const char *fw);

// 解析一条文本帧。json 不需要以 \0 结尾,len 说了算。
void protoParse(const char *json, size_t len, ProtoMsg *out);
