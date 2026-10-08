#include "platform.h"
#include "net_prov.h"
#include "config.h"
#include "cue.h"
#include "led.h"
#include "net_wifi.h"
#include "power.h"
#include "driver/gpio.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "freertos/queue.h"
#include "network_provisioning/manager.h"
#include "network_provisioning/scheme_ble.h"
#include <atomic>
#include <cstdlib>

struct ProvEvent {
    int32_t id;
    wifi_sta_config_t credentials;
};
static QueueHandle_t s_events;
static bool s_active = false;
static std::atomic<bool> s_eventOverflow{false};

static void onProvEvent(void *, esp_event_base_t, int32_t id, void *data) {
    if (id != NETWORK_PROV_WIFI_CRED_RECV && id != NETWORK_PROV_WIFI_CRED_FAIL &&
        id != NETWORK_PROV_WIFI_CRED_SUCCESS && id != NETWORK_PROV_END) return;
    ProvEvent event = {};
    event.id = id;
    if (id == NETWORK_PROV_WIFI_CRED_RECV) event.credentials = *static_cast<wifi_sta_config_t *>(data);
    if (xQueueSend(s_events, &event, 0) != pdTRUE) s_eventOverflow.store(true);
}
bool provWanted() {
    const uint32_t start = appMillis();
    while (gpio_get_level(static_cast<gpio_num_t>(PIN_PTT_BUTTON)) == 0) {
        ledUpdate();
        if (appMillis() - start >= PROV_HOLD_MS) return true;
        appDelay(10);
    }
    return !netWifiHasCreds();
}
void provRun() {
    netWifiInit();
    s_events = xQueueCreate(8, sizeof(ProvEvent));
    if (!s_events) abort();
    ESP_ERROR_CHECK(esp_event_handler_register(NETWORK_PROV_EVENT, ESP_EVENT_ANY_ID, onProvEvent, nullptr));
    network_prov_mgr_config_t cfg = {};
    cfg.scheme = network_prov_scheme_ble;
    cfg.scheme_event_handler = NETWORK_PROV_EVENT_HANDLER_NONE;
    cfg.network_prov_wifi_conn_cfg.wifi_conn_attempts = 3;
    ESP_ERROR_CHECK(network_prov_mgr_init(cfg));
    s_active = true;
    // Retain Security 1 / no-PoP and the service UUID used by miniprogram/.
    static uint8_t uuid[16] = PROV_SERVICE_UUID;
    ESP_ERROR_CHECK(network_prov_scheme_ble_set_service_uuid(uuid));
    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_WIFI_STA));
    char name[16];
    snprintf(name, sizeof(name), PROV_NAME_PREFIX "%02X%02X%02X", mac[3], mac[4], mac[5]);
    ESP_ERROR_CHECK(network_prov_mgr_start_provisioning(NETWORK_PROV_SECURITY_1, nullptr, name, nullptr));
    printf("[PROV] BLE %s\n", name);
    ledSet(LedMode::DOUBLE);
    cueProv();

    char ssid[33] = {}, pass[65] = {};
    bool saved = false;
    for (;;) {
        ledUpdate();
        powerUpdate(false);
        if (s_eventOverflow.load()) {
            printf("[PROV] Event queue overflow; restarting without saving credentials\n");
            esp_restart();
        }
        ProvEvent event;
        if (xQueueReceive(s_events, &event, pdMS_TO_TICKS(10)) != pdTRUE) continue;
        powerNoteActivity();
        switch (event.id) {
            case NETWORK_PROV_WIFI_CRED_RECV:
                memcpy(ssid, event.credentials.ssid, 32); ssid[32] = 0;
                memcpy(pass, event.credentials.password, 64); pass[64] = 0;
                saved = false;
                break;
            case NETWORK_PROV_WIFI_CRED_FAIL:
                printf("[PROV] WiFi connection failed; waiting for new credentials\n");
                ESP_ERROR_CHECK(network_prov_mgr_reset_wifi_sm_state_on_failure());
                cueLinkDown();
                break;
            case NETWORK_PROV_WIFI_CRED_SUCCESS:
                saved = ssid[0] && netWifiSaveCreds(ssid, pass);
                if (saved) cueLinkUp(); else printf("[PROV] Credential save failed\n");
                break;
            case NETWORK_PROV_END:
                printf("[PROV] End, credentials saved=%d; restart\n", saved);
                ESP_ERROR_CHECK(network_prov_mgr_deinit());
                s_active = false;
                appDelay(100);
                esp_restart();
                break;
            default: break;
        }
    }
}
void provStop() {
    if (!s_active) return;
    s_active = false;
    ESP_ERROR_CHECK(network_prov_mgr_deinit());
}
