#include "measureflow/api/static_files.hpp"

#include <algorithm>

#include "measureflow/util/fs.hpp"
#include "measureflow/util/strings.hpp"

namespace mf {

namespace fs = std::filesystem;

StaticFiles::StaticFiles(fs::path root) : root_(std::move(root)) {}

bool StaticFiles::is_safe_request_path(const std::string& p) {
  if (p.empty() || p[0] != '/') return false;
  if (p.find('\0') != std::string::npos || p.find('\\') != std::string::npos) return false;
  for (char c : p) {
    if (static_cast<unsigned char>(c) < 0x20 || c == 0x7F) return false;
  }
  for (const auto& seg : split(p, '/')) {
    if (seg == "..") return false;
    if (seg.size() > 1 && seg[0] == '.') return false;  // dotfiles and "..x" tricks
  }
  return true;
}

std::string StaticFiles::mime_for(const std::string& ext) {
  const std::string e = to_lower(ext);
  if (e == ".html" || e == ".htm") return "text/html; charset=utf-8";
  if (e == ".js" || e == ".mjs") return "text/javascript; charset=utf-8";
  if (e == ".css") return "text/css; charset=utf-8";
  if (e == ".json" || e == ".map") return "application/json";
  if (e == ".svg") return "image/svg+xml";
  if (e == ".png") return "image/png";
  if (e == ".jpg" || e == ".jpeg") return "image/jpeg";
  if (e == ".gif") return "image/gif";
  if (e == ".webp") return "image/webp";
  if (e == ".ico") return "image/x-icon";
  if (e == ".woff2") return "font/woff2";
  if (e == ".woff") return "font/woff";
  if (e == ".ttf") return "font/ttf";
  if (e == ".txt") return "text/plain; charset=utf-8";
  if (e == ".wasm") return "application/wasm";
  return "application/octet-stream";
}

namespace {
bool within(const fs::path& root, const fs::path& candidate) {
  auto r = root.begin();
  auto c = candidate.begin();
  for (; r != root.end(); ++r, ++c) {
    if (c == candidate.end() || *r != *c) return false;
  }
  return true;
}

void fill_file(HttpResponse& res, const fs::path& file, const std::string& content) {
  res.status = 200;
  res.content_type = StaticFiles::mime_for(file.extension().string());
  res.body = content;
  // index.html must always be revalidated; hashed assets may be cached.
  res.headers["Cache-Control"] = file.filename() == "index.html" ? "no-cache" : "public, max-age=3600";
}
}  // namespace

StaticFiles::Outcome StaticFiles::serve(const std::string& path, HttpResponse& res) const {
  std::error_code ec;
  const fs::path index = root_ / "index.html";
  if (!fs::is_regular_file(index, ec)) return Outcome::Unavailable;
  if (!is_safe_request_path(path)) return Outcome::Rejected;

  const fs::path canon_root = fs::weakly_canonical(root_, ec);
  if (ec) return Outcome::Unavailable;
  std::string rel = path.substr(1);
  fs::path candidate = rel.empty() ? index : (canon_root / rel);
  candidate = fs::weakly_canonical(candidate, ec);
  if (ec || !within(canon_root, candidate)) return Outcome::Rejected;
  if (fs::is_directory(candidate, ec)) candidate /= "index.html";
  if (fs::is_regular_file(candidate, ec)) {
    const auto content = read_file(candidate, 64u << 20);
    if (!content) return Outcome::NotFound;
    fill_file(res, candidate, *content);
    return Outcome::Served;
  }
  // SPA fallback for client-side routes (no file extension in the last segment).
  const fs::path last = fs::path(rel).filename();
  if (last.extension().empty()) {
    const auto content = read_file(index, 64u << 20);
    if (!content) return Outcome::Unavailable;
    fill_file(res, index, *content);
    return Outcome::Served;
  }
  return Outcome::NotFound;
}

}  // namespace mf
