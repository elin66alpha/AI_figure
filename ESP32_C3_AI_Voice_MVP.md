# ESP32-C3 Half-Duplex AI Voice MVP — Agent Build Spec

## 1. Goal

Build the fastest possible Arduino-based MVP for a push-to-talk, half-duplex AI voice terminal using:

- ESP32-C3 SuperMini
- INMP441 I2S digital microphone
- MAX98357A I2S Class-D amplifier
- 4Ω / 3W speaker
- 2-pin momentary push button
- Wi-Fi
- Cloud AI server

Target interaction:

```text
Hold button
→ speaker muted
→ microphone records
→ PCM audio streams to server while recording

Release button
→ stop recording
→ send END_OF_TURN

Server returns audio stream
→ enable amplifier
→ play audio immediately as chunks arrive

Press button during playback
→ stop playback immediately
→ mute amplifier
→ start new recording turn
```

This is a strict half-duplex system. Recording and playback must never happen at the same time.

---

## 2. Hardware Wiring — Do Not Change Unless Necessary

### ESP32-C3 SuperMini ↔ INMP441

| ESP32-C3 | INMP441 | Purpose |
|---|---|---|
| 3V3 | VDD | Microphone power |
| GND | GND | Ground |
| GPIO4 | SCK | I2S bit clock |
| GPIO5 | WS | I2S word select / LR clock |
| GPIO6 | SD | Microphone data into ESP32 |
| GND | L/R | Select left channel |

### ESP32-C3 SuperMini ↔ MAX98357A

| ESP32-C3 | MAX98357A | Purpose |
|---|---|---|
| 5V | VIN | Amplifier power |
| GND | GND | Ground |
| GPIO4 | BCLK | Shared I2S bit clock |
| GPIO5 | LRC | Shared I2S LR clock |
| GPIO7 | DIN | Audio data from ESP32 |
| GPIO10 | SD | Amplifier shutdown; HIGH also selects the left I2S channel |
| — | GAIN | Leave unconnected for MVP |

Important MAX98357A note:

```text
GPIO10 LOW  → shutdown
GPIO10 HIGH → amplifier active + LEFT channel selected
```

Therefore playback must put the mono response samples in the **left I2S slot** (or duplicate the sample to both left and right slots).

### Push Button

```text
GPIO3 ─── Button ─── GND
```

Firmware:

```cpp
pinMode(3, INPUT_PULLUP);
```

Logic:

```text
Released = HIGH
Pressed  = LOW
```

Use software debounce around 20–30 ms.

### Speaker

Connect the 4Ω / 3W speaker directly to the MAX98357A speaker outputs:

```text
MAX98357A SPK+ → Speaker +
MAX98357A SPK- → Speaker -
```

Do not connect either speaker output to GND.

### INMP441 SD Pulldown

The INMP441 datasheet recommends a **100 kΩ pulldown from SD to GND** because SD becomes high-impedance during the unselected I2S slot.

Many breakout boards already include this resistor. Check the module. If it is not present, add:

```text
INMP441 SD ── 100 kΩ ── GND
```

This is recommended for signal robustness, not a different GPIO assignment.

---

## 3. Pin Constants

Use one central header/config file.

```cpp
#define PIN_I2S_BCLK      4
#define PIN_I2S_WS        5
#define PIN_MIC_DATA      6
#define PIN_AMP_DATA      7
#define PIN_AMP_SD       10
#define PIN_PTT_BUTTON    3
```

Do not scatter GPIO numbers throughout the codebase.

---

## 4. Important Hardware Architecture

GPIO4 and GPIO5 are intentionally shared.

The chosen GPIO assignment is valid for ESP32-C3. GPIO2, GPIO8, and GPIO9 are the ESP32-C3 boot strapping pins and are intentionally avoided. GPIO4–GPIO7 are JTAG-capable pins, but they can be reassigned through the GPIO matrix for I2S when hardware JTAG is not being used.

GPIO4 and GPIO5 are intentionally shared:

```text
GPIO4 ──┬── INMP441 SCK
        └── MAX98357A BCLK

GPIO5 ──┬── INMP441 WS
        └── MAX98357A LRC
```

ESP32-C3 has one I2S peripheral, which is sufficient because the product is half-duplex.

Firmware must switch the I2S peripheral between:

```text
RECORDING:
I2S RX
INMP441 → ESP32

PLAYBACK:
I2S TX
ESP32 → MAX98357A
```

Never run RX and TX simultaneously.

---

## 5. Audio Format

Keep the **physical I2S bus format** separate from the **network audio format**.

### INMP441 capture bus

The INMP441 requires standard I2S with:

```text
WS/sample rate:  16,000 Hz
Slots:           2 slots per frame (left + right)
Slot width:      32 bits
BCLK:            64 × WS = 1.024 MHz at 16 kHz
Microphone data: 24-bit two's-complement
Selected slot:   LEFT, because L/R is tied to GND
```

