#include "platform.h"
#include "config.h"
#include "secrets.h"
#include "audio_io.h"
#include "cue.h"
#include "led.h"
#include "net_prov.h"
#include "net_wifi.h"
#include "net_ws.h"
#include "power.h"
#include "ring.h"
#include "session.h"
#include "esp_heap_caps.h"
#include "esp_system.h"
#include "nvs_flash.h"
#include "driver/gpio.h"
#include "lwip/ip4_addr.h"

static void telemetry() {
  static uint32_t last = 0;
  const VoiceState state = sessionState();
  if (appMillis() - last < TELEMETRY_INTERVAL_MS ||
      state == VoiceState::RECORDING || state == VoiceState::PLAYING || audioIsPlaying()) return;
  last = appMillis();
  multi_heap_info_t heap;
  heap_caps_get_info(&heap, MALLOC_CAP_DEFAULT);
  esp_ip4_addr_t ip = netWifiIp();
  printf("[TLM] %s ip=" IPSTR " rssi=%ld VBAT=%d USB=%d free=%u max=%u "
         "wifiDrop=%lu upDrop=%lu rx=%lu under=%lu\n",
         sessionStateName(), IP2STR(&ip), (long)netWifiRssi(), powerBatteryMv(), powerUsbPresent(),
         (unsigned)heap.total_free_bytes, (unsigned)heap.largest_free_block,
         (unsigned long)netWifiDisconnectCount(), (unsigned long)sessionUplinkDrops(),
         (unsigned long)wsRxAudioBytes(), (unsigned long)sessionUnderruns());
  if (heap.largest_free_block < HEAP_MIN_MAXALLOC) {
    printf("[TLM] Low contiguous heap; restart\n");
    cueError();
    esp_restart();
  }
}
extern "C" void app_main() {
  printf("\n[BOOT] AI Figure %s ESP-IDF %s\n", FW_VERSION, esp_get_idf_version());
  powerBegin(); // Battery and wake policy are checked before radios/audio.
  ledBegin();
  ledSet(LedMode::BLINK_FAST);
  // Preserve existing credentials: do not automatically erase NVS on init failure.
  ESP_ERROR_CHECK(nvs_flash_init());
  if (!audioBegin()) {
    printf("[BOOT] Audio init failed\n");
    ledSet(LedMode::BLINK_SLOW);
    for (;;) { ledUpdate(); powerUpdate(false); appDelay(10); }
  }
  cueBegin();
  cueBoot();
  if (provWanted()) provRun();
  netWifiBegin();
  sessionBegin();
  for (;;) {
    ledUpdate();
    // Also count button presses during connection/retry as user activity.
    if (gpio_get_level(static_cast<gpio_num_t>(PIN_PTT_BUTTON)) == 0) powerNoteActivity();
    const VoiceState before = sessionState();
    powerUpdate(before == VoiceState::RECORDING || before == VoiceState::WAITING ||
                before == VoiceState::PLAYING);
    netWifiUpdate();
    sessionUpdate();
    telemetry();
    const VoiceState state = sessionState();
    if (state != VoiceState::RECORDING && state != VoiceState::PLAYING) appDelay(2);
  }
}
