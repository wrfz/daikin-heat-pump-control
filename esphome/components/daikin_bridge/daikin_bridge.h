#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <string>
#include <vector>

#include "esphome/components/json/json_util.h"
#include "esphome/core/component.h"
#include "esphome/core/defines.h"

#ifdef USE_DAIKIN_BRIDGE_CAN
#include "esphome/components/canbus/canbus.h"
#endif
#ifdef USE_DAIKIN_BRIDGE_UART
#include "esphome/components/uart/uart.h"
#endif

namespace esphome::daikin_bridge {

/// Clients (Home Assistant instances) that can use the bridge at the same time.
static constexpr size_t MAX_CLIENTS = 4;

/// A CAN frame with the time it was received or sent (ms since start).
struct TimedFrame {
  uint32_t time;
  uint32_t can_id;
  uint8_t length;
  uint8_t data[8];
};

/// Ring buffer shared by all clients. Every entry has a sequence number; each
/// client reads from its own position. When the buffer is full, the oldest
/// entry is dropped; a client that has not read it yet loses it.
template<typename T> class SharedBuffer {
 public:
  void set_capacity(size_t capacity) {
    this->items_.assign(capacity, T{});
    this->end_ = 0;
    this->size_ = 0;
  }
  size_t capacity() const { return this->items_.size(); }
  /// Sequence number of the next entry.
  uint64_t end() const { return this->end_; }
  /// Sequence number of the oldest kept entry.
  uint64_t begin() const { return this->end_ - this->size_; }

  void push(const T &item) {
    if (this->items_.empty())
      return;
    this->items_[this->end_ % this->items_.size()] = item;
    this->end_++;
    if (this->size_ < this->items_.size())
      this->size_++;
  }

  const T &at(uint64_t seq) const { return this->items_[seq % this->items_.size()]; }

  /// Move `cursor` to the oldest kept entry if it fell behind; return the
  /// number of entries it missed.
  uint32_t catch_up(uint64_t &cursor) const {
    if (cursor >= this->begin())
      return 0;
    uint64_t missed = this->begin() - cursor;
    cursor = this->begin();
    return static_cast<uint32_t>(std::min<uint64_t>(missed, UINT32_MAX));
  }

 protected:
  std::vector<T> items_;
  uint64_t end_{0};
  size_t size_{0};
};

/// One client of the bridge, identified by the id it sends with every call.
struct Client {
  bool active{false};
  std::string id;
  uint32_t last_seen{0};
  uint32_t order{0};
  uint32_t rejected{0};
#ifdef USE_DAIKIN_BRIDGE_CAN
  uint64_t can_cursor{0};
  uint32_t can_overflows{0};
#endif
#ifdef USE_DAIKIN_BRIDGE_UART
  uint64_t uart_cursor{0};
  uint32_t uart_overflows{0};
#endif
};

#ifdef USE_DAIKIN_BRIDGE_UART
/// Start of a run of received UART bytes. `fresh` marks the first bytes after
/// the master sent something, i.e. the start of an answer.
struct UartPiece {
  uint64_t start;
  uint32_t time;
  bool fresh;
};
#endif

class DaikinBridge : public Component {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::AFTER_CONNECTION; }

  /// Answer of `daikin_bridge_info`.
  void info(JsonObject root);

  /// Answer of `daikin_bridge_claim`: make the client the master.
  void claim(const std::string &client, JsonObject root);

#ifdef USE_DAIKIN_BRIDGE_CAN
  void set_canbus(canbus::Canbus *canbus) { this->canbus_ = canbus; }
  void set_can_buffer_size(size_t size) { this->can_rx_.set_capacity(size); }
  void set_can_send_queue_size(size_t size) { this->can_send_queue_size_ = size; }
  void set_quiet_time(uint32_t ms) { this->quiet_time_ = ms; }

  /// Answer of `daikin_can_exchange`: queue `frames` ("<id hex>#<data hex>") if
  /// the client is the master and report what was received (and, to the
  /// master, sent) since the client's previous call.
  template<typename T> void can_exchange(const std::string &client, const T &frames, JsonObject root) {
    Client *caller = this->client_(client, root);
    if (caller == nullptr)
      return;
    bool master = this->is_master_(caller);
    for (const auto &frame : frames) {
      if (master)
        this->queue_can_frame_(std::string(frame));
      else
        caller->rejected++;
    }
    this->can_send_if_quiet_();
    this->can_report_(caller, master, root);
  }
#endif

#ifdef USE_DAIKIN_BRIDGE_UART
  void set_uart(uart::UARTComponent *uart) { this->uart_ = uart; }
  void set_uart_buffer_size(size_t size) { this->uart_rx_.set_capacity(size); }

  /// Answer of `daikin_uart_exchange`: send `data` (hex) if the client is the
  /// master and report the bytes received since the client's previous call.
  void uart_exchange(const std::string &client, const std::string &data, JsonObject root);
#endif

 protected:
  /// Find or register the client; on failure write the error and return null.
  Client *client_(const std::string &id, JsonObject root);
  bool is_master_(const Client *client) const;
  void set_master_(int index);
  void expire_clients_();
  void report_client_(const Client *client, bool master, JsonObject root) const;
  size_t client_count_() const;

  std::array<Client, MAX_CLIENTS> clients_{};
  int master_{-1};
  uint32_t next_order_{0};

#ifdef USE_DAIKIN_BRIDGE_CAN
  void on_can_frame_(uint32_t can_id, const std::vector<uint8_t> &data);
  void queue_can_frame_(const std::string &text);
  void can_send_if_quiet_();
  void can_report_(Client *client, bool master, JsonObject root);
  void can_poll_status_();
  const char *can_state_() const;

  canbus::Canbus *canbus_{nullptr};
  SharedBuffer<TimedFrame> can_rx_;
  std::vector<TimedFrame> can_sent_;
  std::deque<TimedFrame> can_queue_;
  size_t can_send_queue_size_{16};
  uint32_t quiet_time_{250};
  uint32_t last_bus_activity_{0};
  uint32_t can_dropped_{0};
  uint32_t can_send_errors_{0};
  uint32_t can_bus_off_count_{0};
  uint32_t last_status_poll_{0};
  bool can_bus_off_{false};
  canbus::CanStatus can_status_{};
#endif

#ifdef USE_DAIKIN_BRIDGE_UART
  void uart_read_();
  void uart_report_(Client *client, bool master, JsonObject root);

  uart::UARTComponent *uart_{nullptr};
  SharedBuffer<uint8_t> uart_rx_;
  std::deque<UartPiece> uart_pieces_;
  // Set when the master sent bytes; the next received byte starts a fresh piece.
  bool uart_sent_{false};
#endif
};

}  // namespace esphome::daikin_bridge
