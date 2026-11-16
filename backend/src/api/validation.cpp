#include "measureflow/api/validation.hpp"

#include <cmath>

#include "measureflow/util/strings.hpp"

namespace mf {

using nlohmann::json;

namespace {
[[noreturn]] void invalid(const std::string& msg, const std::string& field = {}) { throw MfError(ErrorCode::InvalidArgument, msg, field); }
}  // namespace

BodyReader::BodyReader(const HttpRequest& req, bool allow_empty) {
  if (trim(req.body).empty()) {
    if (!allow_empty) invalid("request body must be a JSON object");
    obj_ = json::object();
    return;
  }
  obj_ = json::parse(req.body, nullptr, false);
  if (obj_.is_discarded()) invalid("malformed JSON in request body");
  if (!obj_.is_object()) invalid("request body must be a JSON object");
}

std::string BodyReader::req_string(const std::string& key, size_t min_len, size_t max_len) {
  auto v = opt_string(key, min_len, max_len);
  if (!v) invalid("missing required field '" + key + "'", key);
  return *v;
}

std::optional<std::string> BodyReader::opt_string(const std::string& key, size_t min_len, size_t max_len) {
  used_.insert(key);
  if (!has(key)) return std::nullopt;
  const json& v = obj_.at(key);
  if (!v.is_string()) invalid(key + " must be a string", key);
  std::string s = v.get<std::string>();
  if (s.size() < min_len || s.size() > max_len) {
    invalid(key + " must be " + std::to_string(min_len) + " to " + std::to_string(max_len) + " characters long", key);
  }
  return s;
}

std::optional<double> BodyReader::opt_number(const std::string& key, double lo, double hi) {
  used_.insert(key);
  if (!has(key)) return std::nullopt;
  const json& v = obj_.at(key);
  if (!v.is_number()) invalid(key + " must be a number", key);
  const double d = v.get<double>();
  if (!std::isfinite(d) || d < lo || d > hi) invalid(key + " must be within [" + format_g(lo, 9) + ", " + format_g(hi, 9) + "]", key);
  return d;
}

std::optional<long long> BodyReader::opt_int(const std::string& key, long long lo, long long hi) {
  used_.insert(key);
  if (!has(key)) return std::nullopt;
  const json& v = obj_.at(key);
  if (!v.is_number_integer()) invalid(key + " must be an integer", key);
  const long long d = v.get<long long>();
  if (d < lo || d > hi) invalid(key + " must be within [" + std::to_string(lo) + ", " + std::to_string(hi) + "]", key);
  return d;
}

std::optional<bool> BodyReader::opt_bool(const std::string& key) {
  used_.insert(key);
  if (!has(key)) return std::nullopt;
  const json& v = obj_.at(key);
  if (!v.is_boolean()) invalid(key + " must be a boolean", key);
  return v.get<bool>();
}

const json* BodyReader::opt_object(const std::string& key) {
  used_.insert(key);
  if (!has(key)) return nullptr;
  const json& v = obj_.at(key);
  if (!v.is_object()) invalid(key + " must be an object", key);
  return &v;
}

void BodyReader::finish() {
  for (auto it = obj_.begin(); it != obj_.end(); ++it) {
    if (!used_.count(it.key())) invalid("unknown field '" + it.key() + "'", it.key());
  }
}

long long query_int(const HttpRequest& req, const std::string& key, long long def, long long lo, long long hi) {
  const auto it = req.query.find(key);
  if (it == req.query.end() || it->second.empty()) return def;
  const auto v = parse_int_strict(it->second, lo, hi);
  if (!v) invalid("query parameter '" + key + "' must be an integer within [" + std::to_string(lo) + ", " + std::to_string(hi) + "]", key);
  return *v;
}

std::string query_string(const HttpRequest& req, const std::string& key, size_t max_len) {
  const auto it = req.query.find(key);
  if (it == req.query.end()) return {};
  if (it->second.size() > max_len) invalid("query parameter '" + key + "' is too long", key);
  return it->second;
}

void require_one_of(const std::string& field, const std::string& value, const std::set<std::string>& allowed) {
  if (value.empty() || allowed.count(value)) return;
  std::string list;
  for (const auto& a : allowed) list += (list.empty() ? "" : ", ") + a;
  invalid("query parameter '" + field + "' must be one of: " + list, field);
}

json ok_json(const HttpRequest&, json body) { return body; }

void send_json(HttpResponse& res, int status, const json& body) {
  res.status = status;
  res.content_type = "application/json";
  res.body = body.dump(-1, ' ', false, json::error_handler_t::replace);
}

}  // namespace mf
