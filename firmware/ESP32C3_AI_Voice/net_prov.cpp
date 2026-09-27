#include "net_prov.h"
#include "config.h"
#include "cue.h"
#include "led.h"
#include "net_wifi.h"
#include <WiFi.h>
#include <WiFiProv.h>
#include <esp_mac.h>

// 事件回调跑在 Arduino 的事件任务里,不是 loop 这个线程。
// 回调里只拷数据、置标志;写 NVS、放提示音、打日志、重启都回主循环做。
static char          s_ssid[33], s_pass[65];
static volatile bool s_ok, s_fail, s_end;
static volatile uint8_t s_failReason;

static void onProvEvent(arduino_event_t *e) {
  switch (e->event_id) {
    case ARDUINO_EVENT_PROV_CRED_RECV: {
      // wifi_sta_config_t 的 ssid[32] / password[64] 在满长时**没有结尾 0**,不能 strlcpy
      const wifi_sta_config_t &c = e->event_info.prov_cred_recv;
      memcpy(s_ssid, c.ssid, 32);     s_ssid[32] = 0;
      memcpy(s_pass, c.password, 64); s_pass[64] = 0;
      break;
    }
    case ARDUINO_EVENT_PROV_CRED_FAIL:
      s_failReason = (uint8_t)e->event_info.prov_fail_reason;
      s_fail = true;
      break;
    case ARDUINO_EVENT_PROV_CRED_SUCCESS: s_ok  = true; break;
    case ARDUINO_EVENT_PROV_END:          s_end = true; break;
    default: break;
  }
}

bool provWanted() {
  pinMode(PIN_PTT_BUTTON, INPUT_PULLUP);
  delay(5);
  const uint32_t t0 = millis();
  while (digitalRead(PIN_PTT_BUTTON) == LOW) {
    ledUpdate();
    if (millis() - t0 >= PROV_HOLD_MS) {
      Serial.println("[PROV] 上电时按住了按键 -> 配网模式");
      return true;
    }
    delay(10);
  }
  if (netWifiHasCreds()) return false;
  Serial.println("[PROV] 没有 WiFi 凭据 -> 配网模式");
  return true;
}

void provRun() {
  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  char name[16];
  snprintf(name, sizeof name, PROV_NAME_PREFIX "%02X%02X%02X", mac[3], mac[4], mac[5]);
  static uint8_t uuid[16] = PROV_SERVICE_UUID;

  WiFi.onEvent(onProvEvent);
  // 必须显式传 SECURITY_1:WiFiProv 的默认值是 Security 0(明文)。
  // HANDLER_NONE 而不是 FREE_BLE:反正配完就重启,没必要把 BLE 内存永久释放掉。
  // 最后一个 true = 清掉 WiFiProv 自己记的"已配网"标记,否则它会跳过配网直接去连。
  WiFiProv.beginProvision(NETWORK_PROV_SCHEME_BLE, NETWORK_PROV_SCHEME_HANDLER_NONE,
                          NETWORK_PROV_SECURITY_1, nullptr, name, nullptr, uuid, true);
  Serial.printf("[PROV] BLE 广播 \"%s\",打开微信小程序配网\n", name);
  ledSet(LedMode::DOUBLE);
  cueProv();

  for (;;) {
    ledUpdate();
    if (s_fail) {
      s_fail = false;
      Serial.printf("[PROV] 连 \"%s\" 失败:%s。等小程序重发\n", s_ssid,
                    s_failReason == NETWORK_PROV_WIFI_STA_AUTH_ERROR ? "密码错误" : "找不到这个 WiFi");
      cueLinkDown();
    }
    if (s_ok) {
      s_ok = false;
      netWifiSaveCreds(s_ssid, s_pass);
      Serial.printf("[PROV] 连上 \"%s\",凭据已存 NVS\n", s_ssid);
      cueLinkUp();
    }
    // 小程序读到"已连接"后 1 s,或连上后 30 s 没人读,WiFiProv 自己收尾 -> PROV_END。
    // 没成功也可能走到这里(极少见):NVS 没被改过,重启后照旧 —— 有旧凭据就连旧的,没有就再进配网。
    if (s_end) {
      Serial.println("[PROV] 配网结束,重启");
      delay(100);
      ESP.restart();
    }
    delay(10);
  }
}
