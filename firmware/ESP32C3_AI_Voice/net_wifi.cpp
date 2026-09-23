#include "net_wifi.h"
#include "config.h"
#include "secrets.h"
#include <WiFi.h>

enum class WState : uint8_t { DOWN, CONNECTING, UP };

static WState   s_state    = WState::DOWN;
static uint32_t s_backoff  = WIFI_RETRY_MIN_MS;
static uint32_t s_retryAt  = 0;
static uint32_t s_attemptStart = 0;
static uint32_t s_disconnects = 0;

static void startAttempt() {
  Serial.printf("[WIFI] 连接 \"%s\" ...\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  s_attemptStart = millis();
  s_state = WState::CONNECTING;
}

static void scheduleRetry() {
  s_retryAt = millis() + s_backoff;
  Serial.printf("[WIFI] %lu ms 后重试\n", (unsigned long)s_backoff);
  s_backoff *= 2;
  if (s_backoff > WIFI_RETRY_MAX_MS) s_backoff = WIFI_RETRY_MAX_MS;
  s_state = WState::DOWN;
}

void netWifiBegin() {
  WiFi.persistent(false);          // 别把凭据反复写进 NVS,省 flash 寿命
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);    // 重连由本文件负责,见头文件说明
#if WIFI_SLEEP_OFF
  // modem sleep 会给收发引入几十 ms 抖动,音频流受不了。代价是功耗,USB 供电无所谓。
  WiFi.setSleep(false);
#endif
  s_backoff = WIFI_RETRY_MIN_MS;
  startAttempt();
}

void netWifiUpdate() {
  switch (s_state) {
    case WState::DOWN:
      if ((int32_t)(millis() - s_retryAt) >= 0) startAttempt();
      break;

    case WState::CONNECTING:
      if (WiFi.status() == WL_CONNECTED) {
        s_state   = WState::UP;
        s_backoff = WIFI_RETRY_MIN_MS;
        IPAddress ip = WiFi.localIP();
        Serial.printf("[WIFI] 已连接  IP=%u.%u.%u.%u  RSSI=%d dBm  信道=%d\n",
                      ip[0], ip[1], ip[2], ip[3], (int)WiFi.RSSI(), WiFi.channel());
        if (WiFi.RSSI() < -75)
          Serial.println("[WIFI] !! 信号很弱。SuperMini 克隆板天线普遍差 10~20 dB,"
                         "音频流对丢包敏感 —— 先把路由器放近再说(AGENT.md §7)");
      } else if (millis() - s_attemptStart > WIFI_CONNECT_TIMEOUT_MS) {
        Serial.printf("[WIFI] 连接超时 (status=%d)。查:SSID 是不是 2.4G、密码、"
                      "路由器是不是 WPA3-only\n", (int)WiFi.status());
        WiFi.disconnect(true);
        scheduleRetry();
      }
      break;

    case WState::UP:
      if (WiFi.status() != WL_CONNECTED) {
        s_disconnects++;
        Serial.printf("[WIFI] 掉线 (第 %lu 次)\n", (unsigned long)s_disconnects);
        WiFi.disconnect(true);
        s_backoff = WIFI_RETRY_MIN_MS;
        scheduleRetry();
      }
      break;
  }
}

bool netWifiIsUp() { return s_state == WState::UP; }

void netWifiForceRetry() {
  if (s_state == WState::UP) return;
  s_backoff = WIFI_RETRY_MIN_MS;
  s_retryAt = millis();
  if (s_state == WState::CONNECTING) s_attemptStart = 0;   // 让本次尝试立刻判超时
}

int32_t   netWifiRssi() { return s_state == WState::UP ? WiFi.RSSI() : 0; }
IPAddress netWifiIp()   { return WiFi.localIP(); }
uint32_t  netWifiDisconnectCount() { return s_disconnects; }
