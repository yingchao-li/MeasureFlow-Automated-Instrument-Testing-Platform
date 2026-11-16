#include "measureflow/api/json_convert.hpp"
#include "measureflow/api/routes.hpp"
#include "measureflow/api/validation.hpp"
#include "measureflow/engine/serialize.hpp"
#include "measureflow/util/strings.hpp"

namespace mf {

using nlohmann::json;

void register_report_routes(Router& router, AppServices& svc) {
  router.add("GET", "/api/reports", [&svc](const HttpRequest&, HttpResponse& res) {
    json list = json::array();
    for (const auto& r : svc.reports.list(500)) {
      const std::string base = "/api/reports/" + r.run_id;
      list.push_back(json{{"run_id", r.run_id},
                          {"sequence_id", r.sequence_id},
                          {"sequence_name", r.sequence_name},
                          {"status", to_string(r.status)},
                          {"created_at", r.created_at},
                          {"counts", counts_to_json(count_tasks(r))},
                          {"files", json{{"csv", base + ".csv"}, {"html", base + ".html"}, {"pdf", base + ".pdf"}}}});
    }
    send_json(res, 200, json{{"reports", list}});
  });

  router.add("GET", "/api/reports/summary", [&svc](const HttpRequest& req, HttpResponse& res) {
    const std::string seq = query_string(req, "sequence_id");
    if (!seq.empty() && !is_valid_id(seq)) throw MfError(ErrorCode::InvalidArgument, "sequence_id must match ^[A-Za-z0-9._-]{1,64}$", "sequence_id");
    const size_t limit = static_cast<size_t>(query_int(req, "limit", 1000, 1, 100000));
    send_json(res, 200, summary_to_json(svc.store.summary(seq, limit)));
  });

  router.add("GET", "/api/reports/{file}", [&svc](const HttpRequest& req, HttpResponse& res) {
    const std::string file = req.params.at("file");
    const size_t dot = file.rfind('.');
    if (dot == std::string::npos || dot == 0) throw MfError(ErrorCode::NotFound, "report not found (expected <run_id>.csv|html|pdf)", "run_id");
    const std::string run_id = file.substr(0, dot);
    const std::string ext = file.substr(dot + 1);
    if (!is_valid_id(run_id)) throw MfError(ErrorCode::InvalidArgument, "run_id must match ^[A-Za-z0-9._-]{1,64}$", "run_id");
    if (ext != "csv" && ext != "html" && ext != "pdf") throw MfError(ErrorCode::NotFound, "unknown report format '" + ext + "'", "format");
    auto f = svc.reports.fetch(run_id, ext);
    if (!f) throw MfError(ErrorCode::NotFound, "no report for run '" + run_id + "'", "run_id");
    res.status = 200;
    res.content_type = f->content_type;
    res.body = std::move(f->content);
    res.headers["Content-Disposition"] = "attachment; filename=\"" + f->filename + "\"";
  });
}

}  // namespace mf