Even though only one microphone is present, the INMP441 still requires **64 BCLK cycles per WS frame / 32 clocks per slot**.

Capture the left slot as a 32-bit word, extract the valid 24-bit microphone sample, then convert/scaled-shift it to signed PCM16.

### Network audio

For the MVP send:

```text
Sample rate:     16,000 Hz
Format:          signed PCM16 little-endian
Channels:        mono
Transport:       raw PCM binary chunks
```

### MAX98357A playback bus

MAX98357A accepts standard I2S at 16 kHz and supports 16/24/32-bit audio words.

Because GPIO10 drives `SD` directly HIGH during playback, the MAX98357A selects the **left I2S channel**. The firmware must therefore:

```text
put response PCM in the LEFT slot
```

or simply duplicate the mono sample into both left and right slots.

Do not confuse `PCM16 mono over the network` with the INMP441's required physical I2S framing.

---

## 6. Explicit Non-Goals

Do not implement any of the following unless required later:

- SD card
- WAV file recording
- MP3
- Opus
- AAC
- local speech recognition
- local TTS
- acoustic echo cancellation (AEC)
- beamforming
- dual microphones
- wake word
- Bluetooth audio
- DAC
- external audio codec
- PSRAM dependency
- full duplex audio
- permanent local audio storage

The MVP should stream raw audio instead of creating files.

---

## 7. Amplifier Control

MAX98357A `SD` is connected to GPIO10.

Required behavior:

```text
Recording / idle before playback:
GPIO10 LOW
→ amplifier disabled

Playback:
GPIO10 HIGH
→ amplifier enabled
```

Recommended sequence when beginning playback:

```text
1. Configure I2S TX
2. Prepare initial audio buffer
3. Enable amplifier
4. Start writing PCM
```

When stopping playback:

```text
1. Stop feeding I2S
2. Disable amplifier
3. Clear playback buffers
```

Avoid audible pops where reasonably possible, but do not over-engineer the MVP.

---

## 8. Required State Machine

Implement an explicit state machine.

```cpp
enum class VoiceState {
    IDLE,
    RECORDING,
    WAITING_FOR_RESPONSE,
    PLAYING,
    ERROR_STATE
};
```

### IDLE

- amplifier off
- wait for button press
- Wi-Fi/server connection should remain alive if possible

### RECORDING

On button press:

```text
amp OFF
configure I2S RX
start microphone capture
send TURN_START
stream PCM chunks continuously
```

### WAITING_FOR_RESPONSE

On button release:

```text
stop microphone
flush final input audio
send TURN_END
wait for server audio
```

### PLAYING

When first response PCM arrives:

```text
configure I2S TX
enable MAX98357A
play chunks as soon as available
```

When playback ends:

```text
amp OFF
return to IDLE
```

### Barge-in / Interrupt

If button is pressed during playback:

```text
stop playback immediately
amp OFF
clear playback buffer
send CANCEL_RESPONSE if supported
switch I2S to RX
start new RECORDING turn
```

This behavior is important.

---

## 9. Networking

Use Wi-Fi.

Preferred transport for MVP:

```text
WebSocket over TLS (WSS)
```

Keep one persistent connection if possible.

Do not reconnect for every audio chunk.

Suggested application messages:

```text
TURN_START
AUDIO_CHUNK
TURN_END
CANCEL_RESPONSE
RESPONSE_AUDIO
RESPONSE_END
ERROR
```

Binary audio should remain binary.

Control messages may be JSON or another simple framing method.

Example conceptual flow:

```text
ESP32 → server: TURN_START
ESP32 → server: PCM chunk
ESP32 → server: PCM chunk
ESP32 → server: PCM chunk
ESP32 → server: TURN_END

server → ESP32: PCM response chunk
server → ESP32: PCM response chunk
server → ESP32: RESPONSE_END
```

The networking layer must be isolated from the audio driver so the backend provider can be replaced later.

---

## 10. Buffering

Do not record the entire utterance before uploading.

Use small streaming buffers.

Recommended starting point:

```text
Audio chunk duration: ~20–40 ms
```

At 16 kHz / mono / PCM16:

```text
20 ms ≈ 640 bytes
40 ms ≈ 1280 bytes
```

Use a small ring buffer / queue between:

```text
I2S capture → network transmit
network receive → I2S playback
```

Prioritize stable streaming over ultra-small latency.

Avoid dynamically allocating memory continuously inside the audio loop.

---

## 11. Software Architecture

Suggested project structure:

```text
src/
├── main.cpp
├── config.h
├── button.cpp
├── button.h
├── audio_input.cpp
├── audio_input.h
├── audio_output.cpp
├── audio_output.h
├── voice_state.cpp
├── voice_state.h
├── network_client.cpp
├── network_client.h
└── credentials.example.h
```

Responsibilities:

### `button.*`

- GPIO3
- INPUT_PULLUP
- debounce
- press/release events

### `audio_input.*`

