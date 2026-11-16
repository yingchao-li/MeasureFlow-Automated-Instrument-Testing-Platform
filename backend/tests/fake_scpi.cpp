#include "fake_scpi.hpp"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <stdexcept>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>

namespace mftest {

namespace {
std::string upper(std::string s) {
  for (char& c : s)
    if (c >= 'a' && c <= 'z') c = static_cast<char>(c - 'a' + 'A');
  return s;
}
std::string trim(const std::string& s) {
  size_t b = 0, e = s.size();
  while (b < e && (s[b] == ' ' || s[b] == '\t' || s[b] == '\r')) ++b;
  while (e > b && (s[e - 1] == ' ' || s[e - 1] == '\t' || s[e - 1] == '\r')) --e;
  return s.substr(b, e - b);
}
std::string g9(double v) {
  char buf[40];
  std::snprintf(buf, sizeof buf, "%.9g", v);
  return buf;
}
}  // namespace

FakeScpiServer::FakeScpiServer(Handler handler) : handler_(std::move(handler)) {
  listen_fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
  int one = 1;
  ::setsockopt(listen_fd_, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  addr.sin_port = 0;
  if (::bind(listen_fd_, reinterpret_cast<sockaddr*>(&addr), sizeof addr) != 0) throw std::runtime_error("fake server bind failed");
  socklen_t len = sizeof addr;
  ::getsockname(listen_fd_, reinterpret_cast<sockaddr*>(&addr), &len);
  port_ = ntohs(addr.sin_port);
  ::listen(listen_fd_, 16);
  acceptor_ = std::thread([this] { accept_loop(); });
}

FakeScpiServer::~FakeScpiServer() { stop(); }

void FakeScpiServer::stop() {
  if (stopping_.exchange(true)) return;
  if (listen_fd_ >= 0) {
    ::shutdown(listen_fd_, SHUT_RDWR);
    ::close(listen_fd_);
    listen_fd_ = -1;
  }
  {
    std::lock_guard<std::mutex> lk(mu_);
    for (int fd : conn_fds_) ::shutdown(fd, SHUT_RDWR);
  }
  if (acceptor_.joinable()) acceptor_.join();
  std::vector<std::thread> ws;
  {
    std::lock_guard<std::mutex> lk(mu_);
    ws.swap(workers_);
  }
  for (auto& t : ws)
    if (t.joinable()) t.join();
}

void FakeScpiServer::kill() { stop(); }

void FakeScpiServer::drop_connections() {
  std::lock_guard<std::mutex> lk(mu_);
  for (int fd : conn_fds_) ::shutdown(fd, SHUT_RDWR);
}

void FakeScpiServer::accept_loop() {
  while (!stopping_) {
    pollfd p{listen_fd_, POLLIN, 0};
    if (listen_fd_ < 0) break;
    const int rc = ::poll(&p, 1, 50);
    if (rc <= 0) continue;
    const int fd = ::accept(listen_fd_, nullptr, nullptr);
    if (fd < 0) continue;
#ifdef SO_NOSIGPIPE
    const int one = 1;
    ::setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof one);
#endif
    std::lock_guard<std::mutex> lk(mu_);
    conn_fds_.push_back(fd);
    workers_.emplace_back([this, fd] { serve(fd); });
    ++accepted_;
  }
}

bool FakeScpiServer::wait_accepted(int n, int timeout_ms) const {
  const auto end = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
  while (std::chrono::steady_clock::now() < end) {
    if (accepted_.load() >= n) return true;
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
  return accepted_.load() >= n;
}

std::vector<std::string> FakeScpiServer::received() const {
  std::lock_guard<std::mutex> lk(mu_);
  return received_;
}

int FakeScpiServer::count_received(const std::string& exact_upper) const {
  std::lock_guard<std::mutex> lk(mu_);
  int n = 0;
  for (const auto& r : received_)
    if (upper(r) == exact_upper) ++n;
  return n;
}

void FakeScpiServer::clear_received() {
  std::lock_guard<std::mutex> lk(mu_);
  received_.clear();
}

void FakeScpiServer::set_trigger(Trigger t) {
  std::lock_guard<std::mutex> lk(mu_);
  trigger_ = std::move(t);
}

void FakeScpiServer::clear_faults() {
  f_timeout = f_disconnect = f_garbage = f_fragment = f_nan = f_inf = f_oversize = 0;
}

bool FakeScpiServer::send_reply(int fd, std::string text) {
  text += "\n";
  const int chunk = f_fragment.load() > 0 ? std::max(1, fragment_chunk.load()) : 0;
  if (chunk > 0) --f_fragment;
  size_t off = 0;
  while (off < text.size()) {
    const size_t n = chunk > 0 ? std::min<size_t>(static_cast<size_t>(chunk), text.size() - off) : text.size() - off;
#ifdef MSG_NOSIGNAL
    const int send_flags = MSG_NOSIGNAL;
#else  // macOS: no MSG_NOSIGNAL; SIGPIPE is suppressed with SO_NOSIGPIPE on the accepted socket
    const int send_flags = 0;
#endif
    const ssize_t w = ::send(fd, text.data() + off, n, send_flags);
    if (w <= 0) return false;
    off += static_cast<size_t>(w);
    if (chunk > 0 && off < text.size()) std::this_thread::sleep_for(std::chrono::milliseconds(fragment_delay_ms.load()));
  }
  return true;
}

Reply FakeScpiServer::handle_fault_command(const std::string& up, const std::string& raw) {
  if (up == "MF:FAULT?") {
    return {"TIMEOUT=" + std::to_string(f_timeout.load()) + ",DISCONNECT=" + std::to_string(f_disconnect.load()) +
                ",GARBAGE=" + std::to_string(f_garbage.load()) + ",FRAGMENT=" + std::to_string(f_fragment.load()) +
                ",NAN=" + std::to_string(f_nan.load()) + ",INF=" + std::to_string(f_inf.load()) + ",OVERSIZE=" + std::to_string(f_oversize.load()),
            false};
  }
  const size_t sp = raw.find(' ');
  const std::string head = upper(raw.substr(0, sp));
  std::vector<int> args;
  if (sp != std::string::npos) {
    std::stringstream ss(raw.substr(sp + 1));
    std::string part;
    while (std::getline(ss, part, ',')) args.push_back(std::atoi(trim(part).c_str()));
  }
  const int n = args.empty() ? 1 : args[0];
  if (head == "MF:FAULT:TIMEOUT") {
    f_timeout = n;
    if (args.size() > 1) timeout_delay_ms = args[1];
  } else if (head == "MF:FAULT:DISCONNECT") f_disconnect = n;
  else if (head == "MF:FAULT:GARBAGE") f_garbage = n;
  else if (head == "MF:FAULT:FRAGMENT") {
    f_fragment = n;
    if (args.size() > 1) fragment_chunk = args[1];
    if (args.size() > 2) fragment_delay_ms = args[2];
  } else if (head == "MF:FAULT:NAN") f_nan = n;
  else if (head == "MF:FAULT:INF") f_inf = n;
  else if (head == "MF:FAULT:OVERSIZE") f_oversize = n;
  else if (head == "MF:FAULT:CLEAR") clear_faults();
  return {std::nullopt, false};
}

void FakeScpiServer::serve(int fd) {
  std::string buf;
  char tmp[1024];
  while (!stopping_) {
    pollfd p{fd, POLLIN, 0};
    const int rc = ::poll(&p, 1, 50);
    if (rc < 0) break;
    if (rc == 0) continue;
    const ssize_t n = ::recv(fd, tmp, sizeof tmp, 0);
    if (n <= 0) break;
    buf.append(tmp, static_cast<size_t>(n));
    size_t nl;
    while ((nl = buf.find('\n')) != std::string::npos) {
      const std::string raw = trim(buf.substr(0, nl));
      buf.erase(0, nl + 1);
      if (raw.empty()) continue;
      const std::string up = upper(raw);
      Reply rep;
      bool is_fault_cmd = up.rfind("MF:FAULT", 0) == 0;
      Trigger trig;
      int index = 0;
      {
        std::lock_guard<std::mutex> lk(mu_);
        received_.push_back(raw);
        if (!is_fault_cmd) {
          index = ++command_index_;
          trig = trigger_;
        }
      }
      if (is_fault_cmd) {
        rep = handle_fault_command(up, raw);
        if (rep.text && !send_reply(fd, *rep.text)) goto done;
        continue;
      }
      if (trig) trig(*this, raw, index);
      if (f_disconnect.load() > 0) {
        --f_disconnect;
        goto done;
      }
      rep = handler_(up, raw);
      if (f_timeout.load() > 0) {
        --f_timeout;
        const auto end = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_delay_ms.load());
        while (std::chrono::steady_clock::now() < end && !stopping_) std::this_thread::sleep_for(std::chrono::milliseconds(10));
        if (stopping_) goto done;
      }
      if (reply_delay_ms_.load() > 0) std::this_thread::sleep_for(std::chrono::milliseconds(reply_delay_ms_.load()));
      if (rep.text) {
        std::string text = *rep.text;
        if (f_garbage.load() > 0) {
          --f_garbage;
          text = "#!GARBAGE~~";
        } else if (rep.numeric && f_nan.load() > 0) {
          --f_nan;
          text = "NAN";
        } else if (rep.numeric && f_inf.load() > 0) {
          --f_inf;
          text = "INF";
        } else if (f_oversize.load() > 0) {
          --f_oversize;
          text += std::string(2u * 1024u * 1024u + 16u, 'x');
        }
        if (!send_reply(fd, text)) goto done;
      }
    }
  }
done:
  ::shutdown(fd, SHUT_RDWR);
  ::close(fd);
  std::lock_guard<std::mutex> lk(mu_);
  conn_fds_.erase(std::remove(conn_fds_.begin(), conn_fds_.end(), fd), conn_fds_.end());
}

// ------------------------------------------------------------------------------------------------ bench

struct FakeBench::State {
  std::mutex mu;
  // generator
  std::string function = "SIN";
  double freq = 1000, amp = 0.05, srate = 48000;
  bool output = false;
  // analyzer
  int points = 16384;
  bool stored = false;
  long long counter = 0;
  // dut
  std::string profile = "NORMAL";
  double gain = 20, hpf = 100, lpf = 8000, noise = -80, hd2 = 0.004, hd3 = 0.01, clip = 1.5;
  std::string firmware = "1.0.0";
  bool dut_nan = false;
  // error queues
  std::vector<std::string> errq_sg, errq_an, errq_dut;

