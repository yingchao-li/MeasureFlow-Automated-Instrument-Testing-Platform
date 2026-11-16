#include "measureflow/net/tcp_connection.hpp"

#include <arpa/inet.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>

#include "measureflow/util/time.hpp"

namespace mf {

namespace {

constexpr int kPollSliceMs = 25;

void set_nonblocking(int fd, bool on) {
  const int flags = ::fcntl(fd, F_GETFL, 0);
  if (flags < 0) return;
  ::fcntl(fd, F_SETFL, on ? (flags | O_NONBLOCK) : (flags & ~O_NONBLOCK));
}

// Waits for `events` on fd for up to `timeout_ms`, in slices so a cancel flag is noticed.
// Returns true when ready, false on timeout. Throws on cancel/poll error.
bool wait_fd(int fd, short events, int timeout_ms, const std::atomic<bool>* cancel) {
  const auto deadline = SteadyClock::now() + std::chrono::milliseconds(std::max(timeout_ms, 0));
  while (true) {
    if (cancel && cancel->load(std::memory_order_relaxed)) throw NetError(NetErrorKind::Cancelled, "cancelled");
    const auto now = SteadyClock::now();
    long long remaining = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now).count();
    if (remaining < 0) remaining = 0;
    const int slice = static_cast<int>(std::min<long long>(remaining, kPollSliceMs));
    struct pollfd p;
    p.fd = fd;
    p.events = events;
    p.revents = 0;
    const int rc = ::poll(&p, 1, slice);
    if (rc < 0) {
      if (errno == EINTR) continue;
      throw NetError(NetErrorKind::Io, std::string("poll failed: ") + std::strerror(errno));
    }
    if (rc > 0) return true;
    if (SteadyClock::now() >= deadline) return false;
  }
}

}  // namespace

TcpConnection::~TcpConnection() { close(); }

void TcpConnection::close() {
  std::lock_guard<std::mutex> lock(fd_mu_);
  const int fd = fd_.exchange(-1);
  if (fd >= 0) ::close(fd);
  buffer_.clear();
}

void TcpConnection::interrupt() {
  std::lock_guard<std::mutex> lock(fd_mu_);
  const int fd = fd_.load();
  if (fd >= 0) ::shutdown(fd, SHUT_RDWR);
}

void TcpConnection::connect(const std::string& host, uint16_t port, int timeout_ms) {
  close();
  const std::string h = (host == "localhost") ? "127.0.0.1" : host;
  struct addrinfo hints;
  std::memset(&hints, 0, sizeof hints);
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;
  hints.ai_flags = AI_NUMERICHOST;  // callers only pass numeric loopback addresses
  struct addrinfo* res = nullptr;
  const std::string port_s = std::to_string(port);
  const int gai = ::getaddrinfo(h.c_str(), port_s.c_str(), &hints, &res);
  if (gai != 0 || !res) {
    throw NetError(NetErrorKind::ConnectFailed, "cannot resolve host '" + host + "': " + ::gai_strerror(gai));
  }
  struct AddrGuard {
    struct addrinfo* p;
    ~AddrGuard() { ::freeaddrinfo(p); }
  } guard{res};

  std::string last_err = "no address";
  bool timed_out = false;
  for (struct addrinfo* ai = res; ai; ai = ai->ai_next) {
#ifdef SOCK_CLOEXEC
    const int fd = ::socket(ai->ai_family, ai->ai_socktype | SOCK_CLOEXEC, ai->ai_protocol);
#else  // macOS has no SOCK_CLOEXEC: set the flag right after creation instead
    const int fd = ::socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
    if (fd >= 0) ::fcntl(fd, F_SETFD, FD_CLOEXEC);
#endif
    if (fd < 0) {
      last_err = std::strerror(errno);
      continue;
    }
    set_nonblocking(fd, true);
    int rc = ::connect(fd, ai->ai_addr, ai->ai_addrlen);
    if (rc < 0 && errno != EINPROGRESS && errno != EINTR) {
      last_err = std::strerror(errno);
      ::close(fd);
      continue;
    }
    if (rc < 0) {
      bool ready = false;
      try {
        ready = wait_fd(fd, POLLOUT, timeout_ms, nullptr);
      } catch (const NetError&) {
        ::close(fd);
        throw;
      }
      if (!ready) {
        timed_out = true;
        last_err = "connect timed out after " + std::to_string(timeout_ms) + " ms";
        ::close(fd);
        continue;
      }
      int soerr = 0;
      socklen_t len = sizeof soerr;
      ::getsockopt(fd, SOL_SOCKET, SO_ERROR, &soerr, &len);
      if (soerr != 0) {
        last_err = std::strerror(soerr);
        ::close(fd);
        continue;
      }
    }
    set_nonblocking(fd, false);
    // Non-blocking I/O is driven by poll() below; keep the socket non-blocking for reads/writes.
    set_nonblocking(fd, true);
    int one = 1;
    ::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
#ifdef SO_NOSIGPIPE
    ::setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof one);
#endif
    {
      std::lock_guard<std::mutex> lock(fd_mu_);
      fd_.store(fd);
      buffer_.clear();
    }
    peer_ = host + ":" + port_s;
    return;
  }
  throw NetError(timed_out ? NetErrorKind::ConnectTimeout : NetErrorKind::ConnectFailed,
                 "connect to " + host + ":" + port_s + " failed: " + last_err);
}

