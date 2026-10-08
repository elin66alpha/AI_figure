#pragma once
#include <stddef.h>
#include <stdint.h>

bool transportConnect();
void transportClose();
bool transportConnected();
int transportFd();
int transportRead(uint8_t *dst, size_t n);  // Nonblocking; -1 if no data is available.
size_t transportWrite(const uint8_t *src, size_t n, uint32_t timeoutMs);
