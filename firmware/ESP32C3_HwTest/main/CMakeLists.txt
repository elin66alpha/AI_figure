# Production drivers are compiled from ../ESP32C3_AI_Voice unchanged, so the self-test
# exercises the same code the product ships. secrets.h is never included.
set(APP_DIR "${CMAKE_CURRENT_LIST_DIR}/../../ESP32C3_AI_Voice")
idf_component_register(
    SRCS "../hwtest_main.cpp"
         "${APP_DIR}/audio_io.cpp" "${APP_DIR}/pdm_filter.cpp" "${APP_DIR}/cue.cpp"
         "${APP_DIR}/led.cpp" "${APP_DIR}/button.cpp"
    INCLUDE_DIRS ".." "${APP_DIR}"
    REQUIRES esp_driver_gpio esp_driver_i2s esp_driver_usb_serial_jtag esp_adc
             esp_timer esp_hw_support)
