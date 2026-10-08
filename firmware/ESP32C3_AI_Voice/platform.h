#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// Application timing, backed by IDF. No Arduino runtime or compatibility layer.
inline uint32_t appMillis() {
    return static_cast<uint32_t>(esp_timer_get_time() / 1000);
}
inline void appDelay(uint32_t ms) {
    if (ms == 0) { taskYIELD(); return; }
    vTaskDelay(pdMS_TO_TICKS(ms) ? pdMS_TO_TICKS(ms) : 1);
}
