#pragma once
// Custom board + user-confirmed power revisions, ESP-IDF 6.1.0.
// GPIO numbers belong here. secrets.h retains WiFi / server / PSK configuration.
#define FW_VERSION "0.5.0-idf61"

// NS4168 I2S output; microphone uses separate PDM clock/data.
#define PIN_I2S_BCLK    4
#define PIN_I2S_WS      5
#define PIN_MIC_CLK     6
#define PIN_MIC_DATA    0
#define PIN_AMP_DATA    7
#define PIN_AMP_SD      10    // NS4168: LOW shutdown, HIGH right channel
#define PIN_PTT_BUTTON  3     // External 100 kOhm pull-up, press to GND
#define PIN_STATUS_LED  8
#define LED_ON_LEVEL    0
#define PIN_BAT_ADC     1     // VBAT -> 1 MOhm -> ADC -> 1 MOhm -> GND; 100 nF
#define PIN_VBUS_DET    20    // VBUS_CHG -> 68 kOhm -> input -> 100 kOhm -> GND

#define SAMPLE_RATE_HZ       16000
#define FRAME_SAMPLES        320
#define NET_CHUNK_SAMPLES    1600
#define NET_CHUNK_BYTES      (NET_CHUNK_SAMPLES * 2)
#define OUTPUT_GAIN_DEFAULT  100  // Retained conservative volume; verify on NS4168 board.
#define DMA_DESC_NUM         4
#define DMA_FRAME_NUM        240
#define DMA_TOTAL_MS         ((DMA_DESC_NUM * DMA_FRAME_NUM * 1000) / SAMPLE_RATE_HZ)
#define AMP_WAKE_MS          10
#define AMP_TAIL_MS          4

// Raw PDM bit clock 2.048 MHz; CIC /64 -> 32 kHz, FIR /2 -> PCM 16 kHz.
// IDF 6.1.0 raw RX driver generates CLK = sample_rate_hz * 2.
#define MIC_PDM_CLK_HZ       2048000
#define MIC_PDM_DRIVER_RATE  (MIC_PDM_CLK_HZ / 2)
#define MIC_CIC_DECIMATION   64
#define MIC_PDM_WORDS_PER_PCM (MIC_CIC_DECIMATION * 2 / 16)
#define MIC_RAW_DMA_WORDS    1024
#define MIC_RAW_DMA_DESC_NUM 8    // 64 ms at 2.048 MHz, 16 KB DMA
#define MIC_GAIN_Q8          256  // Unity; old INMP441 MIC_SHIFT calibration does not apply.
#define DC_BLOCKER_ON        true

#define BUTTON_DEBOUNCE_MS   25
#define BAT_LOW_MV           3600
#define BAT_RESUME_MV        3800
#define BAT_LOW_CONFIRM_MS   3000
#define BAT_SAMPLE_MS        1000
#define VBUS_DEBOUNCE_MS     50
#define IDLE_SLEEP_MS        (20u * 60u * 1000u)

#define RING_BYTES           16384
#define PREBUFFER_BYTES      9600
#define WIFI_RETRY_MIN_MS    1000
#define WIFI_RETRY_MAX_MS    30000
#define WIFI_CONNECT_TIMEOUT_MS 12000
#define WIFI_SLEEP_OFF       true // Retain low-latency audio; deep sleep handles standby.

#define PROV_SERVICE_UUID { 0x3f, 0xdb, 0x78, 0xcc, 0xd3, 0x9c, 0x94, 0x85, \
                            0xa8, 0x4c, 0xaa, 0xf2, 0x9a, 0x4c, 0x62, 0x10 }
#define PROV_NAME_PREFIX    "AIFIG_"
#define PROV_HOLD_MS        3000

#define WS_TCP_CONNECT_TIMEOUT_MS 2500
#define WS_TLS_HANDSHAKE_TIMEOUT_S 8
#define WS_HANDSHAKE_TIMEOUT_MS 6000
#define WS_PING_INTERVAL_MS 30000
#define WS_PONG_TIMEOUT_MS  70000
#define WS_RETRY_MIN_MS     1000
#define WS_RETRY_MAX_MS     30000
#define WS_TEXT_MAX         256
#define WS_SEND_TIMEOUT_MS  300
#define WS_AUDIO_SEND_TIMEOUT_MS 30
#define WS_UPLINK_DROP_LIMIT 10
#define WAITING_TIMEOUT_MS  8000
#define TELEMETRY_INTERVAL_MS 10000
#define HEAP_MIN_MAXALLOC   24576
