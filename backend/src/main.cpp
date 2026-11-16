// MeasureFlow backend entry point.
#include <signal.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <string>
#include <thread>

#include "measureflow/app/application.hpp"
#include "measureflow/util/errors.hpp"
#include "measureflow/util/strings.hpp"

namespace {

volatile sig_atomic_t g_stop = 0;

extern "C" void on_signal(int) { g_stop = 1; }

void usage(const char* argv0) {
  std::printf(
      "MeasureFlow backend %s\n"
      "Usage: %s [options]\n"
      "  --root <dir>        repository root containing configs/, results/, reports/, frontend/dist (default: auto-detect)\n"
      "  --port <n>          REST port (default 8080)\n"
      "  --host <addr>       bind address (default 127.0.0.1; loopback only unless --unsafe-bind)\n"
      "  --unsafe-bind       allow binding a non-loopback address (NOT recommended: no authentication)\n"
      "  --log-level <lvl>   debug | info | warn | error (default info)\n"
      "  --help, --version\n",
      MF_VERSION, argv0);
}

std::filesystem::path detect_root() {
  namespace fs = std::filesystem;
  fs::path p = fs::current_path();
  for (int i = 0; i < 4; ++i) {
    if (fs::exists(p / "configs" / "instruments.json")) return p;
    if (!p.has_parent_path() || p.parent_path() == p) break;
    p = p.parent_path();
  }
  return fs::current_path();
}

}  // namespace

int main(int argc, char** argv) {
  mf::AppOptions opt;
  bool root_given = false;
  for (int i = 1; i < argc; ++i) {
    const std::string a = argv[i];
    auto need = [&](const char* name) -> std::string {
      if (i + 1 >= argc) {
        std::fprintf(stderr, "error: %s requires a value\n", name);
        std::exit(2);
      }
      return argv[++i];
    };
    if (a == "--help" || a == "-h") {
      usage(argv[0]);
      return 0;
    } else if (a == "--version") {
      std::printf("measureflow_backend %s\n", MF_VERSION);
      return 0;
    } else if (a == "--root") {
      opt.root = need("--root");
      root_given = true;
    } else if (a == "--port") {
      const auto v = mf::parse_int_strict(need("--port"), 0, 65535);
      if (!v) {
        std::fprintf(stderr, "error: --port must be an integer in [0, 65535]\n");
        return 2;
      }
      opt.port = static_cast<int>(*v);
    } else if (a == "--host") {
      opt.host = need("--host");
    } else if (a == "--unsafe-bind") {
      opt.unsafe_bind = true;
    } else if (a == "--log-level") {
      const auto lv = mf::parse_log_level(need("--log-level"));
      if (!lv) {
        std::fprintf(stderr, "error: --log-level must be debug, info, warn or error\n");
        return 2;
      }
      opt.log_level = *lv;
    } else {
      std::fprintf(stderr, "error: unknown option '%s' (try --help)\n", a.c_str());
      return 2;
    }
  }
  if (!root_given) opt.root = detect_root();
  opt.root = std::filesystem::absolute(opt.root).lexically_normal();
  opt.stderr_log = true;

  struct sigaction sa;
  sa.sa_handler = on_signal;
  sigemptyset(&sa.sa_mask);
  sa.sa_flags = 0;
  sigaction(SIGINT, &sa, nullptr);
  sigaction(SIGTERM, &sa, nullptr);
  signal(SIGPIPE, SIG_IGN);

  try {
    mf::Application app(opt);
    const int port = app.start();
    std::printf("READY measureflow_backend %s listening on http://%s:%d (root %s)\n", MF_VERSION, opt.host.c_str(), port, opt.root.c_str());
    std::fflush(stdout);
    while (!g_stop) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    std::fprintf(stderr, "signal received: shutting down\n");
    app.shutdown();
    return 0;
  } catch (const mf::MfError& e) {
    std::fprintf(stderr, "error: %s\n", e.what());
    return 2;
  } catch (const std::exception& e) {
    std::fprintf(stderr, "error: %s\n", e.what());
    return 1;
  }
}
