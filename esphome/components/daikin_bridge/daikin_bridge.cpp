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
// UART bytes and pieces per response, within the same limit.
static constexpr size_t MAX_UART_BYTES_PER_RESPONSE = 1024;
static constexpr size_t MAX_UART_PIECES_PER_RESPONSE = 32;
static constexpr size_t MAX_UART_PIECES = 64;
// A client that does not call for this long is gone.
static constexpr uint32_t CLIENT_TIMEOUT = 3000;
static constexpr size_t CLIENT_ID_MAX = 32;

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

static std::string arg_string(const api::ExecuteServiceArgument &arg) {
  return std::string(arg.string_.c_str(), arg.string_.size());
}

BridgeAction::BridgeAction(DaikinBridge *bridge, const char *name, std::vector<Arg> args, Handler handler)
    : bridge_(bridge), name_(name), args_(std::move(args)), handler_(handler), key_(fnv1_hash(name)) {}

api::ListEntitiesServicesResponse BridgeAction::encode_list_service_response() {
  api::ListEntitiesServicesResponse msg;
  msg.name = ProgmemStringRef(StringRef(this->name_));
  msg.key = this->key_;
  msg.supports_response = api::enums::SUPPORTS_RESPONSE_ONLY;
  msg.args.init(this->args_.size());
  for (const auto &arg : this->args_) {
    auto &item = msg.args.emplace_back();
    item.name = ProgmemStringRef(StringRef(arg.name));
    item.type = arg.type;
  }
  return msg;
}

bool BridgeAction::execute_service(const api::ExecuteServiceRequest &req) {
  // Every action of the bridge answers; without a response there is nothing to do.
  return req.key == this->key_;
}

bool BridgeAction::execute_service(const api::ExecuteServiceRequest &req, uint32_t action_call_id) {
  if (req.key != this->key_)
    return false;
  auto *server = api::global_api_server;
  if (action_call_id == 0)
    return true;
  if (req.args.size() != this->args_.size()) {
    server->send_action_response(action_call_id, false, StringRef("invalid arguments"));
  } else {
    json::JsonBuilder builder;
    this->handler_(this->bridge_, req, builder.root());
    auto buffer = builder.serialize();
    server->send_action_response(action_call_id, true, StringRef(), reinterpret_cast<const uint8_t *>(buffer.data()),
                                 buffer.size());
  }
  server->unregister_active_action_call(action_call_id);
  return true;
}

void DaikinBridge::register_actions() {
  auto *server = api::global_api_server;
  using api::enums::SERVICE_ARG_TYPE_STRING;
  using api::enums::SERVICE_ARG_TYPE_STRING_ARRAY;
  server->register_user_service(new BridgeAction(  // NOLINT
      this, "daikin_bridge_info", {},
      [](DaikinBridge *bridge, const api::ExecuteServiceRequest &, JsonObject root) { bridge->info(root); }));
  server->register_user_service(new BridgeAction(  // NOLINT
      this, "daikin_bridge_claim", {{"client", SERVICE_ARG_TYPE_STRING}},
      [](DaikinBridge *bridge, const api::ExecuteServiceRequest &req, JsonObject root) {
        bridge->claim(arg_string(req.args[0]), root);
      }));
#ifdef USE_DAIKIN_BRIDGE_CAN
  server->register_user_service(new BridgeAction(  // NOLINT
      this, "daikin_can_exchange", {{"client", SERVICE_ARG_TYPE_STRING}, {"frames", SERVICE_ARG_TYPE_STRING_ARRAY}},
      [](DaikinBridge *bridge, const api::ExecuteServiceRequest &req, JsonObject root) {
        bridge->can_exchange(arg_string(req.args[0]), req.args[1].string_array, root);
      }));
#endif
#ifdef USE_DAIKIN_BRIDGE_UART
  server->register_user_service(new BridgeAction(  // NOLINT
      this, "daikin_uart_exchange", {{"client", SERVICE_ARG_TYPE_STRING}, {"data", SERVICE_ARG_TYPE_STRING}},
      [](DaikinBridge *bridge, const api::ExecuteServiceRequest &req, JsonObject root) {
        bridge->uart_exchange(arg_string(req.args[0]), arg_string(req.args[1]), root);
      }));
#endif
}

