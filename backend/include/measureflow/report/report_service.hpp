// ReportService: writes reports/<run_id>.{csv,html,pdf} atomically and serves them back.
// Lock-free: file operations are atomic renames; the ResultStore has its own lock.
#pragma once

#include <filesystem>
#include <optional>
#include <string>
#include <vector>

#include "measureflow/engine/result_store.hpp"
#include "measureflow/util/logger.hpp"

namespace mf {

struct ReportFile {
  std::string content;
  std::string content_type;
  std::string filename;
};

struct ReportListing {
  RunRecord run;  // without tasks' logs; used for the summary fields
};

class ReportService {
 public:
  ReportService(std::filesystem::path root, ResultStore& store, Logger* logger = nullptr);
  std::filesystem::path reports_dir() const { return dir_; }

  // Generates and atomically writes the three files. Throws std::runtime_error on I/O failure.
  void generate(const RunRecord& run);
  // Newest first, at most `limit` entries.
  std::vector<RunRecord> list(size_t limit = 500) const;
  // nullopt when the run is unknown. A missing file of a known run is regenerated on demand.
  // `ext` must be "csv", "html" or "pdf" (else nullopt).
  std::optional<ReportFile> fetch(const std::string& run_id, const std::string& ext);
  bool exists(const std::string& run_id, const std::string& ext) const;

 private:
  std::filesystem::path dir_;
  ResultStore& store_;
  Logger* logger_;
};

}  // namespace mf
