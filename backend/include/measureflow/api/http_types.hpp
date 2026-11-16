// Transport-independent HTTP model + router. Handlers are written against these types so they can be unit-tested
// without sockets; only api_server.cpp includes httplib.h.
#pragma once

#include <functional>
#include <map>
#include <string>
#include <vector>

namespace mf {

struct HttpRequest {
  std::string method;  // upper case
  std::string path;    // percent-decoded, without query string
  std::map<std::string, std::string> query;
  std::map<std::string, std::string> headers;  // lower-case names
  std::string body;
  std::map<std::string, std::string> params;   // path parameters ({name})

  std::string header(const std::string& lower_name) const {
    const auto it = headers.find(lower_name);
    return it == headers.end() ? std::string() : it->second;
  }
};

struct HttpResponse {
  int status = 200;
  std::string body;
  std::string content_type = "application/json";
  std::map<std::string, std::string> headers;
};

using Handler = std::function<void(const HttpRequest&, HttpResponse&)>;

class Router {
 public:
  // Pattern segments: literal text or "{name}" (matches exactly one non-empty segment).
  void add(const std::string& method, const std::string& pattern, Handler handler);

  enum class Result { Handled, NotFound, MethodNotAllowed };
  struct Dispatch {
    Result result = Result::NotFound;
    std::vector<std::string> allowed;  // for MethodNotAllowed
  };
  // Runs the matching handler (exceptions are converted to the unified error body).
  Dispatch dispatch(HttpRequest& req, HttpResponse& res) const;
  bool has_route(const std::string& path) const;

 private:
  struct Route {
    std::string method;
    std::vector<std::string> segments;
    Handler handler;
  };
  static bool match(const std::vector<std::string>& pattern, const std::vector<std::string>& parts,
                    std::map<std::string, std::string>* params);
  std::vector<Route> routes_;
};

}  // namespace mf
