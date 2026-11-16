// RAII TCP client connection with timeouts, line framing and bounded reads.
//
// Properties:
//  * connect with timeout (non-blocking connect + poll), loopback or any numeric/DNS host
//  * send_all: loops over partial writes, EINTR-safe, never raises SIGPIPE (MSG_NOSIGNAL / SO_NOSIGPIPE)
//  * recv_line: '\n'-framed, per-read and total timeouts, partial reads are accumulated, bytes that
//    arrive after the terminator are kept for the next call, hard cap on the line length
//  * interrupt(): thread-safe shutdown() that wakes up a blocked reader (used for cancel / shutdown)
//  * optional cancel flag polled every <= 25 ms while waiting
//
// Locking: `fd_mu_` only guards the fd value against close/interrupt races; it is a leaf lock.
#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <stdexcept>
#include <string>

namespace mf {

enum class NetErrorKind { ConnectFailed, ConnectTimeout, Timeout, Closed, TooLarge, Io, Cancelled };

class NetError : public std::runtime_error {
 public:
  NetError(NetErrorKind kind, const std::string& msg) : std::runtime_error(msg), kind_(kind) {}
  NetErrorKind kind() const { return kind_; }

 private:
  NetErrorKind kind_;
};

class TcpConnection {
 public:
  TcpConnection() = default;
  ~TcpConnection();
  TcpConnection(const TcpConnection&) = delete;
  TcpConnection& operator=(const TcpConnection&) = delete;

  // Opens a connection; throws NetError(ConnectFailed|ConnectTimeout).
  void connect(const std::string& host, uint16_t port, int timeout_ms);
  bool is_open() const { return fd_.load() >= 0; }
  void close();
  // Thread-safe: makes pending/future I/O fail promptly. Does not close the descriptor.
  void interrupt();

  // Sends all bytes within `timeout_ms` (per-poll). Throws NetError(Closed|Timeout|Io|Cancelled).
  void send_all(const std::string& data, int timeout_ms, const std::atomic<bool>* cancel = nullptr);
  // Reads until '\n'. The terminator (and one preceding '\r') is stripped.
  //   per_read_timeout_ms: max silence between two chunks
  //   total_timeout_ms:    max time for the whole line (0 = unlimited)
  //   max_bytes:           max line length (excluding terminator); NetError(TooLarge) when exceeded
  std::string recv_line(size_t max_bytes, int per_read_timeout_ms, int total_timeout_ms,
                        const std::atomic<bool>* cancel = nullptr);
  // Discards anything currently buffered/readable (used after a protocol desync). Returns bytes dropped.
  size_t discard_pending();

  std::string peer() const { return peer_; }

 private:
  std::atomic<int> fd_{-1};
  std::mutex fd_mu_;
  std::string buffer_;
  std::string peer_;
};

}  // namespace mf