  void rst_sg() { function = "SIN"; freq = 1000; amp = 0.05; srate = 48000; output = false; }
  void rst_an() { points = 16384; stored = false; counter = 0; }
  void rst_dut() {
    profile = "NORMAL"; gain = 20; hpf = 100; lpf = 8000; noise = -80; hd2 = 0.004; hd3 = 0.01; clip = 1.5; firmware = "1.0.0"; dut_nan = false;
  }
  void load_profile(const std::string& p) {
    gain = 20; noise = -80; hd2 = 0.004; hd3 = 0.01; clip = 1.5;
    if (p == "LOWGAIN") gain = 14;
    else if (p == "HIGHTHD") { hd2 = 0.10; hd3 = 0.30; }
    else if (p == "NOISY") noise = -50;
    else if (p == "CLIPPING") clip = 0.3;
    profile = p;
  }
  double thd_percent() const {
    double t = 100.0 * std::sqrt(std::pow(hd2 * amp * std::pow(10.0, gain / 20.0) / 2, 2) + std::pow(hd3 * std::pow(amp * std::pow(10.0, gain / 20.0), 2) / 4, 2)) / (amp * std::pow(10.0, gain / 20.0));
    if (profile == "NORMAL" && firmware == "1.2.0") t = 2.0;
    if (profile == "NORMAL" && firmware != "1.2.0") t = 0.15;
    if (profile == "HIGHTHD") t = 3.0;
    if (profile == "CLIPPING") t = 20.0;
    return t;
  }
  double noise_inband() const { return noise + 10.0 * std::log10(19980.0 / 24000.0) + (firmware == "1.2.0" ? 5.0 : 0.0); }
  double out_fund() const { return std::min(amp * std::pow(10.0, gain / 20.0), clip); }
};

namespace {
std::string err_text(int code, const std::string& msg) { return std::to_string(code) + ",\"" + msg + "\""; }

void push_err(std::vector<std::string>& q, int code, const std::string& msg) { q.push_back(err_text(code, msg)); }

// handles *IDN? etc. Returns true if handled.
bool common(const std::string& up, std::vector<std::string>& q, const std::string& idn, Reply& r, const std::function<void()>& rst) {
  if (up == "*IDN?") { r = {idn, false}; return true; }
  if (up == "*RST") { rst(); return true; }
  if (up == "*CLS") { q.clear(); return true; }
  if (up == "*OPC?") { r = {std::string("1"), false}; return true; }
  if (up == "*TST?") { r = {std::string("0"), false}; return true; }
  if (up == "SYST:VERS?") { r = {std::string("1999.0"), false}; return true; }
  if (up == "MF:SIM:VERS?") { r = {std::string("0.1.0-fake"), false}; return true; }
  if (up == "SYST:ERR?") {
    if (q.empty()) r = {std::string("0,\"No error\""), false};
    else { r = {q.front(), false}; q.erase(q.begin()); }
    return true;
  }
  return false;
}

bool arg_number(const std::string& raw, double* out) {
  const size_t sp = raw.find(' ');
  if (sp == std::string::npos) return false;
  char* end = nullptr;
  const std::string a = trim(raw.substr(sp + 1));
  *out = std::strtod(a.c_str(), &end);
  return end && *end == '\0' && !a.empty();
}
std::string arg_text(const std::string& raw) {
  const size_t sp = raw.find(' ');
  return sp == std::string::npos ? std::string() : trim(raw.substr(sp + 1));
}
}  // namespace

FakeBench::FakeBench()
    : st_(std::make_shared<State>()),
      siggen([this](const std::string& up, const std::string& raw) {
        std::lock_guard<std::mutex> lk(st_->mu);
        State& s = *st_;
        Reply r;
        if (common(up, s.errq_sg, "MeasureFlow,VSG-1000,SN-SIM-0001,1.0.0", r, [&] { s.rst_sg(); })) return r;
        double v;
        if (up == "SOUR:FUNC?") return Reply{s.function, false};
        if (up.rfind("SOUR:FUNC ", 0) == 0) {
          const std::string f = arg_text(up);
          if (f == "SIN" || f == "SQU" || f == "CHIR" || f == "NOIS") s.function = f; else push_err(s.errq_sg, -224, "Illegal parameter value");
          return Reply{};
        }
        if (up == "SOUR:FREQ?") return Reply{g9(s.freq), true};
        if (up.rfind("SOUR:FREQ ", 0) == 0) {
          if (!arg_number(raw, &v)) push_err(s.errq_sg, -104, "Data type error");
          else if (v < 10 || v > 20000) push_err(s.errq_sg, -222, "Data out of range");
          else s.freq = v;
          s.stored = false;
          return Reply{};
        }
        if (up == "SOUR:VOLT?") return Reply{g9(s.amp), true};
        if (up.rfind("SOUR:VOLT ", 0) == 0) {
          if (!arg_number(raw, &v)) push_err(s.errq_sg, -104, "Data type error");
          else if (v < 0 || v > 5) push_err(s.errq_sg, -222, "Data out of range");
          else s.amp = v;
          return Reply{};
        }
        if (up.rfind("MF:SOUR:SRAT ", 0) == 0) {
          if (arg_number(raw, &v) && v >= 8000 && v <= 192000) s.srate = v; else push_err(s.errq_sg, -222, "Data out of range");
          return Reply{};
        }
        if (up == "MF:SOUR:SRAT?") return Reply{g9(s.srate), true};
        if (up == "OUTP?") return Reply{std::string(s.output ? "1" : "0"), true};
        if (up.rfind("OUTP ", 0) == 0) {
          const std::string a = arg_text(up);
          if (a == "ON" || a == "1") s.output = true; else if (a == "OFF" || a == "0") s.output = false; else push_err(s.errq_sg, -104, "Data type error");
          return Reply{};
        }
        if (up == "MF:SOUR:CONF?") return Reply{s.function + "," + g9(s.freq) + "," + g9(s.amp) + "," + g9(s.srate) + "," + (s.output ? "1" : "0"), false};
        push_err(s.errq_sg, -113, "Undefined header");
        return Reply{};
      }),
      analyzer([this](const std::string& up, const std::string& raw) {
        std::lock_guard<std::mutex> lk(st_->mu);
        State& s = *st_;
        Reply r;
        if (common(up, s.errq_an, "MeasureFlow,VAA-2000,SN-SIM-0002,1.0.0", r, [&] { s.rst_an(); })) return r;
        double v;
        if (up == "MF:ACQ:POIN?") return Reply{std::to_string(s.points), true};
        if (up.rfind("MF:ACQ:POIN ", 0) == 0) {
          if (arg_number(raw, &v) && v >= 1024 && v <= 65536) { s.points = static_cast<int>(v); s.stored = false; } else push_err(s.errq_an, -222, "Data out of range");
          return Reply{};
        }
        if (up == "MF:ACQ:INIT") { s.stored = true; ++s.counter; return Reply{}; }
        if (up == "MF:ACQ:CONF?") return Reply{std::to_string(s.points) + "," + g9(s.srate) + "," + (s.stored ? "1" : "0") + "," + std::to_string(s.counter), false};
        if (up.rfind("MF:ACQ:WAV?", 0) == 0) {
          int n = 512;
          if (arg_number(raw, &v)) n = static_cast<int>(v);
          n = std::min(n, s.points);
          std::string out;
          for (int i = 0; i < n; ++i) {
            const double x = s.out_fund() * std::sin(2.0 * 3.14159265358979 * s.freq * i / s.srate);
            char b[32];
            std::snprintf(b, sizeof b, "%.6g", x);
            out += (i ? "," : "") + std::string(b);
          }
          return Reply{out, false};
        }
        if (up.rfind("MF:ACQ:FFT?", 0) == 0) {
          const int nfft = s.points;
          const int bins = nfft / 2 + 1;
          std::string out = g9(s.srate) + "," + std::to_string(nfft);
          const int peak = static_cast<int>(std::lround(s.freq / (s.srate / nfft)));
          for (int k = 0; k < bins; ++k) {
            const double db = (k == peak) ? 20.0 * std::log10(std::max(s.out_fund(), 1e-9)) : -100.0 - 0.001 * k;
            out += "," + g9(db);
          }
          return Reply{out, false};
        }
        if (up.rfind("MEAS:", 0) == 0) {
          if (!s.stored) { s.stored = true; ++s.counter; }
          const bool tone_ok = s.output && s.function == "SIN";
          if (s.dut_nan) { push_err(s.errq_an, -230, "Data corrupt or stale"); return Reply{std::string("NAN"), true}; }
          if (up == "MEAS:RMS?") return Reply{g9(s.out_fund() / std::sqrt(2.0)), true};
          if (up == "MEAS:NOIS?") return Reply{g9(s.noise_inband()), true};
          if (up == "MEAS:FREQ?") return Reply{g9(s.freq), true};
          if (up == "MEAS:GAIN?" || up == "MEAS:THD?" || up == "MEAS:SNR?") {
            if (!tone_ok) { push_err(s.errq_an, -221, "Settings conflict"); return Reply{std::string("NAN"), true}; }
            if (up == "MEAS:GAIN?") return Reply{g9(20.0 * std::log10(s.out_fund() / s.amp)), true};
            if (up == "MEAS:THD?") return Reply{g9(s.thd_percent()), true};
            return Reply{g9(20.0 * std::log10(s.out_fund() / std::pow(10.0, s.noise_inband() / 20.0)) - 3.0), true};
          }
        }
        if (up == "MF:ANAL:WIN?") return Reply{std::string("FLATTOP"), false};
        push_err(s.errq_an, -113, "Undefined header");
        return Reply{};
      }),
      dut([this](const std::string& up, const std::string& raw) {
        std::lock_guard<std::mutex> lk(st_->mu);
        State& s = *st_;
        Reply r;
        if (common(up, s.errq_dut, "MeasureFlow,VDUT-HA1,SN-SIM-0003," + s.firmware, r, [&] { s.rst_dut(); })) return r;
        double v;
        if (up == "MF:DUT:PROF?") return Reply{s.profile, false};
        if (up.rfind("MF:DUT:PROF ", 0) == 0) {
          const std::string p = arg_text(up);
          if (p == "NORMAL" || p == "LOWGAIN" || p == "HIGHTHD" || p == "NOISY" || p == "CLIPPING") s.load_profile(p); else push_err(s.errq_dut, -224, "Illegal parameter value");
          return Reply{};
        }
        if (up.rfind("MF:DUT:FW ", 0) == 0) {
          const std::string f = arg_text(raw);
          if (f == "1.0.0" || f == "1.1.0" || f == "1.2.0") s.firmware = f; else push_err(s.errq_dut, -224, "Illegal parameter value");
          return Reply{};
        }
        if (up == "MF:DUT:FW?") return Reply{s.firmware, false};
        struct P { const char* cmd; double* field; double lo, hi; };
        const P ps[] = {{"MF:DUT:GAIN", &s.gain, -20, 60}, {"MF:DUT:HPF", &s.hpf, 20, 1000}, {"MF:DUT:LPF", &s.lpf, 1000, 20000},
                        {"MF:DUT:NOISE", &s.noise, -140, 0}, {"MF:DUT:HD2", &s.hd2, 0, 1}, {"MF:DUT:HD3", &s.hd3, 0, 1}, {"MF:DUT:CLIP", &s.clip, 0.01, 10}};
        for (const auto& p : ps) {
          if (up == std::string(p.cmd) + "?") return Reply{g9(*p.field), true};
          if (up.rfind(std::string(p.cmd) + " ", 0) == 0) {
            if (arg_number(raw, &v) && v >= p.lo && v <= p.hi) { *p.field = v; s.profile = "CUSTOM"; } else push_err(s.errq_dut, -222, "Data out of range");
            return Reply{};
          }
        }
        if (up.rfind("MF:DUT:FAULT ", 0) == 0) { s.dut_nan = arg_text(up) == "NAN"; return Reply{}; }
        if (up == "MF:DUT:CONF?") {
          return Reply{s.profile + "," + g9(s.gain) + "," + g9(s.hpf) + "," + g9(s.lpf) + "," + g9(s.noise) + "," + g9(s.hd2) + "," + g9(s.hd3) + "," + g9(s.clip) + "," + s.firmware, false};
        }
        push_err(s.errq_dut, -113, "Undefined header");
        return Reply{};
      }) {}

std::string FakeBench::instruments_json(int timeout_ms, int max_retries, int connect_timeout_ms) const {
  auto one = [&](const char* id, const char* name, const char* kind, uint16_t port) {
    std::ostringstream o;
    o << "{\"id\":\"" << id << "\",\"name\":\"" << name << "\",\"kind\":\"" << kind << "\",\"host\":\"127.0.0.1\",\"port\":" << port
      << ",\"timeout_ms\":" << timeout_ms << ",\"connect_timeout_ms\":" << connect_timeout_ms << ",\"max_retries\":" << max_retries << "}";
    return o.str();
  };
  return "{\"config_version\":\"1.0.0\",\"max_response_bytes\":1048576,\"instruments\":[" + one("siggen", "Fake Signal Generator", "signal_generator", siggen.port()) +
         "," + one("analyzer", "Fake Audio Analyzer", "audio_analyzer", analyzer.port()) + "," + one("dut", "Fake DUT", "device_under_test", dut.port()) + "]}";
}

bool FakeBench::output_on() const { std::lock_guard<std::mutex> lk(st_->mu); return st_->output; }
std::string FakeBench::dut_firmware() const { std::lock_guard<std::mutex> lk(st_->mu); return st_->firmware; }
std::string FakeBench::dut_profile() const { std::lock_guard<std::mutex> lk(st_->mu); return st_->profile; }
void FakeBench::set_dut_nan_fault(bool on) { std::lock_guard<std::mutex> lk(st_->mu); st_->dut_nan = on; }

// ------------------------------------------------------------------------------------------------ temp root

TempRoot::TempRoot(const std::string& instruments_json, bool copy_calibration) {
  namespace fs = std::filesystem;
  static std::atomic<int> counter{0};
  path_ = (fs::temp_directory_path() / ("mf-test-" + std::to_string(::getpid()) + "-" + std::to_string(counter++))).string();
  fs::create_directories(fs::path(path_) / "configs" / "sequences");
  fs::create_directories(fs::path(path_) / "results");
  fs::create_directories(fs::path(path_) / "reports");
  const fs::path repo = fs::path(MF_REPO_ROOT) / "configs";
  for (const auto& e : fs::directory_iterator(repo / "sequences")) {
    if (e.path().extension() == ".json") fs::copy_file(e.path(), fs::path(path_) / "configs" / "sequences" / e.path().filename());
  }
  if (copy_calibration) fs::copy_file(repo / "calibration.json", fs::path(path_) / "configs" / "calibration.json");
  write("configs/instruments.json", instruments_json);
}

TempRoot::~TempRoot() {
  std::error_code ec;
  std::filesystem::remove_all(path_, ec);
}

void TempRoot::write(const std::string& relative, const std::string& content) const {
  const auto p = std::filesystem::path(path_) / relative;
  std::filesystem::create_directories(p.parent_path());
  std::ofstream(p, std::ios::binary) << content;
}

std::string TempRoot::read(const std::string& relative) const {
  std::ifstream in(std::filesystem::path(path_) / relative, std::ios::binary);
  std::stringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

bool TempRoot::exists(const std::string& relative) const { return std::filesystem::exists(std::filesystem::path(path_) / relative); }

}  // namespace mftest
