#include <algorithm>

#include "measureflow/api/api_errors.hpp"
#include "measureflow/api/http_types.hpp"
#include "measureflow/util/strings.hpp"

namespace mf {

namespace {
std::vector<std::string> split_path(const std::string& path) {
  std::vector<std::string> out;
  size_t i = 0;
  while (i < path.size()) {
    if (path[i] == '/') {
      ++i;
      continue;
    }
    const size_t j = path.find('/', i);
    out.push_back(path.substr(i, j == std::string::npos ? std::string::npos : j - i));
    if (j == std::string::npos) break;
    i = j;
  }
  return out;
}
}  // namespace

void Router::add(const std::string& method, const std::string& pattern, Handler handler) {
  routes_.push_back(Route{method, split_path(pattern), std::move(handler)});
}

bool Router::match(const std::vector<std::string>& pattern, const std::vector<std::string>& parts,
                   std::map<std::string, std::string>* params) {
  if (pattern.size() != parts.size()) return false;
  for (size_t i = 0; i < pattern.size(); ++i) {
    const std::string& p = pattern[i];
    if (p.size() > 2 && p.front() == '{' && p.back() == '}') {
      if (parts[i].empty()) return false;
      if (params) (*params)[p.substr(1, p.size() - 2)] = parts[i];
    } else if (p != parts[i]) {
      return false;
    }
  }
  return true;
}

bool Router::has_route(const std::string& path) const {
  const auto parts = split_path(path);
  return std::any_of(routes_.begin(), routes_.end(), [&](const Route& r) { return match(r.segments, parts, nullptr); });
}

Router::Dispatch Router::dispatch(HttpRequest& req, HttpResponse& res) const {
  Dispatch d;
  const auto parts = split_path(req.path);
  for (const auto& r : routes_) {
    std::map<std::string, std::string> params;
    if (!match(r.segments, parts, &params)) continue;
    d.allowed.push_back(r.method);
    if (r.method != req.method) continue;
    req.params = std::move(params);
    try {
      r.handler(req, res);
    } catch (...) {
      res = HttpResponse{};
      write_exception(res, std::current_exception());
    }
    d.result = Result::Handled;
    d.allowed.clear();
    return d;
  }
  d.result = d.allowed.empty() ? Result::NotFound : Result::MethodNotAllowed;
  return d;
}

}  // namespace mf
