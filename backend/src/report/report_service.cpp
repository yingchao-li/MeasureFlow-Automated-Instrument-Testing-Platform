#include "measureflow/report/report_service.hpp"

#include "measureflow/report/csv_report.hpp"
#include "measureflow/report/report_generator.hpp"
#include "measureflow/util/fs.hpp"
#include "measureflow/util/strings.hpp"

namespace mf {

ReportService::ReportService(std::filesystem::path root, ResultStore& store, Logger* logger)
    : dir_(root / "reports"), store_(store), logger_(logger) {}

void ReportService::generate(const RunRecord& run) {
  if (!is_valid_id(run.run_id)) throw std::runtime_error("invalid run id");
  atomic_write_file(dir_ / (run.run_id + ".csv"), run_to_csv(run));
  atomic_write_file(dir_ / (run.run_id + ".html"), run_to_html(run));
  atomic_write_file(dir_ / (run.run_id + ".pdf"), run_to_pdf(run));
  if (logger_) logger_->info("engine", "reports written for " + run.run_id, {{"run_id", run.run_id}}, run.run_id);
}

std::vector<RunRecord> ReportService::list(size_t limit) const {
  RunFilter f;
  f.limit = limit;
  return store_.list_runs(f).runs;
}

bool ReportService::exists(const std::string& run_id, const std::string& ext) const {
  if (!is_valid_id(run_id)) return false;
  std::error_code ec;
  return std::filesystem::is_regular_file(dir_ / (run_id + "." + ext), ec);
}

std::optional<ReportFile> ReportService::fetch(const std::string& run_id, const std::string& ext) {
  if (!is_valid_id(run_id)) return std::nullopt;
  std::string type;
  if (ext == "csv") type = "text/csv; charset=utf-8";
  else if (ext == "html") type = "text/html; charset=utf-8";
  else if (ext == "pdf") type = "application/pdf";
  else return std::nullopt;
  if (!store_.contains(run_id)) return std::nullopt;
  const auto path = dir_ / (run_id + "." + ext);
  auto content = read_file(path, 128u << 20);
  if (!content) {
    auto run = store_.get_run(run_id, true);
    if (!run) return std::nullopt;
    try {
      generate(*run);
    } catch (const std::exception& e) {
      if (logger_) logger_->error("engine", std::string("report regeneration failed: ") + e.what(), {{"run_id", run_id}});
      return std::nullopt;
    }
    content = read_file(path, 128u << 20);
    if (!content) return std::nullopt;
  }
  return ReportFile{std::move(*content), type, run_id + "." + ext};
}

}  // namespace mf