- configure shared I2S peripheral for RX
- INMP441 capture
- convert input samples to PCM16 mono
- expose PCM chunks

### `audio_output.*`

- configure shared I2S peripheral for TX
- MAX98357A control
- PCM playback
- amplifier enable/disable

### `network_client.*`

- Wi-Fi connection
- persistent WebSocket/WSS
- transmit microphone PCM
- receive response PCM
- reconnect handling

### `voice_state.*`

- main state machine
- switching RX/TX
- playback interruption
- error recovery

### `config.h`

All hardware and audio constants.

---

## 12. Arduino Environment

Use:

```text
Framework: Arduino
Target: ESP32-C3
```

Prefer a current stable Arduino-ESP32 core.

If using PlatformIO:

```text
platform = espressif32
framework = arduino
```

If using Arduino IDE, select an ESP32-C3 compatible board profile.

Do not depend on ESP32-S3-only features.

Do not assume PSRAM exists.

---

## 13. Build Order

The agent should implement and validate the system in this order.

### Stage 1 — GPIO

Verify:

```text
button press/release
MAX98357A SD control
```

Serial output example:

```text
BUTTON DOWN
AMP OFF

BUTTON UP
```

### Stage 2 — Speaker

Generate a simple test tone or PCM buffer.

Verify:

```text
ESP32-C3
→ I2S TX
→ MAX98357A
→ speaker
```

Do not continue until speaker output works reliably.

### Stage 3 — Microphone

Configure I2S RX and capture INMP441.

Verify microphone samples change when speaking.

Print only occasional statistics such as:

```text
min
max
RMS
```

Do not spam raw samples over Serial.

### Stage 4 — Half-Duplex Switching

Verify repeatedly:

```text
RX → stop → TX → stop → RX
```

without rebooting or corrupting I2S state.

This is a critical milestone.

### Stage 5 — Local Record / Playback Test

For a short fixed interval:

```text
record microphone
→ small RAM buffer
→ switch to TX
→ play captured audio
```

This is only a hardware validation test.

Do not make full-utterance RAM recording part of the final architecture.

### Stage 6 — Wi-Fi

Connect to Wi-Fi and maintain connection.

### Stage 7 — Streaming Upload

Stream microphone PCM while the button is held.

Verify server receives continuous PCM.

### Stage 8 — Streaming Playback

Receive PCM from server and play it immediately.

### Stage 9 — Complete Push-to-Talk Flow

Final flow:

```text
press
→ capture + upload

release
→ END_OF_TURN

receive response
→ play

press again
→ interrupt playback
→ start new recording
```

---

## 14. Logging

Use concise serial logging.

Examples:

```text
[BOOT] ESP32-C3 AI Voice MVP
[WIFI] connected
[WS] connected
[STATE] IDLE -> RECORDING
[AUDIO] RX started
[STATE] RECORDING -> WAITING
[AUDIO] RX stopped
[STATE] WAITING -> PLAYING
[AUDIO] TX started
[STATE] PLAYING -> IDLE
```

Do not print audio samples continuously.

---

## 15. Error Handling

The firmware must survive normal failures without reboot loops.

Handle at minimum:

```text
Wi-Fi disconnect
WebSocket disconnect
server timeout
I2S start failure
I2S stop failure
empty server response
button press during playback
```

On recoverable error:

```text
disable amplifier
stop I2S
clear buffers
attempt network recovery
return to safe IDLE state
```

---

## 16. Power Assumptions for MVP

For development, power the ESP32-C3 SuperMini through USB-C.

Current wiring:

```text
USB 5V / VBUS
  │
  ├── ESP32-C3 board
  │     └── 3V3 → INMP441
  │
  └── board 5V pin → MAX98357A
```

On the common ESP32-C3 SuperMini design, the 5V header pin is tied to USB VBUS. This is suitable for MVP bench testing, but the MAX98357A can draw substantial current at high speaker power. Use a good 5V USB supply, preferably around 2A, and avoid assuming the board's 5V path is a high-current production power rail.

Battery support is explicitly outside the first firmware milestone.

---

## 17. Success Criteria

The MVP is complete when all of the following work reliably:

- button press starts microphone capture
- amplifier remains off while recording
- microphone audio is streamed before button release
- button release ends the turn
- server response begins playing without downloading the complete response first
- MAX98357A drives the 4Ω / 3W speaker
- playback can be interrupted by pressing the button
- switching between I2S RX and TX works repeatedly
- no SD card
- no WAV recording
- no Opus requirement
- no AEC
- no full-duplex audio

---

## 18. First Agent Task

Start by creating the Arduino project skeleton and implementing only:

```text
1. config.h with the exact GPIO mapping
2. button input + debounce
3. MAX98357A SD control
4. I2S TX speaker test
5. I2S RX microphone test
6. repeatable RX/TX mode switching
```

Do not connect to any AI API until the local audio hardware passes these tests.

Keep the implementation small, modular, and easy to replace later.
