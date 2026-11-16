#include "measureflow/util/fs.hpp"

#include <fcntl.h>
#include <unistd.h>

#include <atomic>
#include <cerrno>
#include <cstring>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace mf {

namespace {
std::atomic<unsigned long> g_tmp_counter{0};
}

void atomic_write_file(const fs::path& path, const std::string& content) {
  std::error_code ec;
  if (path.has_parent_path()) fs::create_directories(path.parent_path(), ec);
  const fs::path tmp = path.parent_path() / (path.filename().string() + ".tmp." + std::to_string(::getpid()) + "." +
                                              std::to_string(g_tmp_counter.fetch_add(1)));
  const int fd = ::open(tmp.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
  if (fd < 0) throw std::runtime_error("cannot create " + tmp.string() + ": " + std::strerror(errno));
  size_t off = 0;
  while (off < content.size()) {
    const ssize_t n = ::write(fd, content.data() + off, content.size() - off);
    if (n < 0) {
      if (errno == EINTR) continue;
      const int e = errno;
      ::close(fd);
      ::unlink(tmp.c_str());
      throw std::runtime_error("write failed for " + tmp.string() + ": " + std::strerror(e));
    }
    off += static_cast<size_t>(n);
  }
  ::fsync(fd);
  ::close(fd);
  if (::rename(tmp.c_str(), path.c_str()) != 0) {
    const int e = errno;
    ::unlink(tmp.c_str());
    throw std::runtime_error("rename to " + path.string() + " failed: " + std::strerror(e));
  }
}

std::optional<std::string> read_file(const fs::path& path, size_t max_bytes) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return std::nullopt;
  std::error_code ec;
  const auto size = fs::file_size(path, ec);
  if (!ec && size > max_bytes) return std::nullopt;
  std::ostringstream ss;
  ss << in.rdbuf();
  if (in.bad()) return std::nullopt;
  std::string s = ss.str();
  if (s.size() > max_bytes) return std::nullopt;
  return s;
}

bool ensure_dir(const fs::path& dir) {
  std::error_code ec;
  fs::create_directories(dir, ec);
  return !ec && fs::is_directory(dir, ec);
}

bool dir_writable(const fs::path& dir) {
  if (!ensure_dir(dir)) return false;
  const fs::path probe = dir / (".probe." + std::to_string(::getpid()) + "." + std::to_string(g_tmp_counter.fetch_add(1)));
  try {
    atomic_write_file(probe, "ok");
  } catch (const std::exception&) {
    return false;
  }
  std::error_code ec;
  fs::remove(probe, ec);
  return true;
}

}  // namespace mf