void TcpConnection::send_all(const std::string& data, int timeout_ms, const std::atomic<bool>* cancel) {
  const int fd = fd_.load();
  if (fd < 0) throw NetError(NetErrorKind::Closed, "connection is not open");
  size_t off = 0;
  int flags = 0;
#ifdef MSG_NOSIGNAL
  flags |= MSG_NOSIGNAL;
#endif
  while (off < data.size()) {
    const ssize_t n = ::send(fd, data.data() + off, data.size() - off, flags);
    if (n > 0) {
      off += static_cast<size_t>(n);
      continue;
    }
    if (n < 0 && errno == EINTR) continue;
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
      if (!wait_fd(fd, POLLOUT, timeout_ms, cancel)) throw NetError(NetErrorKind::Timeout, "send timed out");
      continue;
    }
    if (n < 0 && (errno == EPIPE || errno == ECONNRESET || errno == ENOTCONN || errno == EBADF)) {
      throw NetError(NetErrorKind::Closed, std::string("connection closed during send: ") + std::strerror(errno));
    }
    throw NetError(NetErrorKind::Io, std::string("send failed: ") + std::strerror(errno));
  }
}

std::string TcpConnection::recv_line(size_t max_bytes, int per_read_timeout_ms, int total_timeout_ms,
                                     const std::atomic<bool>* cancel) {
  const int fd = fd_.load();
  if (fd < 0) throw NetError(NetErrorKind::Closed, "connection is not open");
  const auto start = SteadyClock::now();
  char chunk[8192];
  while (true) {
    // Complete line already buffered?
    const size_t nl = buffer_.find('\n');
    if (nl != std::string::npos) {
      if (nl > max_bytes) {
        throw NetError(NetErrorKind::TooLarge, "response line exceeds " + std::to_string(max_bytes) + " bytes");
      }
      std::string line = buffer_.substr(0, nl);
      buffer_.erase(0, nl + 1);
      if (!line.empty() && line.back() == '\r') line.pop_back();
      return line;
    }
    if (buffer_.size() > max_bytes) {
      throw NetError(NetErrorKind::TooLarge, "response exceeds " + std::to_string(max_bytes) + " bytes without terminator");
    }
    // Determine how long we may still wait.
    int wait_ms = per_read_timeout_ms;
    if (total_timeout_ms > 0) {
      const long long elapsed =
          std::chrono::duration_cast<std::chrono::milliseconds>(SteadyClock::now() - start).count();
      const long long left = total_timeout_ms - elapsed;
      if (left <= 0) throw NetError(NetErrorKind::Timeout, "response timed out (total " + std::to_string(total_timeout_ms) + " ms)");
      wait_ms = static_cast<int>(std::min<long long>(left, per_read_timeout_ms));
    }
    if (!wait_fd(fd, POLLIN, wait_ms, cancel)) {
      const long long elapsed =
          std::chrono::duration_cast<std::chrono::milliseconds>(SteadyClock::now() - start).count();
      throw NetError(NetErrorKind::Timeout, "no data received for " + std::to_string(elapsed) + " ms");
    }
    const ssize_t n = ::recv(fd, chunk, sizeof chunk, 0);
    if (n > 0) {
      buffer_.append(chunk, static_cast<size_t>(n));
      continue;
    }
    if (n == 0) throw NetError(NetErrorKind::Closed, "connection closed by peer");
    if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) continue;
    if (errno == ECONNRESET || errno == EPIPE || errno == ENOTCONN || errno == EBADF) {
      throw NetError(NetErrorKind::Closed, std::string("connection reset: ") + std::strerror(errno));
    }
    throw NetError(NetErrorKind::Io, std::string("recv failed: ") + std::strerror(errno));
  }
}

size_t TcpConnection::discard_pending() {
  size_t dropped = buffer_.size();
  buffer_.clear();
  const int fd = fd_.load();
  if (fd < 0) return dropped;
  char chunk[4096];
  while (true) {
    const ssize_t n = ::recv(fd, chunk, sizeof chunk, 0);
    if (n > 0) {
      dropped += static_cast<size_t>(n);
      continue;
    }
    break;
  }
  return dropped;
}

}  // namespace mf
