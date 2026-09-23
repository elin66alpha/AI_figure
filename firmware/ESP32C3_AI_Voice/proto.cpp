#include "proto.h"
#include <string.h>
#include <stdlib.h>

// 在 [s, s+len) 里找 "key": ,返回值起始位置(跳过冒号和空格);找不到返回 nullptr。
// 只处理我们自己服务器发的那几种规整 JSON,不处理转义、嵌套、数组。
static const char *findValue(const char *s, size_t len, const char *key) {
  char pat[24];
  const size_t kl = strlen(key);
  if (kl + 4 > sizeof(pat)) return nullptr;
  pat[0] = '"';
  memcpy(pat + 1, key, kl);
  pat[kl + 1] = '"';
  pat[kl + 2] = ':';
  pat[kl + 3] = '\0';
  const size_t pl = kl + 3;

  if (len < pl) return nullptr;
  for (size_t i = 0; i + pl <= len; i++) {
    if (memcmp(s + i, pat, pl) == 0) {
      const char *p = s + i + pl;
      while (p < s + len && (*p == ' ' || *p == '\t')) p++;
      return (p < s + len) ? p : nullptr;
    }
  }
  return nullptr;
}

static int32_t readInt(const char *p, const char *end, int32_t dflt) {
  if (!p) return dflt;
  bool neg = false;
  if (*p == '-') { neg = true; p++; }
  if (p >= end || *p < '0' || *p > '9') return dflt;
  int32_t v = 0;
  while (p < end && *p >= '0' && *p <= '9') { v = v * 10 + (*p - '0'); p++; }
  return neg ? -v : v;
}

// 读一个带引号的字符串到 dst(截断,始终以 \0 结尾)。
static void readStr(const char *p, const char *end, char *dst, size_t cap) {
  dst[0] = '\0';
  if (!p || p >= end || *p != '"') return;
  p++;
  size_t i = 0;
  while (p < end && *p != '"' && i + 1 < cap) dst[i++] = *p++;
  dst[i] = '\0';
}

size_t protoBuildHello(char *out, size_t cap, const char *dev, const char *fw) {
  int n = snprintf(out, cap, "{\"t\":\"hello\",\"dev\":\"%s\",\"fw\":\"%s\"}", dev, fw);
  return (n > 0 && (size_t)n < cap) ? (size_t)n : 0;
}

void protoParse(const char *json, size_t len, ProtoMsg *out) {
  out->t = MsgType::UNKNOWN;
  out->seq = -1;
  out->sr = 0;
  out->name[0] = '\0';

  const char *end = json + len;
  const char *v = findValue(json, len, "t");
  if (!v || *v != '"') return;
  const char *t = v + 1;

  // 逐个比。第一个字符先过一遍,省掉大部分 memcmp。
  struct { const char *s; MsgType m; } tbl[] = {
    { "ready",       MsgType::READY       },
    { "cue",         MsgType::CUE         },
    { "audio_begin", MsgType::AUDIO_BEGIN },
    { "audio_end",   MsgType::AUDIO_END   },
    { "asr",         MsgType::ASR         },
    { "reply",       MsgType::REPLY       },
    { "error",       MsgType::ERROR_MSG   },
  };
  for (auto &e : tbl) {
    const size_t l = strlen(e.s);
    if ((size_t)(end - t) > l && memcmp(t, e.s, l) == 0 && t[l] == '"') {
      out->t = e.m;
      break;
    }
  }

  switch (out->t) {
    case MsgType::READY:
      out->sr = readInt(findValue(json, len, "sr"), end, 0);
      break;
    case MsgType::AUDIO_BEGIN:
    case MsgType::AUDIO_END:
      out->seq = readInt(findValue(json, len, "seq"), end, -1);
      break;
    case MsgType::CUE:
      readStr(findValue(json, len, "name"), end, out->name, sizeof(out->name));
      break;
    case MsgType::ERROR_MSG:
      readStr(findValue(json, len, "code"), end, out->name, sizeof(out->name));
      break;
    default:
      break;
  }
}
