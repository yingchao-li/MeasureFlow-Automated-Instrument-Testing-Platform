#include "measureflow/api/api_server.hpp"

#include <algorithm>
#include <atomic>
#include <set>
#include <thread>

#include "httplib.h"
#include "measureflow/api/api_errors.hpp"
#include "measureflow/api/static_files.hpp"
#include "measureflow/instruments/instrument_types.hpp"
#include "measureflow/util/strings.hpp"
#include "measureflow/util/time.hpp"

namespace mf {

struct ApiServer::Impl {
  Impl(AppServices s, ApiOptions o) : svc(s), opts(std::move(o)), files(opts.frontend_dist) {}

  AppServices svc;
  ApiOptions opts;
  Router router;
  StaticFiles files;
  httplib::Server server;
  int bound_port = 0;
  std::thread thread;
  std::atomic<bool> serving{false};

  std::set<std::string> origins() const {
    std::set<std::string> s(opts.allowed_origins.begin(), opts.allowed_origins.end());
    if (bound_port > 0) {
      s.insert("http://127.0.0.1:" + std::to_string(bound_port));
      s.insert("http://localhost:" + std::to_string(bound_port));
      s.insert("http://[::1]:" + std::to_string(bound_port));
    }
    return s;
  }

  static std::string host_name_of(const std::string& host_header) {
    std::string h = host_header;
    if (!h.empty() && h[0] == '[') {
      const size_t e = h.find(']');
      return e == std::string::npos ? h : h.substr(0, e + 1);
    }
    const size_t colon = h.rfind(':');
    if (colon != std::string::npos) h = h.substr(0, colon);
    return h;
  }

  void add_cors(const httplib::Request& req, httplib::Response& res) const {
    const std::string origin = req.get_header_value("Origin");
    if (origin.empty()) return;
    const bool cross_site_allowed = std::find(opts.allowed_origins.begin(), opts.allowed_origins.end(), origin) != opts.allowed_origins.end();
    if (!cross_site_allowed && !origins().count(origin)) return;
    res.set_header("Access-Control-Allow-Origin", origin);
    res.set_header("Vary", "Origin");
    res.set_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    res.set_header("Access-Control-Allow-Headers", "Content-Type");
    res.set_header("Access-Control-Max-Age", "600");
  }

  void copy_out(const HttpResponse& out, httplib::Response& res) const {
    res.status = out.status;
    for (const auto& kv : out.headers) res.set_header(kv.first, kv.second);
    if (!res.has_header("X-Content-Type-Options")) res.set_header("X-Content-Type-Options", "nosniff");
    if (out.content_type.find("json") != std::string::npos) res.set_header("Cache-Control", "no-store");
    res.set_content(out.body, out.content_type);
  }

  void handle(const httplib::Request& req, httplib::Response& res) {
    Stopwatch sw;
    HttpResponse out;
    const bool is_api = req.path == "/api" || starts_with(req.path, "/api/");

    // DNS-rebinding guard: only loopback host names are served.
    if (!opts.unsafe_bind && req.has_header("Host") && !is_loopback_host(host_name_of(req.get_header_value("Host")))) {
      write_plain_error(out, 403, ErrorCode::ForbiddenHost, "Host header '" + req.get_header_value("Host") + "' is not a loopback address");
      finish(req, res, out, sw);
      return;
    }
    // Cross-site protection: a browser page from another origin may not drive the instruments.
    const std::string origin = req.get_header_value("Origin");
    const bool mutating = req.method != "GET" && req.method != "HEAD";
    if (!origin.empty() && (mutating || req.method == "OPTIONS")) {
      const auto allowed = origins();
      if (!allowed.count(origin)) {
        write_plain_error(out, 403, ErrorCode::ForbiddenHost, "origin '" + origin + "' is not allowed");
        finish(req, res, out, sw);
        return;
      }
    }
    if (req.method == "OPTIONS") {
      out.status = 204;
      out.body.clear();
      finish(req, res, out, sw);
      return;
    }

    HttpRequest hr;
    hr.method = req.method == "HEAD" ? "GET" : req.method;
    hr.path = req.path;
    hr.body = req.body;
    for (const auto& kv : req.headers) hr.headers[to_lower(kv.first)] = kv.second;
    for (const auto& kv : req.params) hr.query.emplace(kv.first, kv.second);

    if (is_api) {
      const auto d = router.dispatch(hr, out);
      if (d.result == Router::Result::NotFound) {
        write_plain_error(out, 404, ErrorCode::NotFound, "unknown endpoint " + req.method + " " + req.path);
      } else if (d.result == Router::Result::MethodNotAllowed) {
        std::string allow;
        for (const auto& m : d.allowed) allow += (allow.empty() ? "" : ", ") + m;
        write_plain_error(out, 405, ErrorCode::InvalidArgument, "method " + req.method + " not allowed for " + req.path + " (allowed: " + allow + ")");
        out.headers["Allow"] = allow;
      }
    } else if (req.method == "GET" || req.method == "HEAD") {
      switch (files.serve(req.path, out)) {
        case StaticFiles::Outcome::Served: break;
        case StaticFiles::Outcome::Rejected: write_plain_error(out, 400, ErrorCode::InvalidArgument, "invalid path"); break;
        case StaticFiles::Outcome::Unavailable:
          write_plain_error(out, 404, ErrorCode::NotFound, "the frontend is not built (run 'npm run build' in frontend/); the REST API is available under /api");
          break;
        case StaticFiles::Outcome::NotFound: write_plain_error(out, 404, ErrorCode::NotFound, "file not found"); break;
      }
    } else {
      write_plain_error(out, 405, ErrorCode::InvalidArgument, "method " + req.method + " not allowed for " + req.path);
      out.headers["Allow"] = "GET, HEAD";
    }
    finish(req, res, out, sw);
  }

