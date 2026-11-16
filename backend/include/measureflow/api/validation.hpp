// Strict request validation helpers (include only from api sources: pulls in json.hpp).
#pragma once

#include <optional>
#include <set>
#include <string>

#include "json.hpp"
#include "measureflow/api/http_types.hpp"
#include "measureflow/util/errors.hpp"

namespace mf {

// Parses the body as a JSON object and tracks which keys were consumed; finish() rejects unknown keys.
class BodyReader {
 public:
  // allow_empty: an empty body is treated as {}.
  explicit BodyReader(const HttpRequest& req, bool allow_empty = false);

  bool has(const std::string& key) const { return obj_.contains(key) && !obj_.at(key).is_null(); }
  std::string req_string(const std::string& key, size_t min_len, size_t max_len);
  std::optional<std::string> opt_string(const std::string& key, size_t min_len, size_t max_len);
  std::optional<double> opt_number(const std::string& key, double lo, double hi);
  std::optional<long long> opt_int(const std::string& key, long long lo, long long hi);
  std::optional<bool> opt_bool(const std::string& key);
  // Returns the object (marks the key as consumed) or nullptr when absent/null; throws when not an object.
  const nlohmann::json* opt_object(const std::string& key);
  const nlohmann::json& root() const { return obj_; }
  void finish();  // throws INVALID_ARGUMENT naming the first unknown key

 private:
  nlohmann::json obj_;
  std::set<std::string> used_;
};

// Query-string helpers. Absent -> default. Present but malformed/out of range -> INVALID_ARGUMENT.
long long query_int(const HttpRequest& req, const std::string& key, long long def, long long lo, long long hi);
std::string query_string(const HttpRequest& req, const std::string& key, size_t max_len = 64);
// Throws unless `value` is empty or one of `allowed`.
void require_one_of(const std::string& field, const std::string& value, const std::set<std::string>& allowed);

nlohmann::json ok_json(const HttpRequest&, nlohmann::json body);
void send_json(HttpResponse& res, int status, const nlohmann::json& body);

}  // namespace mf
