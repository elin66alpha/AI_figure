#include "platform.h"
#include "net_wifi.h"
#include "config.h"
#include "secrets.h"
#include <atomic>
#include <cstdlib>
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs.h"

#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASS
#define WIFI_PASS ""
#endif
enum class WState : uint8_t { DOWN, CONNECTING, UP };
static WState s_state = WState::DOWN;
static std::atomic<bool> s_hasIp{false};
static bool s_initialized, s_started;
static esp_netif_t *s_netif;
static uint32_t s_backoff = WIFI_RETRY_MIN_MS, s_retryAt, s_attemptStart, s_disconnects;
static char s_ssid[33], s_pass[65];

static void onNetworkEvent(void *, esp_event_base_t base, int32_t id, void *) {
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) s_hasIp.store(true);
    if (base == WIFI_EVENT && (id == WIFI_EVENT_STA_DISCONNECTED || id == WIFI_EVENT_STA_STOP))
        s_hasIp.store(false);
}
void netWifiInit() {
    if (s_initialized) return;
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    s_netif = esp_netif_create_default_wifi_sta();
    if (!s_netif) abort();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, onNetworkEvent, nullptr));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, onNetworkEvent, nullptr));
    s_initialized = true;
}
static const char *loadCreds() {
    s_ssid[0] = s_pass[0] = 0;
    nvs_handle_t handle;
    esp_err_t err = nvs_open("net", NVS_READONLY, &handle);
    if (err == ESP_OK) {
        size_t n = sizeof(s_ssid);
        esp_err_t ssidErr = nvs_get_str(handle, "ssid", s_ssid, &n);
        n = sizeof(s_pass);
        esp_err_t passErr = nvs_get_str(handle, "pass", s_pass, &n);
        nvs_close(handle);
        if (ssidErr == ESP_OK && (passErr == ESP_OK || passErr == ESP_ERR_NVS_NOT_FOUND) && s_ssid[0])
            return "NVS";
        s_ssid[0] = s_pass[0] = 0;
    } else if (err != ESP_ERR_NVS_NOT_FOUND) {
        printf("[WIFI] NVS read: %s\n", esp_err_to_name(err));
    }
    strlcpy(s_ssid, WIFI_SSID, sizeof(s_ssid));
    strlcpy(s_pass, WIFI_PASS, sizeof(s_pass));
    return "secrets.h";
}
bool netWifiHasCreds() { loadCreds(); return s_ssid[0] != 0; }
bool netWifiSaveCreds(const char *ssid, const char *pass) {
    nvs_handle_t handle;
    esp_err_t err = nvs_open("net", NVS_READWRITE, &handle);
    if (err != ESP_OK) return false;
    err = nvs_set_str(handle, "ssid", ssid);
    if (err == ESP_OK) err = nvs_set_str(handle, "pass", pass);
    if (err == ESP_OK) err = nvs_commit(handle);
    nvs_close(handle);
    if (err != ESP_OK) printf("[WIFI] NVS write: %s\n", esp_err_to_name(err));
    return err == ESP_OK;
}
static void scheduleRetry() {
    s_retryAt = appMillis() + s_backoff;
    s_backoff = s_backoff < WIFI_RETRY_MAX_MS / 2 ? s_backoff * 2 : WIFI_RETRY_MAX_MS;
    s_state = WState::DOWN;
}
static void startAttempt() {
    s_hasIp.store(false);
    s_attemptStart = appMillis();
    s_state = WState::CONNECTING;
    esp_err_t err = esp_wifi_connect();
    if (err != ESP_OK) {
        printf("[WIFI] connect: %s\n", esp_err_to_name(err));
        scheduleRetry();
    }
}
void netWifiBegin() {
    netWifiInit();
    printf("[WIFI] Credentials: %s\n", loadCreds());
    wifi_config_t cfg = {};
    memcpy(cfg.sta.ssid, s_ssid, strnlen(s_ssid, sizeof(cfg.sta.ssid)));
    memcpy(cfg.sta.password, s_pass, strnlen(s_pass, sizeof(cfg.sta.password)));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &cfg));
    ESP_ERROR_CHECK(esp_wifi_start());
    s_started = true;
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_SLEEP_OFF ? WIFI_PS_NONE : WIFI_PS_MIN_MODEM));
    s_backoff = WIFI_RETRY_MIN_MS;
    startAttempt();
}
void netWifiUpdate() {
    switch (s_state) {
        case WState::DOWN:
            if (static_cast<int32_t>(appMillis() - s_retryAt) >= 0) startAttempt();
            break;
        case WState::CONNECTING:
            if (s_hasIp.load()) {
                s_state = WState::UP;
                s_backoff = WIFI_RETRY_MIN_MS;
                const esp_ip4_addr_t ip = netWifiIp();
                printf("[WIFI] Connected " IPSTR " RSSI=%ld\n", IP2STR(&ip), (long)netWifiRssi());
            } else if (appMillis() - s_attemptStart >= WIFI_CONNECT_TIMEOUT_MS) {
                esp_wifi_disconnect();
                scheduleRetry();
            }
            break;
        case WState::UP:
            if (!s_hasIp.load()) {
                ++s_disconnects;
                s_backoff = WIFI_RETRY_MIN_MS;
                scheduleRetry();
            }
            break;
    }
}
bool netWifiIsUp() { return s_state == WState::UP && s_hasIp.load(); }
void netWifiForceRetry() {
    if (netWifiIsUp()) return;
    esp_wifi_disconnect();
    s_state = WState::DOWN;
    s_backoff = WIFI_RETRY_MIN_MS;
    s_retryAt = appMillis();
}
int32_t netWifiRssi() {
    wifi_ap_record_t ap;
    return netWifiIsUp() && esp_wifi_sta_get_ap_info(&ap) == ESP_OK ? ap.rssi : 0;
}
esp_ip4_addr_t netWifiIp() {
    esp_netif_ip_info_t info = {};
    if (s_netif) esp_netif_get_ip_info(s_netif, &info);
    return info.ip;
}
uint32_t netWifiDisconnectCount() { return s_disconnects; }
void netWifiStop() {
    if (!s_initialized) return;
    esp_wifi_disconnect();
    esp_wifi_stop();
    s_started = false;
    s_hasIp.store(false);
    s_state = WState::DOWN;
}
