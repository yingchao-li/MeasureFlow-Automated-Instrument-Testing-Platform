// ResultStore: file-based persistence of runs (results/runs/<run_id>/run.json|results.csv|run.log),
// in-memory index rebuilt at startup, filters + pagination for the history endpoints.
//
// Locking: `mu_` guards the in-memory index only (leaf lock: file I/O happens outside of it).
#pragma once

#include <filesystem>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "measureflow/engine/statistics.hpp"
#include "measureflow/engine/types.hpp"
#include "measureflow/util/logger.hpp"

namespace mf {

struct RunFilter {
  std::string status;       // empty = any
  std::string sequence_id;  // empty = any
  size_t limit = 50;
  size_t offset = 0;
};

struct TaskFilter {
  std::string run_id, sequence_id, status, kind, firmware, profile;
  size_t limit = 100;
  size_t offset = 0;
};

struct RunPage {
  size_t total = 0;
  std::vector<RunRecord> runs;
};

struct TaskPage {
  size_t total = 0;
  std::vector<TaskResult> tasks;
};

struct HistoryStats {
  size_t runs = 0;
  size_t tasks = 0;
  std::string first_run;  // created_at of the oldest run, empty if none
  std::string last_run;   // created_at of the newest run, empty if none
};

struct IndexReport {
  size_t loaded = 0;
  size_t corrupt = 0;
  size_t recovered_interrupted = 0;
  std::vector<std::string> problems;
};

class ResultStore {
 public:
  // `root` is the repository root; runs live in <root>/results/runs.
  explicit ResultStore(std::filesystem::path root, Logger* logger = nullptr);

  std::filesystem::path runs_dir() const { return runs_dir_; }
  std::filesystem::path run_dir(const std::string& run_id) const { return runs_dir_ / run_id; }

  // Scans results/runs. Corrupt run files are skipped (never thrown); runs left in PENDING/RUNNING by a
  // previous process are rewritten as ERROR (code INTERRUPTED).
  IndexReport rebuild_index();

  // Writes run.json (+ results.csv + run.log) atomically. When `index` is true the in-memory index is updated.
  // Throws std::runtime_error when the files cannot be written.
  void save_run(const RunRecord& run, bool index = true);

  std::optional<RunRecord> get_run(const std::string& run_id, bool with_log = false) const;
  bool contains(const std::string& run_id) const;
  RunPage list_runs(const RunFilter& f) const;
  TaskPage query_tasks(const TaskFilter& f) const;
  HistoryStats history() const;
  SummaryReport summary(const std::string& sequence_id, size_t max_runs) const;
  size_t corrupt_files() const;

 private:
  using RunPtr = std::shared_ptr<const RunRecord>;
  void insert_locked(RunPtr run);

  std::filesystem::path runs_dir_;
  Logger* logger_;
  mutable std::mutex mu_;
  std::vector<RunPtr> runs_;  // newest first
  size_t corrupt_count_ = 0;
};

}  // namespace mf
