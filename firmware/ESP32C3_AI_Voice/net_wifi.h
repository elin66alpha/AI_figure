#pragma once
#include <Arduino.h>
#include <IPAddress.h>

// WiFi 连接 + 指数退避重连(AGENT.md §5.1:1s -> 2s -> 4s -> ... -> 30s 封顶)。
//
// 全程非阻塞:netWifiBegin() 只发起连接,后面靠 loop 里的 netWifiUpdate() 推进。
// 不用 SDK 自带的自动重连(已显式关掉),否则两套重连逻辑会互相打架,
// 表现是退避时间对不上、日志里看到莫名其妙的状态跳变。

void      netWifiBegin();
void      netWifiUpdate();       // 每次 loop 都调一次
bool      netWifiIsUp();
void      netWifiForceRetry();   // 跳过退避立刻重试(ERROR 态按键触发,AGENT.md §8)
int32_t   netWifiRssi();
IPAddress netWifiIp();
uint32_t  netWifiDisconnectCount();   // 进遥测,盯 AGENT.md §7 说的"重连 N 次之后"
