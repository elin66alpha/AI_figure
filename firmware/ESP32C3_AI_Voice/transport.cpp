#include "platform.h"
#include "transport.h"
#include "config.h"
#include "secrets.h"
#include "esp_tls.h"
#include "lwip/sockets.h"
#include "lwip/tcp.h"
#include <errno.h>

#ifndef SERVER_USE_TLS
#error "Set SERVER_USE_TLS explicitly in secrets.h"
#endif

static esp_tls_t *s_tls;
static bool s_connected;
#if SERVER_USE_TLS
static_assert(sizeof(PSK_IDENTITY) > 1, "PSK identity must not be empty");
static_assert(sizeof(PSK_KEY_HEX) == 65, "PSK must be 32 bytes / 64 hexadecimal digits");
static uint8_t s_key[32];
static psk_hint_key_t s_psk = {s_key, sizeof(s_key), PSK_IDENTITY};
static int hexDigit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
#endif

void transportClose() {
    s_connected = false;
    if (s_tls) esp_tls_conn_destroy(s_tls);
    s_tls = nullptr;
}
bool transportConnected() { return s_connected; }
int transportFd() {
    int fd = -1;
    if (s_tls) esp_tls_get_conn_sockfd(s_tls, &fd);
    return fd;
}
bool transportConnect() {
    transportClose();
    esp_tls_cfg_t cfg = {};
    cfg.non_block = true;
    cfg.timeout_ms = WS_TCP_CONNECT_TIMEOUT_MS;
#if SERVER_USE_TLS
    for (size_t i = 0; i < sizeof(s_key); ++i) {
        int a = hexDigit(PSK_KEY_HEX[i * 2]), b = hexDigit(PSK_KEY_HEX[i * 2 + 1]);
        if (a < 0 || b < 0) { printf("[TLS] Invalid PSK hex\n"); return false; }
        s_key[i] = static_cast<uint8_t>((a << 4) | b);
    }
    cfg.psk_hint_key = &s_psk;
#else
    cfg.is_plain_tcp = true;
#endif
    s_tls = esp_tls_init();
    if (!s_tls) return false;
    const uint32_t start = appMillis();
    const uint32_t budget = WS_TCP_CONNECT_TIMEOUT_MS + (SERVER_USE_TLS ? WS_TLS_HANDSHAKE_TIMEOUT_S * 1000 : 0);
    while (appMillis() - start < budget) {
        int result = esp_tls_conn_new_async(SERVER_HOST, strlen(SERVER_HOST), SERVER_PORT, &cfg, s_tls);
        if (result == 1) {
            int fd = transportFd(), yes = 1;
            if (fd < 0 || setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes)) < 0) break;
            s_connected = true;
            return true;
        }
        if (result < 0) break;
        appDelay(2);
    }
    printf("[TLS] Connection failed or timed out\n");
    transportClose();
    return false;
}
int transportRead(uint8_t *dst, size_t n) {
    if (!s_connected || n == 0) return -1;
    const int result = esp_tls_conn_read(s_tls, dst, n);
    if (result > 0) return result;
    if (result == ESP_TLS_ERR_SSL_WANT_READ || result == ESP_TLS_ERR_SSL_WANT_WRITE ||
        (result < 0 && !SERVER_USE_TLS && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)))
        return -1;
    s_connected = false;
    return -1;
}
size_t transportWrite(const uint8_t *src, size_t n, uint32_t timeoutMs) {
    if (!s_connected) return 0;
    const uint32_t start = appMillis();
    size_t sent = 0;
    while (sent < n && appMillis() - start < timeoutMs) {
        int result = esp_tls_conn_write(s_tls, src + sent, n - sent);
        if (result > 0) { sent += result; continue; }
        const bool wantRead = result == ESP_TLS_ERR_SSL_WANT_READ;
        if (!wantRead && result != ESP_TLS_ERR_SSL_WANT_WRITE &&
            !(!SERVER_USE_TLS && result < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR))) {
            s_connected = false;
            break;
        }
        const uint32_t elapsed = appMillis() - start;
        if (elapsed >= timeoutMs) break;
        int fd = transportFd();
        if (fd < 0) break;
        fd_set set;
        FD_ZERO(&set); FD_SET(fd, &set);
        const uint32_t remaining = timeoutMs - elapsed;
        timeval tv = {static_cast<long>(remaining / 1000), static_cast<long>((remaining % 1000) * 1000)};
        int ready = select(fd + 1, wantRead ? &set : nullptr, wantRead ? nullptr : &set, nullptr, &tv);
        if (ready <= 0) break;
    }
    return sent;
}
