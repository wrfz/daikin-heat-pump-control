#include "daikin_bridge.h"

#include <cinttypes>
#include <cstring>

#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"
#include "esphome/core/version.h"

#ifdef USE_WIFI
#include "esphome/components/wifi/wifi_component.h"
#endif
#ifdef USE_ESP32
#include <esp_heap_caps.h>
#include <esp_system.h>
#endif

namespace esphome::daikin_bridge {

static const char *const TAG = "daikin_bridge";
static constexpr size_t CAN_MAX_DATA = 8;
static constexpr uint32_t CAN_MAX_ID = 0x7FF;
static constexpr uint32_t STATUS_POLL_INTERVAL = 100;
// ESPHome caps an action response at 5120 bytes of JSON; one frame takes at
// most about 40 bytes. More frames are reported with "more" and fetched by the
// next call.
static constexpr size_t MAX_FRAMES_PER_RESPONSE = 100;

static int hex_value(char ch) {
  if (ch >= '0' && ch <= '9')
    return ch - '0';
  if (ch >= 'a' && ch <= 'f')
    return ch - 'a' + 10;
  if (ch >= 'A' && ch <= 'F')
    return ch - 'A' + 10;
  return -1;
}

/// Parse an even number of hex digits; return false on any other character.
static bool parse_hex(const char *text, size_t length, uint8_t *out, size_t max, size_t *count) {
  if (length % 2 != 0 || length / 2 > max)
    return false;
  for (size_t i = 0; i < length; i += 2) {
    int high = hex_value(text[i]);
    int low = hex_value(text[i + 1]);
    if (high < 0 || low < 0)
      return false;
    out[i / 2] = static_cast<uint8_t>((high << 4) | low);
  }
  *count = length / 2;
  return true;
}

static void append_hex(std::string &out, const uint8_t *data, size_t length) {
  static const char *const DIGITS = "0123456789ABCDEF";
  for (size_t i = 0; i < length; i++) {
    out.push_back(DIGITS[data[i] >> 4]);
    out.push_back(DIGITS[data[i] & 0x0F]);
  }
}

#ifdef USE_ESP32
static const char *reset_reason_text() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:
      return "Power on";
    case ESP_RST_EXT:
      return "External pin";
    case ESP_RST_SW:
      return "Software";
    case ESP_RST_PANIC:
      return "Exception";
    case ESP_RST_INT_WDT:
      return "Interrupt watchdog";
    case ESP_RST_TASK_WDT:
      return "Task watchdog";
    case ESP_RST_WDT:
      return "Watchdog";
    case ESP_RST_DEEPSLEEP:
      return "Deep sleep";
    case ESP_RST_BROWNOUT:
      return "Brownout";
    case ESP_RST_SDIO:
      return "SDIO";
    default:
      return "Unknown";
  }
}
#endif

void DaikinBridge::setup() {
#ifdef USE_DAIKIN_BRIDGE_CAN
  this->canbus_->add_callback([this](uint32_t can_id, bool extended_id, bool rtr, const std::vector<uint8_t> &data) {
    if (!extended_id && !rtr)
      this->on_can_frame_(can_id, data);
  });
#endif
}

void DaikinBridge::loop() {
#ifdef USE_DAIKIN_BRIDGE_CAN
  this->can_send_if_quiet_();
  this->can_poll_status_();
#endif
#ifdef USE_DAIKIN_BRIDGE_UART
  this->uart_read_();
#endif
}

void DaikinBridge::dump_config() {
  ESP_LOGCONFIG(TAG, "Daikin bridge %s", DAIKIN_BRIDGE_VERSION);
#ifdef USE_DAIKIN_BRIDGE_CAN
  ESP_LOGCONFIG(TAG,
                "  CAN: buffer %u frames, send queue %u frames, quiet time %" PRIu32 " ms",
                static_cast<unsigned>(this->can_rx_.capacity()), static_cast<unsigned>(this->can_send_queue_size_),
                this->quiet_time_);
#endif
#ifdef USE_DAIKIN_BRIDGE_UART
  ESP_LOGCONFIG(TAG, "  UART: buffer %u bytes", static_cast<unsigned>(this->uart_rx_.capacity()));
#endif
}

