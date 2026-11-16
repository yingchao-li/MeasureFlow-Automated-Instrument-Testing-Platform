// Filesystem helpers: atomic writes (temp file + fsync + rename), safe reads.
#pragma once

#include <filesystem>
#include <optional>
#include <string>

namespace mf {

namespace fs = std::filesystem;

// Writes `content` to `path` atomically: temp file in the same directory, fsync, rename.
// Creates parent directories. Throws std::runtime_error on failure.
void atomic_write_file(const fs::path& path, const std::string& content);
// Whole-file read; nullopt if it cannot be read or exceeds `max_bytes`.
std::optional<std::string> read_file(const fs::path& path, size_t max_bytes = 64u * 1024u * 1024u);
// Creates the directory (and parents); false on failure.
bool ensure_dir(const fs::path& dir);
// True if a probe file can be created and removed in `dir`.
bool dir_writable(const fs::path& dir);

}  // namespace mf
