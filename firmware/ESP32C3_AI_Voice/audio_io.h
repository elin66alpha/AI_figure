#pragma once
#include <stdint.h>
#include <stddef.h>

// Independent PDM RX and I2S TX on ESP32-C3 I2S0, application half duplex.
// Both clocks stop when inactive. External format remains 16 kHz mono PCM16.
bool audioBegin();
bool audioStartCapture();
void audioStopCapture();
bool audioIsCapturing();
size_t audioRead(int16_t *dst, size_t maxSamples, uint32_t timeoutMs);

bool audioStartPlayback();
void audioStopPlayback(); // Drain queued audio, disable amp and TX.
void audioCutPlayback();  // Immediate interruption, no tail.
bool audioIsPlaying();
size_t audioWrite(const int16_t *src, size_t samples, uint32_t timeoutMs);
uint32_t audioTxUnderruns();
void setOutputGain(uint16_t gain); // 0..256; microphone gain is in config.h.
uint16_t getOutputGain();
