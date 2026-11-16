#include "measureflow/engine/result_store.hpp"

#include <algorithm>

#include "json.hpp"
#include "measureflow/engine/serialize.hpp"
#include "measureflow/report/csv_report.hpp"
#include "measureflow/util/fs.hpp"
#include "measureflow/util/strings.hpp"
#include "measureflow/util/time.hpp"

namespace mf {

namespace {
bool newer(const RunRecord& a, const RunRecord& b) {
  if (a.created_at != b.created_at) return a.created_at > b.created_at;
  return a.run_id > b.run_id;
}

std::string run_log_text(const RunRecord& run) {
  std::string out;
  for (const auto& e : run.log) {
    out += Logger::to_text_line(e);
    out += '\n';
  }
  return out;
}
}  // namespace

ResultStore::ResultStore(std::filesystem::path root, Logger* logger) : runs_dir_(root / "results" / "runs"), logger_(logger) {}

void ResultStore::insert_locked(RunPtr run) {
  for (auto it = runs_.begin(); it != runs_.end(); ++it) {
    if ((*it)->run_id == run->run_id) {
      runs_.erase(it);
      break;
    }
  }
  const auto pos = std::lower_bound(runs_.begin(), runs_.end(), run, [](const RunPtr& a, const RunPtr& b) { return newer(*a, *b); });
  runs_.insert(pos, std::move(run));
}

IndexReport ResultStore::rebuild_index() {
  IndexReport rep;
  std::vector<RunPtr> loaded;
  std::error_code ec;
  if (std::filesystem::is_directory(runs_dir_, ec)) {
    std::vector<std::filesystem::path> dirs;
    for (const auto& e : std::filesystem::directory_iterator(runs_dir_, ec)) {
      if (e.is_directory()) dirs.push_back(e.path());
    }
    std::sort(dirs.begin(), dirs.end());
    for (const auto& d : dirs) {
      const std::string id = d.filename().string();
      const auto text = read_file(d / "run.json", 64u << 20);
      if (!text) {
        // directory without run.json (e.g. crash before the first write): ignore silently
        continue;
      }
      nlohmann::json j = nlohmann::json::parse(*text, nullptr, false);
      std::string err;
      auto run = j.is_discarded() ? std::nullopt : run_from_json(j, &err);
      if (j.is_discarded()) err = "invalid JSON";
      if (!run || run->run_id != id) {
        ++rep.corrupt;
        rep.problems.push_back(id + ": " + (run ? "run_id does not match directory" : err));
        if (logger_) logger_->warn("system", "skipping corrupt run file " + (d / "run.json").string() + ": " + (run ? "run_id mismatch" : err));
        continue;
      }
      if (!is_final(run->status)) {
        run->status = Status::Error;
        run->error = RunError{"INTERRUPTED", "the backend stopped while this run was active"};
        run->finished_at = iso_now();
        run->current_step.clear();
        run->running_tasks = 0;
        for (auto& s : run->steps) {
          if (!is_final(s.status)) {
            s.status = Status::Cancelled;
            s.message = "interrupted";
          }
        }
        try {
          RunRecord copy = *run;
          atomic_write_file(d / "run.json", run_detail_to_json(copy, 0).dump(2, ' ', false, nlohmann::json::error_handler_t::replace));
          atomic_write_file(d / "results.csv", run_to_csv(copy));
        } catch (const std::exception& e) {
          rep.problems.push_back(id + ": could not rewrite interrupted run: " + e.what());
        }
        ++rep.recovered_interrupted;
        if (logger_) logger_->warn("system", "run " + id + " was left active by a previous process; marked ERROR/INTERRUPTED");
      }
      run->log.clear();  // logs are re-read from disk on demand
      loaded.push_back(std::make_shared<const RunRecord>(std::move(*run)));
      ++rep.loaded;
    }
  }
  std::sort(loaded.begin(), loaded.end(), [](const RunPtr& a, const RunPtr& b) { return newer(*a, *b); });
  std::lock_guard<std::mutex> lock(mu_);
  runs_ = std::move(loaded);
  corrupt_count_ = rep.corrupt;
  return rep;
}

void ResultStore::save_run(const RunRecord& run, bool index) {
  if (!is_valid_id(run.run_id)) throw std::runtime_error("invalid run id");
  const auto dir = run_dir(run.run_id);
  const std::string json = run_detail_to_json(run, 0).dump(2, ' ', false, nlohmann::json::error_handler_t::replace);
  atomic_write_file(dir / "run.json", json);
  atomic_write_file(dir / "results.csv", run_to_csv(run));
  atomic_write_file(dir / "run.log", run_log_text(run));
  if (index) {
    RunRecord copy = run;
    copy.log.clear();
    std::lock_guard<std::mutex> lock(mu_);
    insert_locked(std::make_shared<const RunRecord>(std::move(copy)));
  }
}

std::optional<RunRecord> ResultStore::get_run(const std::string& run_id, bool with_log) const {
  if (!is_valid_id(run_id)) return std::nullopt;
  RunPtr found;
  {
    std::lock_guard<std::mutex> lock(mu_);
    for (const auto& r : runs_) {
      if (r->run_id == run_id) found = r;
    }
  }
  if (!found) return std::nullopt;
  RunRecord out = *found;
  if (with_log) {
    const auto text = read_file(run_dir(run_id) / "run.json", 64u << 20);
    if (text) {
      nlohmann::json j = nlohmann::json::parse(*text, nullptr, false);
      std::string err;
      if (!j.is_discarded()) {
        if (auto full = run_from_json(j, &err)) out.log = std::move(full->log);
      }
    }
  }
  return out;
}

bool ResultStore::contains(const std::string& run_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  return std::any_of(runs_.begin(), runs_.end(), [&](const RunPtr& r) { return r->run_id == run_id; });
}

RunPage ResultStore::list_runs(const RunFilter& f) const {
  std::vector<RunPtr> snapshot;
  {
    std::lock_guard<std::mutex> lock(mu_);
    snapshot = runs_;
  }
  RunPage page;
  size_t matched = 0;
  for (const auto& r : snapshot) {
    if (!f.status.empty() && to_string(r->status) != f.status) continue;
    if (!f.sequence_id.empty() && r->sequence_id != f.sequence_id) continue;
    if (matched >= f.offset && page.runs.size() < f.limit) page.runs.push_back(*r);
    ++matched;
  }
  page.total = matched;
  return page;
}

TaskPage ResultStore::query_tasks(const TaskFilter& f) const {
  std::vector<RunPtr> snapshot;
  {
    std::lock_guard<std::mutex> lock(mu_);
    snapshot = runs_;
  }
  TaskPage page;
  size_t matched = 0;
  for (const auto& r : snapshot) {
    if (!f.run_id.empty() && r->run_id != f.run_id) continue;
    if (!f.sequence_id.empty() && r->sequence_id != f.sequence_id) continue;
    for (auto it = r->tasks.rbegin(); it != r->tasks.rend(); ++it) {
      const TaskResult& t = *it;
      if (!f.status.empty() && to_string(t.status) != f.status) continue;
      if (!f.kind.empty() && t.kind != f.kind) continue;
      if (!f.firmware.empty() && t.dut_firmware != f.firmware) continue;
      if (!f.profile.empty() && t.dut_profile != f.profile) continue;
      if (matched >= f.offset && page.tasks.size() < f.limit) page.tasks.push_back(t);
      ++matched;
    }
  }
  page.total = matched;
  return page;
}

HistoryStats ResultStore::history() const {
  std::lock_guard<std::mutex> lock(mu_);
  HistoryStats h;
  h.runs = runs_.size();
  for (const auto& r : runs_) h.tasks += r->tasks.size();
  if (!runs_.empty()) {
    h.last_run = runs_.front()->created_at;
    h.first_run = runs_.back()->created_at;
  }
  return h;
}

SummaryReport ResultStore::summary(const std::string& sequence_id, size_t max_runs) const {
  std::vector<RunPtr> snapshot;
  {
    std::lock_guard<std::mutex> lock(mu_);
    snapshot = runs_;
  }
  std::vector<const RunRecord*> selected;
  for (const auto& r : snapshot) {
    if (!sequence_id.empty() && r->sequence_id != sequence_id) continue;
    if (selected.size() >= max_runs) break;
    selected.push_back(r.get());
  }
  return compute_summary(selected);  // `snapshot` keeps the records alive during the computation
}

size_t ResultStore::corrupt_files() const {
  std::lock_guard<std::mutex> lock(mu_);
  return corrupt_count_;
}

}  // namespace mf