void DaikinBridge::info(JsonObject root) {
  root["bridge"] = DAIKIN_BRIDGE_VERSION;
  root["esphome"] = ESPHOME_VERSION;
  JsonArray buses = root["buses"].to<JsonArray>();
#ifdef USE_DAIKIN_BRIDGE_CAN
  buses.add("can");
#endif
#ifdef USE_DAIKIN_BRIDGE_UART
  buses.add("uart");
#endif
  root["uptime"] = static_cast<uint32_t>(millis_64() / 1000);
#ifdef USE_ESP32
  root["heap_free"] = static_cast<uint32_t>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
  root["heap_max_block"] = static_cast<uint32_t>(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL));
  root["reset_reason"] = reset_reason_text();
#endif
#ifdef USE_WIFI
  if (wifi::global_wifi_component != nullptr && wifi::global_wifi_component->is_connected()) {
    JsonObject wifi_info = root["wifi"].to<JsonObject>();
    wifi_info["rssi"] = wifi::global_wifi_component->wifi_rssi();
    char ssid[wifi::SSID_BUFFER_SIZE];
    wifi_info["ssid"] = wifi::global_wifi_component->wifi_ssid_to(ssid);
    for (auto &ip : wifi::global_wifi_component->wifi_sta_ip_addresses()) {
      if (ip.is_set()) {
        char buf[network::IP_ADDRESS_BUFFER_SIZE];
        wifi_info["ip"] = ip.str_to(buf);
        break;
      }
    }
  }
#endif
#ifdef USE_DAIKIN_BRIDGE_CAN
  JsonObject can = root["can"].to<JsonObject>();
  can["buffer"] = this->can_rx_.capacity();
  can["overflows"] = this->can_rx_.overflows();
  can["state"] = this->can_state_();
  can["tx_errors"] = this->can_status_.tx_error_counter;
  can["rx_errors"] = this->can_status_.rx_error_counter;
  if (this->can_status_.arb_lost_count != canbus::CAN_STATUS_UNSET)
    can["arbitration_lost"] = this->can_status_.arb_lost_count;
  can["bus_off"] = this->can_bus_off_count_;
  can["send_errors"] = this->can_send_errors_;
#endif
#ifdef USE_DAIKIN_BRIDGE_UART
  JsonObject uart_info = root["uart"].to<JsonObject>();
  uart_info["buffer"] = this->uart_rx_.capacity();
  uart_info["overflows"] = this->uart_rx_.overflows();
#endif
}

#ifdef USE_DAIKIN_BRIDGE_CAN
void DaikinBridge::on_can_frame_(uint32_t can_id, const std::vector<uint8_t> &data) {
  TimedFrame frame{};
  frame.time = millis();
  frame.can_id = can_id;
  frame.length = static_cast<uint8_t>(std::min(data.size(), CAN_MAX_DATA));
  std::memcpy(frame.data, data.data(), frame.length);
  this->can_rx_.push(frame);
  this->last_bus_activity_ = frame.time;
}

void DaikinBridge::queue_can_frame_(const std::string &text) {
  size_t sep = text.find('#');
  TimedFrame frame{};
  size_t count = 0;
  bool valid = sep != std::string::npos && sep > 0 && sep <= 3;
  uint32_t can_id = 0;
  for (size_t i = 0; valid && i < sep; i++) {
    int value = hex_value(text[i]);
    valid = value >= 0;
    can_id = (can_id << 4) | static_cast<uint32_t>(value);
  }
  valid = valid && can_id <= CAN_MAX_ID &&
          parse_hex(text.c_str() + sep + 1, text.size() - sep - 1, frame.data, CAN_MAX_DATA, &count);
  if (!valid) {
    ESP_LOGW(TAG, "Invalid CAN frame '%s'", text.c_str());
    this->can_dropped_++;
    return;
  }
  if (this->can_queue_.size() >= this->can_send_queue_size_) {
    this->can_dropped_++;
    return;
  }
  frame.can_id = can_id;
  frame.length = static_cast<uint8_t>(count);
  this->can_queue_.push_back(frame);
}

