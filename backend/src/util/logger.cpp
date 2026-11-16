#include "measureflow/util/logger.hpp"

#include <cstdio>
#include <system_error>

#include "json.hpp"
#include "measureflow/util/fs.hpp"
#include "measureflow/util/time.hpp"

namespace mf {

const char* to_string(LogLevel level) {
  switch (level) {
    case LogLevel::Debug: return "debug";
    case LogLevel::Info: return "info";
    case LogLevel::Warn: return "warn";
    case LogLevel::Error: return "error";
  }
  return "info";
}

std::optional<LogLevel> parse_log_level(const std::string& s) {
  if (s == "debug") return LogLevel::Debug;
  if (s == "info") return LogLevel::Info;
  if (s == "warn" || s == "warning") return LogLevel::Warn;
  if (s == "error") return LogLevel::Error;
  return std::nullopt;
}

namespace {
nlohmann::json fields_to_json(const LogFields& fields) {
  nlohmann::json o = nlohmann::json::object();
  for (const auto& kv : fields) {
    std::visit([&](const auto& v) { o[kv.first] = v; }, kv.second);
  }
  return o;
}
}  // namespace

Logger::Logger(size_t ring_capacity) : capacity_(ring_capacity == 0 ? 1 : ring_capacity) {}

Logger::~Logger() {
  std::lock_guard<std::mutex> lock(mu_);
  if (file_) {
    std::fclose(file_);
    file_ = nullptr;
  }
}

bool Logger::open_file(const std::filesystem::path& path, size_t max_bytes, int keep) {
  std::lock_guard<std::mutex> lock(mu_);
  if (file_) {
    std::fclose(file_);
    file_ = nullptr;
  }
  std::error_code ec;
  if (path.has_parent_path()) std::filesystem::create_directories(path.parent_path(), ec);
  file_path_ = path;
  file_max_bytes_ = max_bytes;
  file_keep_ = keep < 1 ? 1 : keep;
  file_ = std::fopen(path.c_str(), "ab");
  if (!file_) return false;
  const auto sz = std::filesystem::file_size(path, ec);
  file_size_ = ec ? 0 : static_cast<size_t>(sz);
  return true;
}

void Logger::set_min_level(LogLevel level) {
  std::lock_guard<std::mutex> lock(mu_);
  min_level_ = level;
}

LogLevel Logger::min_level() const {
  std::lock_guard<std::mutex> lock(mu_);
  return min_level_;
}

void Logger::set_stderr_echo(bool on) {
  std::lock_guard<std::mutex> lock(mu_);
  echo_ = on;
}

std::string Logger::to_json_line(const LogEntry& e) {
  nlohmann::json j;
  j["seq"] = e.seq;
  j["ts"] = e.ts;
  j["level"] = to_string(e.level);
  j["source"] = e.source;
  j["message"] = e.message;
  j["fields"] = fields_to_json(e.fields);
  if (!e.run_id.empty()) j["run_id"] = e.run_id;
  // error_handler_t::replace keeps the logger safe against invalid UTF-8 in instrument responses
  return j.dump(-1, ' ', false, nlohmann::json::error_handler_t::replace);
}

std::string Logger::to_text_line(const LogEntry& e) {
  std::string line = e.ts + " " + to_string(e.level) + " [" + e.source + "] " + e.message;
  if (!e.fields.empty()) {
    line += " " + fields_to_json(e.fields).dump(-1, ' ', false, nlohmann::json::error_handler_t::replace);
  }
  return line;
}

void Logger::rotate_locked() {
  if (file_) {
    std::fclose(file_);
    file_ = nullptr;
  }
  std::error_code ec;
  for (int i = file_keep_; i >= 1; --i) {
    const std::filesystem::path from = (i == 1) ? file_path_ : std::filesystem::path(file_path_.string() + "." + std::to_string(i - 1));
    const std::filesystem::path to = file_path_.string() + "." + std::to_string(i);
    if (!std::filesystem::exists(from, ec)) continue;
    if (i == file_keep_) std::filesystem::remove(to, ec);
    std::filesystem::rename(from, to, ec);
  }
  file_ = std::fopen(file_path_.c_str(), "ab");
  file_size_ = 0;
}

void Logger::write_file_locked(const std::string& line) {
  if (!file_) return;
  if (file_max_bytes_ > 0 && file_size_ + line.size() + 1 > file_max_bytes_ && file_size_ > 0) rotate_locked();
  if (!file_) return;
  std::fwrite(line.data(), 1, line.size(), file_);
  std::fputc('\n', file_);
  std::fflush(file_);
  file_size_ += line.size() + 1;
}

void Logger::log(LogLevel level, const std::string& source, const std::string& message, LogFields fields,
                 const std::string& run_id) {
  LogEntry e;
  e.ts = iso_now();
  e.level = level;
  e.source = source;
  e.message = message;
  e.fields = std::move(fields);
  e.run_id = run_id;

  std::lock_guard<std::mutex> lock(mu_);
  if (level < min_level_) return;
  e.seq = next_seq_++;
  if (!run_id.empty()) {
    auto it = captures_.find(run_id);
    if (it != captures_.end()) {
      it->second.entries.push_back(e);
      while (it->second.entries.size() > it->second.capacity) it->second.entries.pop_front();
    }
  }
  const std::string line = (file_ || echo_) ? to_json_line(e) : std::string();
  write_file_locked(line);
  if (echo_) {
    const std::string text = to_text_line(e);
    std::fprintf(stderr, "%s\n", text.c_str());
  }
  ring_.push_back(std::move(e));
  while (ring_.size() > capacity_) ring_.pop_front();
}

std::vector<LogEntry> Logger::query(const LogQuery& q) const {
  std::lock_guard<std::mutex> lock(mu_);
  std::vector<LogEntry> matched;
  for (const auto& e : ring_) {
    if (e.seq <= q.since_seq) continue;
    if (q.min_level && e.level < *q.min_level) continue;
    if (!q.source.empty() && e.source != q.source) continue;
    matched.push_back(e);
  }
  if (q.limit > 0 && matched.size() > q.limit) {
    // newest `limit` entries, still oldest-first
    matched.erase(matched.begin(), matched.begin() + static_cast<std::ptrdiff_t>(matched.size() - q.limit));
  }
  return matched;
}

uint64_t Logger::last_seq() const {
  std::lock_guard<std::mutex> lock(mu_);
  return next_seq_ - 1;
}

void Logger::open_run_capture(const std::string& run_id, size_t capacity) {
  std::lock_guard<std::mutex> lock(mu_);
  Capture c;
  c.capacity = capacity == 0 ? 1 : capacity;
  captures_[run_id] = std::move(c);
}

std::vector<LogEntry> Logger::run_tail(const std::string& run_id, size_t n) const {
  std::lock_guard<std::mutex> lock(mu_);
  std::vector<LogEntry> out;
  const auto it = captures_.find(run_id);
  if (it == captures_.end()) return out;
  const auto& d = it->second.entries;
  size_t start = 0;
  if (n > 0 && d.size() > n) start = d.size() - n;
  for (size_t i = start; i < d.size(); ++i) out.push_back(d[i]);
  return out;
}

std::vector<LogEntry> Logger::close_run_capture(const std::string& run_id) {
  std::lock_guard<std::mutex> lock(mu_);
  std::vector<LogEntry> out;
  const auto it = captures_.find(run_id);
  if (it == captures_.end()) return out;
  out.assign(it->second.entries.begin(), it->second.entries.end());
  captures_.erase(it);
  return out;
}

}  // namespace mf
