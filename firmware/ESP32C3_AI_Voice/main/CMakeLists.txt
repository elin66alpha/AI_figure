idf_component_register(
    SRCS "../main.cpp" "../audio_io.cpp" "../pdm_filter.cpp" "../power.cpp"
         "../button.cpp" "../led.cpp" "../cue.cpp" "../bubble.cpp"
         "../net_wifi.cpp" "../net_prov.cpp" "../net_ws.cpp" "../transport.cpp"
         "../ring.cpp" "../proto.cpp" "../session.cpp"
    INCLUDE_DIRS ".."
    REQUIRES esp_driver_gpio esp_driver_i2s esp_adc esp_timer esp_wifi
             esp_event esp_netif nvs_flash esp-tls esp_hw_support
             espressif__network_provisioning)