void DaikinBridge::can_send_if_quiet_() {
  if (this->can_queue_.empty())
    return;
  uint32_t now = millis();
  if (now - this->last_bus_activity_ < this->quiet_time_)
    return;
  TimedFrame frame = this->can_queue_.front();
  this->can_queue_.pop_front();
  if (this->canbus_->send_data(frame.can_id, false, false, frame.data, frame.length) != canbus::ERROR_OK) {
    this->can_send_errors_++;
    return;
  }
  frame.time = now;
  this->can_sent_.push_back(frame);
  this->last_bus_activity_ = now;
}

void DaikinBridge::can_report_(JsonObject root) {
  root["now"] = millis();
  auto add = [](JsonArray list, const TimedFrame &frame) {
    JsonArray item = list.add<JsonArray>();
    item.add(frame.time);
    item.add(frame.can_id);
    std::string data;
    append_hex(data, frame.data, frame.length);
    item.add(data);
  };
  JsonArray rx = root["rx"].to<JsonArray>();
  this->can_rx_.drain([&](const TimedFrame &frame) { add(rx, frame); }, MAX_FRAMES_PER_RESPONSE);
  JsonArray tx = root["tx"].to<JsonArray>();
  for (const auto &frame : this->can_sent_)
    add(tx, frame);
  this->can_sent_.clear();
  root["more"] = this->can_rx_.size() > 0;
  root["pending"] = this->can_queue_.size();
  root["overflows"] = this->can_rx_.overflows();
  root["dropped"] = this->can_dropped_;
}

void DaikinBridge::can_poll_status_() {
  uint32_t now = millis();
  if (now - this->last_status_poll_ < STATUS_POLL_INTERVAL)
    return;
  this->last_status_poll_ = now;
  this->can_status_ = this->canbus_->get_status();
  if (this->can_status_.bus_off && !this->can_bus_off_)
    this->can_bus_off_count_++;
  this->can_bus_off_ = this->can_status_.bus_off;
}

const char *DaikinBridge::can_state_() const {
  if (this->can_status_.bus_off)
    return "bus_off";
  if (this->can_status_.tx_error_counter >= canbus::CAN_ERROR_PASSIVE_THRESHOLD ||
      this->can_status_.rx_error_counter >= canbus::CAN_ERROR_PASSIVE_THRESHOLD)
    return "error_passive";
  return "error_active";
}
#endif

#ifdef USE_DAIKIN_BRIDGE_UART
void DaikinBridge::uart_read_() {
  uint8_t byte;
  while (this->uart_->available() > 0 && this->uart_->read_byte(&byte)) {
    if (!this->uart_rx_time_set_) {
      this->uart_rx_time_ = millis();
      this->uart_rx_time_set_ = true;
    }
    this->uart_rx_.push(byte);
  }
}

void DaikinBridge::uart_exchange(const std::string &data, JsonObject root) {
  this->uart_read_();
  uint8_t buffer[64];
  size_t count = 0;
  bool sent = false;
  if (!data.empty()) {
    if (parse_hex(data.c_str(), data.size(), buffer, sizeof(buffer), &count)) {
      this->uart_->write_array(buffer, count);
      sent = true;
    } else {
      ESP_LOGW(TAG, "Invalid UART data '%s'", data.c_str());
    }
  }
  uint32_t now = millis();
  root["now"] = now;
  std::string rx;
  this->uart_rx_.drain([&](const uint8_t &value) { append_hex(rx, &value, 1); });
  root["rx"] = rx;
  if (this->uart_rx_time_set_ && !rx.empty())
    root["rx_t"] = this->uart_rx_time_;
  this->uart_rx_time_set_ = false;
  if (sent)
    root["tx_t"] = now;
  root["overflows"] = this->uart_rx_.overflows();
}
#endif

}  // namespace esphome::daikin_bridge
