#include "platform.h"
#include "ring.h"
#include "config.h"

static uint8_t s_buf[RING_BYTES];
static size_t  s_head = 0;    // 下一个写入位置
static size_t  s_tail = 0;    // 下一个读出位置
static size_t  s_used = 0;

void   ringReset()    { s_head = s_tail = s_used = 0; }
size_t ringUsed()     { return s_used; }
size_t ringFree()     { return RING_BYTES - s_used; }
size_t ringCapacity() { return RING_BYTES; }

size_t ringWriteSpan(uint8_t **p) {
  *p = s_buf + s_head;
  const size_t space = RING_BYTES - s_used;
  const size_t tail  = RING_BYTES - s_head;       // 到数组末尾还有多少
  return space < tail ? space : tail;
}

void ringCommit(size_t n) {
  s_head = (s_head + n) % RING_BYTES;
  s_used += n;
}

size_t ringRead(uint8_t *dst, size_t n) {
  if (!dst) return 0;
  if (n > s_used) n = s_used;
  n &= ~(size_t)1;              // 保持 int16 对齐,见 ring.h
  if (n == 0) return 0;

  size_t first = RING_BYTES - s_tail;
  if (first > n) first = n;
  memcpy(dst, s_buf + s_tail, first);
  if (n > first) memcpy(dst + first, s_buf, n - first);

  s_tail = (s_tail + n) % RING_BYTES;
  s_used -= n;
  return n;
}