void DaikinBridge::setup() {
#ifdef USE_DAIKIN_BRIDGE_CAN
  this->canbus_->add_callback([this](uint32_t can_id, bool extended_id, bool rtr, const std::vector<uint8_t> &data) {
    if (!extended_id && !rtr)
      this->on_can_frame_(can_id, data);
  });
#endif
}

void DaikinBridge::loop() {
  this->expire_clients_();
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
  root["clients"] = this->client_count_();
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
#endif
}


Client *DaikinBridge::client_(const std::string &id, JsonObject root) {
  if (id.empty() || id.size() > CLIENT_ID_MAX) {
    root["error"] = "invalid_client";
    return nullptr;
  }
  this->expire_clients_();
  uint32_t now = millis();
  for (auto &client : this->clients_) {
    if (client.active && client.id == id) {
      client.last_seen = now;
      return &client;
    }
  }
  for (size_t i = 0; i < this->clients_.size(); i++) {
    Client &client = this->clients_[i];
    if (client.active)
      continue;
    client = Client{};
    client.active = true;
    client.id = id;
    client.last_seen = now;
    client.order = this->next_order_++;
#ifdef USE_DAIKIN_BRIDGE_CAN
    client.can_cursor = this->can_rx_.end();
#endif
#ifdef USE_DAIKIN_BRIDGE_UART
    client.uart_cursor = this->uart_rx_.end();
#endif
    ESP_LOGD(TAG, "Client %s registered", id.c_str());
    if (this->master_ < 0)
      this->set_master_(static_cast<int>(i));
    return &client;
  }
  ESP_LOGW(TAG, "Client %s rejected: %u clients already", id.c_str(), static_cast<unsigned>(MAX_CLIENTS));
  root["error"] = "too_many_clients";
  return nullptr;
}

bool DaikinBridge::is_master_(const Client *client) const {
  return this->master_ >= 0 && &this->clients_[this->master_] == client;
}

void DaikinBridge::set_master_(int index) {
  if (index == this->master_)
    return;
  this->master_ = index;
#ifdef USE_DAIKIN_BRIDGE_CAN
  // Frames of the previous master are not sent anymore.
  this->can_queue_.clear();
  this->can_sent_.clear();
#endif
#ifdef USE_DAIKIN_BRIDGE_UART
  this->uart_sent_ = true;
#endif
  if (index >= 0)
    ESP_LOGI(TAG, "Client %s is the master", this->clients_[index].id.c_str());
}

void DaikinBridge::expire_clients_() {
  uint32_t now = millis();
  bool master_gone = false;
  for (size_t i = 0; i < this->clients_.size(); i++) {
    Client &client = this->clients_[i];
    if (!client.active || now - client.last_seen <= CLIENT_TIMEOUT)
      continue;
    ESP_LOGD(TAG, "Client %s is gone", client.id.c_str());
    client.active = false;
    if (static_cast<int>(i) == this->master_)
      master_gone = true;
  }
  if (!master_gone)
    return;
  this->set_master_(-1);
  int next = -1;
  for (size_t i = 0; i < this->clients_.size(); i++) {
    const Client &client = this->clients_[i];
    if (client.active && (next < 0 || client.order < this->clients_[next].order))
      next = static_cast<int>(i);
  }
  this->set_master_(next);
}

size_t DaikinBridge::client_count_() const {
  return std::count_if(this->clients_.begin(), this->clients_.end(),
                       [](const Client &client) { return client.active; });
}

void DaikinBridge::report_client_(const Client *client, bool master, JsonObject root) const {
  root["master"] = master;
  root["clients"] = this->client_count_();
  root["rejected"] = client->rejected;
}

