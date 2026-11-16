// Structured logger: bounded in-memory ring buffer (served by GET /api/logs),
// JSON-lines file with size-based rotation, and optional per-run capture
// (so a run's detail can show only its own entries).
//
// Locking: Logger::mu_ is a leaf lock — no other lock is ever acquired while it is held
// and no callbacks are invoked under it.
#pragma once

#include <cstdint>
#include <cstdio>
#include <deque>
#include <filesystem>
#include <map>
#include <mutex>
#include <optional>
#include <string>
#include <utility>
#include <variant>
#include <vector>

namespace mf {

enum class LogLevel { Debug = 0, Info = 1, Warn = 2, Error = 3 };

const char* to_string(LogLevel level);
std::optional<LogLevel> parse_log_level(const std::string& s);

using LogValue = std::variant<std::string, double, int64_t, bool>;
using LogFields = std::vector<std::pair<std::string, LogValue>>;

struct LogEntry {
  uint64_t seq = 0;
  std::string ts;
  LogLevel level = LogLevel::Info;
  std::string source;  // api | scpi | engine | env | system
  std::string message;
  LogFields fields;
  std::string run_id;  // empty when not tied to a run
};

struct LogQuery {
  size_t limit = 200;
  std::optional<LogLevel> min_level;  // entries with level >= min_level
  std::string source;                 // empty = any
  uint64_t since_seq = 0;             // entries with seq > since_seq
};

class Logger {
 public:
  explicit Logger(size_t ring_capacity = 5000);
  ~Logger();
  Logger(const Logger&) = delete;
  Logger& operator=(const Logger&) = delete;

  // Enables the JSON-lines file sink. Rotates at `max_bytes`, keeping `keep` old files.
  // Returns false if the file cannot be opened (logging continues in memory only).
  bool open_file(const std::filesystem::path& path, size_t max_bytes = 5u * 1024u * 1024u, int keep = 3);
  void set_min_level(LogLevel level);
  LogLevel min_level() const;
  // Mirror entries to stderr (used by the executable, not by tests).
  void set_stderr_echo(bool on);

  void log(LogLevel level, const std::string& source, const std::string& message, LogFields fields = {},
           const std::string& run_id = {});
  void debug(const std::string& source, const std::string& message, LogFields fields = {}, const std::string& run_id = {}) {
    log(LogLevel::Debug, source, message, std::move(fields), run_id);
  }
  void info(const std::string& source, const std::string& message, LogFields fields = {}, const std::string& run_id = {}) {
    log(LogLevel::Info, source, message, std::move(fields), run_id);
  }
  void warn(const std::string& source, const std::string& message, LogFields fields = {}, const std::string& run_id = {}) {
    log(LogLevel::Warn, source, message, std::move(fields), run_id);
  }
  void error(const std::string& source, const std::string& message, LogFields fields = {}, const std::string& run_id = {}) {
    log(LogLevel::Error, source, message, std::move(fields), run_id);
  }

  // Oldest-first page of the ring buffer.
  std::vector<LogEntry> query(const LogQuery& q) const;
  uint64_t last_seq() const;

  // Per-run capture: entries logged with this run_id are additionally kept (up to `capacity`).
  void open_run_capture(const std::string& run_id, size_t capacity = 2000);
  // Last `n` captured entries (all when n == 0) without closing the capture.
  std::vector<LogEntry> run_tail(const std::string& run_id, size_t n) const;
  // Stops capturing and returns everything captured.
  std::vector<LogEntry> close_run_capture(const std::string& run_id);

  // Formatting used for the JSON-lines file and run.log.
  static std::string to_json_line(const LogEntry& e);
  static std::string to_text_line(const LogEntry& e);

 private:
  struct Capture {
    std::deque<LogEntry> entries;
    size_t capacity = 2000;
  };
  void rotate_locked();
  void write_file_locked(const std::string& line);

  mutable std::mutex mu_;
  size_t capacity_;
  std::deque<LogEntry> ring_;
  uint64_t next_seq_ = 1;
  LogLevel min_level_ = LogLevel::Info;
  bool echo_ = false;
  std::map<std::string, Capture> captures_;

  std::filesystem::path file_path_;
  size_t file_max_bytes_ = 0;
  int file_keep_ = 3;
  size_t file_size_ = 0;
  std::FILE* file_ = nullptr;
};

}  // namespace mf
