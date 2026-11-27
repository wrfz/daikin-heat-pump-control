#pragma once

#include <algorithm>
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

/// A CAN frame with the time it was received or sent (ms since start).
struct TimedFrame {
  uint32_t time;
  uint32_t can_id;
  uint8_t length;
  uint8_t data[8];
};

/// Ring buffer of fixed capacity; the oldest entry is dropped when full.
template<typename T> class RingBuffer {
 public:
  void set_capacity(size_t capacity) {
    this->items_.assign(capacity, T{});
    this->head_ = 0;
    this->size_ = 0;
  }
  size_t capacity() const { return this->items_.size(); }
  size_t size() const { return this->size_; }
  uint32_t overflows() const { return this->overflows_; }

  void push(const T &item) {
    if (this->items_.empty())
      return;
    if (this->size_ == this->items_.size()) {
      this->head_ = (this->head_ + 1) % this->items_.size();
      this->size_--;
      this->overflows_++;
    }
    this->items_[(this->head_ + this->size_) % this->items_.size()] = item;
    this->size_++;
  }

  /// Call `fn` for up to `max` entries in order and remove them.
  template<typename F> void drain(F &&fn, size_t max = SIZE_MAX) {
    size_t count = std::min(max, this->size_);
    for (size_t i = 0; i < count; i++)
      fn(this->items_[(this->head_ + i) % this->items_.size()]);
    if (!this->items_.empty())
      this->head_ = (this->head_ + count) % this->items_.size();
    this->size_ -= count;
  }

 protected:
  std::vector<T> items_;
  size_t head_{0};
  size_t size_{0};
  uint32_t overflows_{0};
};

class DaikinBridge : public Component {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::AFTER_CONNECTION; }

  /// Answer of `daikin_bridge_info`.
  void info(JsonObject root);

#ifdef USE_DAIKIN_BRIDGE_CAN
  void set_canbus(canbus::Canbus *canbus) { this->canbus_ = canbus; }
  void set_can_buffer_size(size_t size) { this->can_rx_.set_capacity(size); }
  void set_can_send_queue_size(size_t size) { this->can_send_queue_size_ = size; }
  void set_quiet_time(uint32_t ms) { this->quiet_time_ = ms; }

  /// Answer of `daikin_can_exchange`: queue `frames` ("<id hex>#<data hex>") and
  /// report everything received and sent since the previous call.
  template<typename T> void can_exchange(const T &frames, JsonObject root) {
    for (const auto &frame : frames)
      this->queue_can_frame_(std::string(frame));
    this->can_send_if_quiet_();
    this->can_report_(root);
  }
#endif

#ifdef USE_DAIKIN_BRIDGE_UART
  void set_uart(uart::UARTComponent *uart) { this->uart_ = uart; }
  void set_uart_buffer_size(size_t size) { this->uart_rx_.set_capacity(size); }

  /// Answer of `daikin_uart_exchange`: send `data` (hex) and report the bytes
  /// received since the previous call.
  void uart_exchange(const std::string &data, JsonObject root);
#endif

 protected:
#ifdef USE_DAIKIN_BRIDGE_CAN
  void on_can_frame_(uint32_t can_id, const std::vector<uint8_t> &data);
  void queue_can_frame_(const std::string &text);
  void can_send_if_quiet_();
  void can_report_(JsonObject root);
  void can_poll_status_();
  const char *can_state_() const;

  canbus::Canbus *canbus_{nullptr};
  RingBuffer<TimedFrame> can_rx_;
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

  uart::UARTComponent *uart_{nullptr};
  RingBuffer<uint8_t> uart_rx_;
  uint32_t uart_rx_time_{0};
  bool uart_rx_time_set_{false};
#endif
};

}  // namespace esphome::daikin_bridge
