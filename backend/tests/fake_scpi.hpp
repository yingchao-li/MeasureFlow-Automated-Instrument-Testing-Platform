// In-process fake SCPI servers for the tests: a generic line server with the documented fault injection
// (MF:FAULT:*) plus a small "bench" (signal generator, audio analyzer, DUT) with plausible measurement values.
#pragma once

#include <atomic>
#include <condition_variable>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace mftest {

struct Reply {
  std::optional<std::string> text;  // nullopt: setter, no response line
  bool numeric = false;             // eligible for NAN/INF fault substitution
};

class FakeScpiServer {
 public:
  using Handler = std::function<Reply(const std::string& upper_cmd, const std::string& raw_cmd)>;
  // Called for every received command (not MF:FAULT:*) before it is processed; index counts from 1.
  using Trigger = std::function<void(FakeScpiServer&, const std::string& cmd, int index)>;

  explicit FakeScpiServer(Handler handler);
  ~FakeScpiServer();
  FakeScpiServer(const FakeScpiServer&) = delete;
  FakeScpiServer& operator=(const FakeScpiServer&) = delete;

  uint16_t port() const { return port_; }
  void stop();
  // Close the listening socket and all connections (simulates a crashed simulator); port stays reserved? no: freed.
  void kill();
  void drop_connections();

  std::vector<std::string> received() const;
  int count_received(const std::string& exact_upper) const;
  int accepted_connections() const { return accepted_.load(); }
  // Waits until `n` connections were accepted AND registered (so drop_connections() will see them).
  bool wait_accepted(int n, int timeout_ms = 1000) const;
  void clear_received();
  void set_trigger(Trigger t);
  void set_reply_delay_ms(int ms) { reply_delay_ms_ = ms; }

  // Fault counters (same semantics as MF:FAULT:*; usable directly from tests).
  std::atomic<int> f_timeout{0}, f_disconnect{0}, f_garbage{0}, f_fragment{0}, f_nan{0}, f_inf{0}, f_oversize{0};
  std::atomic<int> timeout_delay_ms{5000}, fragment_chunk{3}, fragment_delay_ms{15};
  void clear_faults();

 private:
  void accept_loop();
  void serve(int fd);
  bool send_reply(int fd, std::string text);
  Reply handle_fault_command(const std::string& upper, const std::string& raw);

  Handler handler_;
  uint16_t port_ = 0;
  int listen_fd_ = -1;
  std::atomic<bool> stopping_{false};
  std::thread acceptor_;
  mutable std::mutex mu_;
  std::vector<std::thread> workers_;
  std::vector<int> conn_fds_;
  std::vector<std::string> received_;
  Trigger trigger_;
  std::atomic<int> accepted_{0};
  std::atomic<int> reply_delay_ms_{0};
  int command_index_ = 0;
};

// A coherent three-instrument fake modelled on docs/INTERFACE.md (simplified analytics).
class FakeBench {
  struct State;
  std::shared_ptr<State> st_;  // declared first: the servers' handlers use it

 public:
  FakeBench();
  FakeScpiServer siggen, analyzer, dut;
  // Backend instruments.json pointing at the three ports.
  std::string instruments_json(int timeout_ms = 400, int max_retries = 2, int connect_timeout_ms = 300) const;

  // Observable state (thread-safe snapshots)
  bool output_on() const;
  std::string dut_firmware() const;
  std::string dut_profile() const;
  void set_dut_nan_fault(bool on);
};

// Temp repository root with configs copied from the real repo (sequences, calibration) and a generated
// instruments.json. Removed on destruction.
class TempRoot {
 public:
  explicit TempRoot(const std::string& instruments_json, bool copy_calibration = true);
  ~TempRoot();
  const std::string& path() const { return path_; }
  void write(const std::string& relative, const std::string& content) const;
  std::string read(const std::string& relative) const;
  bool exists(const std::string& relative) const;

 private:
  std::string path_;
};

}  // namespace mftest
