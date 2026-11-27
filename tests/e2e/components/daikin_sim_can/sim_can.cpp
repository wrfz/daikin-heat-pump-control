#ifdef USE_HOST

#include "sim_can.h"

#include <arpa/inet.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "esphome/core/log.h"

namespace esphome::daikin_sim_can {

static const char *const TAG = "daikin_sim_can";

bool SimCan::setup_internal() {
  this->socket_ = ::socket(AF_INET, SOCK_DGRAM, 0);
  if (this->socket_ < 0)
    return false;
  // Bursts of several hundred frames must not be dropped by the socket before
  // the bridge reads them.
  int rcvbuf = 4 * 1024 * 1024;
  ::setsockopt(this->socket_, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof(rcvbuf));
  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_port = htons(this->port_);
  addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  if (::connect(this->socket_, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) != 0)
    return false;
  ::fcntl(this->socket_, F_SETFL, O_NONBLOCK);
  // Tell the simulator where to send its frames.
  ::send(this->socket_, "hello", 5, 0);
  return true;
}

canbus::Error SimCan::send_message(struct canbus::CanFrame *frame) {
  char text[32];
  int pos = std::snprintf(text, sizeof(text), "%03X#", static_cast<unsigned>(frame->can_id));
  for (uint8_t i = 0; i < frame->can_data_length_code && pos < 30; i++)
    pos += std::snprintf(text + pos, sizeof(text) - pos, "%02X", frame->data[i]);
  if (::send(this->socket_, text, pos, 0) != pos)
    return canbus::ERROR_FAIL;
  return canbus::ERROR_OK;
}

canbus::Error SimCan::read_message(struct canbus::CanFrame *frame) {
  char text[64];
  ssize_t len = ::recv(this->socket_, text, sizeof(text) - 1, 0);
  if (len <= 0)
    return canbus::ERROR_NOMSG;
  text[len] = '\0';
  char *sep = std::strchr(text, '#');
  if (sep == nullptr)
    return canbus::ERROR_NOMSG;
  *sep = '\0';
  frame->use_extended_id = false;
  frame->remote_transmission_request = false;
  frame->can_id = std::strtoul(text, nullptr, 16);
  size_t hex_len = std::strlen(sep + 1);
  frame->can_data_length_code = static_cast<uint8_t>(std::min<size_t>(hex_len / 2, canbus::CAN_MAX_DATA_LENGTH));
  for (uint8_t i = 0; i < frame->can_data_length_code; i++) {
    char byte[3] = {sep[1 + 2 * i], sep[2 + 2 * i], '\0'};
    frame->data[i] = static_cast<uint8_t>(std::strtoul(byte, nullptr, 16));
  }
  ESP_LOGV(TAG, "received %s", text);
  return canbus::ERROR_OK;
}

}  // namespace esphome::daikin_sim_can

#endif