void DaikinBridge::claim(const std::string &client, JsonObject root) {
  Client *caller = this->client_(client, root);
  if (caller == nullptr)
    return;
  this->set_master_(static_cast<int>(caller - this->clients_.data()));
  this->report_client_(caller, true, root);
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

void DaikinBridge::can_report_(Client *client, bool master, JsonObject root) {
  root["now"] = millis();
  this->report_client_(client, master, root);
  auto add = [](JsonArray list, const TimedFrame &frame) {
    JsonArray item = list.add<JsonArray>();
    item.add(frame.time);
    item.add(frame.can_id);
    std::string data;
    append_hex(data, frame.data, frame.length);
    item.add(data);
  };
  client->can_overflows += this->can_rx_.catch_up(client->can_cursor);
  JsonArray rx = root["rx"].to<JsonArray>();
  uint64_t end = this->can_rx_.end();
  for (size_t count = 0; client->can_cursor < end && count < MAX_FRAMES_PER_RESPONSE; count++)
    add(rx, this->can_rx_.at(client->can_cursor++));
  JsonArray tx = root["tx"].to<JsonArray>();
  if (master) {
    for (const auto &frame : this->can_sent_)
      add(tx, frame);
    this->can_sent_.clear();
  }
  root["more"] = client->can_cursor < end;
  root["pending"] = master ? this->can_queue_.size() : 0;
  root["overflows"] = client->can_overflows;
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
    if (this->uart_pieces_.empty() || this->uart_sent_) {
      this->uart_pieces_.push_back(UartPiece{this->uart_rx_.end(), millis(), this->uart_sent_});
      this->uart_sent_ = false;
    }
    this->uart_rx_.push(byte);
  }
  // Keep the piece the oldest buffered byte belongs to, and a bounded number.
  while (this->uart_pieces_.size() > 1 &&
         (this->uart_pieces_[1].start <= this->uart_rx_.begin() || this->uart_pieces_.size() > MAX_UART_PIECES))
    this->uart_pieces_.pop_front();
}

void DaikinBridge::uart_exchange(const std::string &client, const std::string &data, JsonObject root) {
  this->uart_read_();
  Client *caller = this->client_(client, root);
  if (caller == nullptr)
    return;
  bool master = this->is_master_(caller);
  bool sent = false;
  if (!data.empty() && !master) {
    caller->rejected++;
  } else if (!data.empty()) {
    uint8_t buffer[64];
    size_t count = 0;
    if (parse_hex(data.c_str(), data.size(), buffer, sizeof(buffer), &count)) {
      this->uart_->write_array(buffer, count);
      this->uart_sent_ = true;
      sent = true;
    } else {
      ESP_LOGW(TAG, "Invalid UART data '%s'", data.c_str());
    }
  }
  uint32_t now = millis();
  root["now"] = now;
  if (sent)
    root["tx_t"] = now;
  this->uart_report_(caller, master, root);
}

void DaikinBridge::uart_report_(Client *client, bool master, JsonObject root) {
  this->report_client_(client, master, root);
  client->uart_overflows += this->uart_rx_.catch_up(client->uart_cursor);
  JsonArray rx = root["rx"].to<JsonArray>();
  uint64_t end = this->uart_rx_.end();
  size_t bytes = 0;
  size_t pieces = 0;
  for (size_t i = 0; i < this->uart_pieces_.size() && client->uart_cursor < end; i++) {
    const UartPiece &piece = this->uart_pieces_[i];
    uint64_t piece_end = i + 1 < this->uart_pieces_.size() ? this->uart_pieces_[i + 1].start : end;
    if (piece_end <= client->uart_cursor)
      continue;
    if (bytes >= MAX_UART_BYTES_PER_RESPONSE || pieces >= MAX_UART_PIECES_PER_RESPONSE)
      break;
    // Bytes before the first kept piece belong to it.
    uint64_t from = std::max(client->uart_cursor, i == 0 ? client->uart_cursor : piece.start);
    uint64_t to = std::min<uint64_t>(piece_end, from + (MAX_UART_BYTES_PER_RESPONSE - bytes));
    std::string hex;
    for (uint64_t seq = from; seq < to; seq++) {
      uint8_t value = this->uart_rx_.at(seq);
      append_hex(hex, &value, 1);
    }
    JsonArray item = rx.add<JsonArray>();
    item.add(piece.time);
    item.add(hex);
    item.add(piece.fresh && from == piece.start);
    bytes += to - from;
    pieces++;
    client->uart_cursor = to;
  }
  root["more"] = client->uart_cursor < end;
  root["overflows"] = client->uart_overflows;
}
#endif

}  // namespace esphome::daikin_bridge
