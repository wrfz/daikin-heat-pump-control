#pragma once

#ifdef USE_HOST

#include "esphome/components/canbus/canbus.h"

namespace esphome::daikin_sim_can {

/// CAN bus that sends each frame as a UDP datagram "<id hex>#<data hex>" to
/// the simulator on localhost and receives its frames the same way.
class SimCan final : public canbus::Canbus {
 public:
  void set_port(uint16_t port) { this->port_ = port; }

 protected:
  bool setup_internal() override;
  canbus::Error send_message(struct canbus::CanFrame *frame) override;
  canbus::Error read_message(struct canbus::CanFrame *frame) override;

  uint16_t port_{0};
  int socket_{-1};
};

}  // namespace esphome::daikin_sim_can

#endif