  void finish(const httplib::Request& req, httplib::Response& res, const HttpResponse& out, const Stopwatch& sw) {
    copy_out(out, res);
    add_cors(req, res);
    const bool api = starts_with(req.path, "/api");
    const LogLevel lv = out.status >= 500 ? LogLevel::Error : (out.status >= 400 ? LogLevel::Warn : (req.method == "GET" ? LogLevel::Debug : LogLevel::Info));
    if (api || out.status >= 400) {
      svc.logger.log(lv, "api", req.method + " " + req.path + " -> " + std::to_string(out.status),
                     {{"method", req.method}, {"path", req.path}, {"status", static_cast<int64_t>(out.status)}, {"duration_ms", sw.elapsed_ms()}});
    }
  }
};

ApiServer::ApiServer(AppServices services, ApiOptions options) : impl_(std::make_unique<Impl>(services, std::move(options))) {
  Impl* p = impl_.get();
  register_all_routes(p->router, p->svc);
  httplib::Server& s = p->server;
  s.set_payload_max_length(p->opts.max_body_bytes);
  s.set_read_timeout(10, 0);
  s.set_write_timeout(10, 0);
  s.set_keep_alive_max_count(50);
  s.set_keep_alive_timeout(2);
  // Without TCP_NODELAY the header/body writes interact with the client's delayed ACK and add ~40 ms to every response.
  s.set_tcp_nodelay(true);
  const int threads = std::max(4, p->opts.worker_threads);
  s.new_task_queue = [threads] { return new httplib::ThreadPool(static_cast<size_t>(threads)); };

  auto h = [p](const httplib::Request& req, httplib::Response& res) { p->handle(req, res); };
  s.Get(".*", h);
  s.Post(".*", h);
  s.Put(".*", h);
  s.Delete(".*", h);
  s.Patch(".*", h);
  s.Options(".*", h);

  s.set_exception_handler([p](const httplib::Request& req, httplib::Response& res, std::exception_ptr ep) {
    HttpResponse out;
    write_exception(out, ep);
    p->copy_out(out, res);
    p->add_cors(req, res);
  });
  // Errors raised by httplib itself (oversized body, malformed request line, ...) get the unified body too.
  s.set_error_handler([p](const httplib::Request& req, httplib::Response& res) {
    if (!res.body.empty()) return;
    HttpResponse out;
    std::string msg = "request failed";
    ErrorCode code = ErrorCode::InvalidArgument;
    switch (res.status) {
      case 413: msg = "request body too large (limit " + std::to_string(p->opts.max_body_bytes) + " bytes)"; break;
      case 414: msg = "request URI too long"; break;
      case 404: msg = "not found"; code = ErrorCode::NotFound; break;
      case 405: msg = "method not allowed"; break;
      case 400: msg = "bad request"; break;
      default:
        if (res.status >= 500) {
          code = ErrorCode::Internal;
          msg = "server error";
        }
    }
    write_plain_error(out, res.status, code, msg);
    p->copy_out(out, res);
    p->add_cors(req, res);
  });
}

ApiServer::~ApiServer() { stop(); }

int ApiServer::bind() {
  Impl& i = *impl_;
  if (!i.opts.unsafe_bind) require_loopback(i.opts.host);
  int port = i.opts.port;
  if (port == 0) {
    port = i.server.bind_to_any_port(i.opts.host);
  } else if (!i.server.bind_to_port(i.opts.host, port)) {
    port = -1;
  }
  if (port <= 0) throw std::runtime_error("cannot bind " + i.opts.host + ":" + std::to_string(i.opts.port) + " (address in use?)");
  i.bound_port = port;
  return port;
}

void ApiServer::serve() {
  impl_->serving = true;
  impl_->server.listen_after_bind();
  impl_->serving = false;
}

int ApiServer::start_in_background() {
  const int port = bind();
  impl_->thread = std::thread([this] { serve(); });
  impl_->server.wait_until_ready();
  return port;
}

void ApiServer::stop() {
  if (!impl_) return;
  impl_->server.stop();
  if (impl_->thread.joinable()) impl_->thread.join();
}

int ApiServer::port() const { return impl_->bound_port; }

}  // namespace mf
