#include "measureflow/api/json_convert.hpp"
#include "measureflow/api/routes.hpp"
#include "measureflow/api/validation.hpp"
#include "measureflow/engine/serialize.hpp"
#include "measureflow/util/strings.hpp"

namespace mf {

using nlohmann::json;

namespace {

json sequence_to_json(const SequenceDef& s) {
  json params = json::array();
  std::map<std::string, double> defaults;
  for (const auto& p : s.parameters) {
    defaults[p.key] = p.def;
    params.push_back(json{{"key", p.key}, {"label", p.label}, {"unit", p.unit}, {"default", p.def}, {"min", p.min}, {"max", p.max}});
  }
  json steps = json::array();
  for (const auto& st : s.steps) steps.push_back(json{{"id", st.id}, {"type", to_string(st.type)}, {"name", render_template(st.name, defaults)}});
  return json{{"id", s.id},
              {"name", s.name},
              {"version", s.version},
              {"description", s.description},
              {"parameters", params},
              {"dut", json{{"profile", s.dut.profile}, {"firmware", s.dut.firmware}}},
              {"steps", steps}};
}

void require_valid_run_id(const std::string& id, const char* field) {
  if (!is_valid_id(id)) throw MfError(ErrorCode::InvalidArgument, std::string(field) + " must match ^[A-Za-z0-9._-]{1,64}$", field);
}

}  // namespace

void register_test_routes(Router& router, AppServices& svc) {
  router.add("GET", "/api/sequences", [&svc](const HttpRequest&, HttpResponse& res) {
    json a = json::array();
    for (const auto* s : svc.sequences.list()) a.push_back(sequence_to_json(*s));
    send_json(res, 200, json{{"sequences", a}});
  });

  router.add("POST", "/api/tests/run", [&svc](const HttpRequest& req, HttpResponse& res) {
    BodyReader b(req);
    RunRequest rr;
    rr.sequence_id = b.req_string("sequence_id", 1, 64);
    const json* params = b.opt_object("parameters");
    const json* dut = b.opt_object("dut");
    const auto retries = b.opt_int("retries", 0, 5);
    const auto label = b.opt_string("label", 0, 64);
    b.finish();
    if (params) {
      for (auto it = params->begin(); it != params->end(); ++it) {
        if (!it.value().is_number()) throw MfError(ErrorCode::InvalidArgument, "parameter '" + it.key() + "' must be a number", "parameters." + it.key());
        rr.parameters[it.key()] = it.value().get<double>();
      }
    }
    if (dut) {
      for (auto it = dut->begin(); it != dut->end(); ++it) {
        if (it.key() != "profile" && it.key() != "firmware") throw MfError(ErrorCode::InvalidArgument, "unknown field 'dut." + it.key() + "'", "dut." + it.key());
        if (!it.value().is_string()) throw MfError(ErrorCode::InvalidArgument, "dut." + it.key() + " must be a string", "dut." + it.key());
      }
      if (dut->contains("profile")) rr.dut_profile = (*dut)["profile"].get<std::string>();
      if (dut->contains("firmware")) rr.dut_firmware = (*dut)["firmware"].get<std::string>();
    }
    if (retries) rr.retries = static_cast<int>(*retries);
    if (label) rr.label = *label;
    const RunRecord rec = svc.runner.start(rr);
    send_json(res, 202, json{{"run", run_summary_to_json(rec)}});
  });

  router.add("POST", "/api/tests/cancel", [&svc](const HttpRequest& req, HttpResponse& res) {
    BodyReader b(req, true);
    const auto run_id = b.opt_string("run_id", 0, 64);
    b.finish();
    if (run_id && !run_id->empty()) require_valid_run_id(*run_id, "run_id");
    const RunRecord rec = svc.runner.cancel(run_id ? *run_id : std::string());
    send_json(res, 200, json{{"run", run_summary_to_json(rec)}});
  });

  router.add("GET", "/api/tests/status", [&svc](const HttpRequest& req, HttpResponse& res) {
    const std::string run_id = query_string(req, "run_id");
    if (!run_id.empty()) require_valid_run_id(run_id, "run_id");
    const size_t tail = static_cast<size_t>(query_int(req, "log_tail", 100, 0, 1000));
    auto rec = svc.runner.status(run_id, tail == 0 ? 1 : tail);
    if (!rec) {
      if (!run_id.empty()) throw MfError(ErrorCode::NotFound, "unknown run '" + run_id + "'", "run_id");
      send_json(res, 200, json{{"run", nullptr}});
      return;
    }
    if (tail == 0) rec->log.clear();
    send_json(res, 200, json{{"run", run_detail_to_json(*rec, 0)}});
  });

  router.add("GET", "/api/tests/results", [&svc](const HttpRequest& req, HttpResponse& res) {
    TaskFilter f;
    f.limit = static_cast<size_t>(query_int(req, "limit", 100, 1, 1000));
    f.offset = static_cast<size_t>(query_int(req, "offset", 0, 0, 1000000000));
    f.run_id = query_string(req, "run_id");
    f.sequence_id = query_string(req, "sequence_id");
    f.status = query_string(req, "status");
    f.kind = query_string(req, "kind");
    f.firmware = query_string(req, "firmware");
    f.profile = query_string(req, "profile");
    require_one_of("status", f.status, {"PASS", "FAIL", "ERROR", "CANCELLED"});
    require_one_of("kind", f.kind, {"rms", "gain", "thd", "snr", "noise_floor", "freq_sweep"});
    if (!f.run_id.empty()) require_valid_run_id(f.run_id, "run_id");
    if (!f.sequence_id.empty()) require_valid_run_id(f.sequence_id, "sequence_id");
    const TaskPage page = svc.store.query_tasks(f);
    json results = json::array();
    for (const auto& t : page.tasks) results.push_back(task_to_json(t));
    send_json(res, 200, json{{"total", page.total}, {"limit", f.limit}, {"offset", f.offset}, {"results", results}});
  });

  router.add("GET", "/api/tests/runs", [&svc](const HttpRequest& req, HttpResponse& res) {
    RunFilter f;
    f.limit = static_cast<size_t>(query_int(req, "limit", 50, 1, 1000));
    f.offset = static_cast<size_t>(query_int(req, "offset", 0, 0, 1000000000));
    f.status = query_string(req, "status");
    f.sequence_id = query_string(req, "sequence_id");
    require_one_of("status", f.status, {"PASS", "FAIL", "ERROR", "CANCELLED"});
    if (!f.sequence_id.empty()) require_valid_run_id(f.sequence_id, "sequence_id");
    const RunPage page = svc.store.list_runs(f);
    json runs = json::array();
    for (const auto& r : page.runs) runs.push_back(run_summary_to_json(r));
    send_json(res, 200, json{{"total", page.total}, {"limit", f.limit}, {"offset", f.offset}, {"runs", runs}});
  });
}

}  // namespace mf
