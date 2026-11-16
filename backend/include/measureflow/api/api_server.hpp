// REST server (cpp-httplib adapter): host/origin guards, CORS for the Vite origins, strict body limits,
// unified error bodies, static frontend serving, SPA fallback.
#pragma once

#include <filesystem>
#include <memory>
#include <string>
#include <vector>

#include "measureflow/api/routes.hpp"

namespace mf {

struct ApiOptions {
  std::string host = "127.0.0.1";
  int port = 8080;                     // 0 = pick a free port (tests)
  bool unsafe_bind = false;            // allow non-loopback bind addresses / Host headers
  size_t max_body_bytes = 64 * 1024;   // larger bodies are rejected (HTTP 413)
  std::filesystem::path frontend_dist;
  std::vector<std::string> allowed_origins = {"http://127.0.0.1:5173", "http://localhost:5173"};
  int worker_threads = 16;
};

class ApiServer {
 public:
  ApiServer(AppServices services, ApiOptions options);
  ~ApiServer();
  ApiServer(const ApiServer&) = delete;
  ApiServer& operator=(const ApiServer&) = delete;

  // Binds the listening socket and returns the bound port. Throws MfError(ForbiddenHost) for a non-loopback
  // address without unsafe_bind and std::runtime_error when the port cannot be bound.
  int bind();
  // Blocks serving requests until stop() is called (bind() must have succeeded).
  void serve();
  // bind() + serve() on a background thread; returns once the server accepts connections.
  int start_in_background();
  void stop();
  int port() const;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace mf
