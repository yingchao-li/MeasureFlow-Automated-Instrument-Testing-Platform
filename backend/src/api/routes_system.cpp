#include "measureflow/api/json_convert.hpp"
#include "measureflow/api/routes.hpp"
#include "measureflow/api/validation.hpp"
#include "measureflow/engine/serialize.hpp"

namespace mf {

using nlohmann::json;

void register_system_routes(Router& router, AppServices& svc) {
  router.add("GET", "/api/health", [&svc](const HttpRequest&, HttpResponse& res) { send_json(res, 200, health_to_json(svc.env.health())); });

  router.add("GET", "/api/environment", [&svc](const HttpRequest&, HttpResponse& res) {
    send_json(res, 200, environment_to_json(svc.env.environment()));
  });

  router.add("GET", "/api/logs", [&svc](const HttpRequest& req, HttpResponse& res) {
    LogQuery q;
    q.limit = static_cast<size_t>(query_int(req, "limit", 200, 1, 2000));
    const std::string level = query_string(req, "level");
    const std::string source = query_string(req, "source");
    require_one_of("level", level, {"debug", "info", "warn", "error"});
    require_one_of("source", source, {"api", "scpi", "engine", "env", "system"});
    if (!level.empty()) q.min_level = parse_log_level(level);
    q.source = source;
    q.since_seq = static_cast<uint64_t>(query_int(req, "since_seq", 0, 0, 1LL << 62));
    json logs = json::array();
    for (const auto& e : svc.logger.query(q)) logs.push_back(log_entry_to_json(e));
    send_json(res, 200, json{{"logs", logs}, {"last_seq", svc.logger.last_seq()}});
  });
}

}  // namespace mf
