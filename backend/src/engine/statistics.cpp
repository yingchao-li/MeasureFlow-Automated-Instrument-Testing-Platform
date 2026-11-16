#include "measureflow/engine/statistics.hpp"

#include <algorithm>
#include <cmath>

#include "measureflow/util/time.hpp"

namespace mf {

void RunningStats::add(double v) {
  ++n_;
  if (n_ == 1) {
    min_ = max_ = v;
  } else {
    min_ = std::min(min_, v);
    max_ = std::max(max_, v);
  }
  const double delta = v - mean_;
  mean_ += delta / n_;
  m2_ += delta * (v - mean_);
}

double RunningStats::stddev() const { return n_ < 2 ? 0.0 : std::sqrt(m2_ / (n_ - 1)); }

namespace {

struct Acc {
  ValueStats vs;
  RunningStats rs;
};

void add_task(Acc& a, const TaskResult& t) {
  if (t.status == Status::Cancelled) return;
  ++a.vs.count;
  if (t.status == Status::Pass) ++a.vs.pass;
  if (t.status == Status::Fail) ++a.vs.fail;
  if (t.status == Status::Error) ++a.vs.error;
  if (t.measured) {
    a.rs.add(t.measured->value);
    a.vs.unit = t.measured->unit;
  } else if (a.vs.unit.empty()) {
    a.vs.unit = t.limits.unit;
  }
}

ValueStats finish(Acc& a) {
  ValueStats v = a.vs;
  v.n_values = a.rs.count();
  v.mean = a.rs.mean();
  v.std = a.rs.stddev();
  v.min = a.rs.min();
  v.max = a.rs.max();
  return v;
}

}  // namespace

SummaryReport compute_summary(const std::vector<const RunRecord*>& runs_newest_first) {
  SummaryReport s;
  s.generated_at = iso_now();
  std::map<std::string, Acc> by_kind;
  std::map<std::string, std::map<std::string, Acc>> fw_kind;
  std::map<std::string, FirmwareStats> fw;
  std::map<std::string, int> reasons;
  std::vector<TrendPoint> trend;

  // oldest -> newest so the trend is chronological
  for (auto it = runs_newest_first.rbegin(); it != runs_newest_first.rend(); ++it) {
    const RunRecord& r = **it;
    ++s.runs_total;
    switch (r.status) {
      case Status::Pass: ++s.runs_pass; break;
      case Status::Fail: ++s.runs_fail; break;
      case Status::Error: ++s.runs_error; break;
      case Status::Cancelled: ++s.runs_cancelled; break;
      default: break;
    }
    for (const auto& t : r.tasks) {
      ++s.tasks_total;
      switch (t.status) {
        case Status::Pass: ++s.tasks_pass; break;
        case Status::Fail: ++s.tasks_fail; break;
        case Status::Error: ++s.tasks_error; break;
        case Status::Cancelled: ++s.tasks_cancelled; break;
        default: break;
      }
      add_task(by_kind[t.kind], t);
      auto& f = fw[t.dut_firmware];
      f.firmware = t.dut_firmware;
      if (t.status != Status::Cancelled) {
        ++f.tasks;
        if (t.status == Status::Pass) ++f.pass;
        if (t.status == Status::Fail) ++f.fail;
        if (t.status == Status::Error) ++f.error;
      }
      add_task(fw_kind[t.dut_firmware][t.kind], t);
      if ((t.status == Status::Fail || t.status == Status::Error) && !t.error_code.empty()) ++reasons[t.error_code];
      if (t.attempts > 1 && t.status != Status::Cancelled) {
        ++s.tasks_with_retry;
        if (t.status == Status::Error) ++s.unrecovered;
        else ++s.recovered;
      }
      if (t.measured) {
        TrendPoint p;
        p.timestamp = t.timestamp;
        p.run_id = t.run_id;
        p.kind = t.kind;
        p.value = t.measured->value;
        p.unit = t.measured->unit;
        p.status = to_string(t.status);
        p.firmware = t.dut_firmware;
        trend.push_back(std::move(p));
      }
    }
  }
  const int verdicts = s.tasks_pass + s.tasks_fail + s.tasks_error;
  s.pass_rate = verdicts > 0 ? static_cast<double>(s.tasks_pass) / verdicts : 0.0;
  for (auto& kv : by_kind) s.by_kind[kv.first] = finish(kv.second);
  for (auto& kv : fw) {
    FirmwareStats f = kv.second;
    f.pass_rate = f.tasks > 0 ? static_cast<double>(f.pass) / f.tasks : 0.0;
    for (auto& k : fw_kind[kv.first]) f.by_kind[k.first] = finish(k.second);
    s.by_firmware.push_back(std::move(f));
  }
  std::sort(s.by_firmware.begin(), s.by_firmware.end(), [](const FirmwareStats& a, const FirmwareStats& b) { return a.firmware < b.firmware; });
  for (const auto& kv : reasons) s.failure_reasons.emplace_back(kv.first, kv.second);
  std::sort(s.failure_reasons.begin(), s.failure_reasons.end(), [](const auto& a, const auto& b) {
    return a.second != b.second ? a.second > b.second : a.first < b.first;
  });
  s.recovery_rate = s.tasks_with_retry > 0 ? static_cast<double>(s.recovered) / s.tasks_with_retry : 0.0;
  if (trend.size() > 500) trend.erase(trend.begin(), trend.begin() + static_cast<std::ptrdiff_t>(trend.size() - 500));
  s.trend = std::move(trend);
  return s;
}

}  // namespace mf
