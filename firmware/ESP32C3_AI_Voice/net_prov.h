#pragma once
#include <stdint.h>
#include <stddef.h>

// BLE 配网模式 —— 给微信小程序(../../miniprogram/)用。
//
// 使用 ESP-IDF network_provisioning,Security 1 =
// X25519 + AES-256-CTR),WiFi 密码在 BLE 上是加密的。没有 PoP —— 靠"要按住按键才进配网"
// 这个物理动作兜底(ROADMAP §3.1)。
//
// 配网是**独立的开机模式**:这次开机只跑 BLE + 连 WiFi 验证,不碰 WS/TLS,
// 配成功就把凭据写进 NVS 然后重启进正常模式。BLE 和 TLS 从来不同时占堆。

// 进不进配网模式:上电时按住按键 PROV_HOLD_MS,或者 NVS 和 secrets.h 里都没有 WiFi 凭据。
// 按住期间阻塞(最多 PROV_HOLD_MS),只在启动时调。
bool provWanted();
void provStop(); // 深睡前释放 BLE 配网资源。

// 跑配网,不返回；成功保存后重启。
// 配网失败不重启:小程序会提示原因,让用户改密码重试(同一个 BLE 连接里)。
// 想放弃就直接断电,原来 NVS 里的凭据只有在新凭据连通之后才会被覆盖。
[[noreturn]] void provRun();
