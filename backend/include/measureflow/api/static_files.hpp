// Static file serving for the built frontend (frontend/dist) with path-traversal protection and SPA fallback.
#pragma once

#include <filesystem>
#include <string>

#include "measureflow/api/http_types.hpp"

namespace mf {

class StaticFiles {
 public:
  explicit StaticFiles(std::filesystem::path root);

  enum class Outcome { Served, NotFound, Rejected, Unavailable };
  // `path` is the percent-decoded request path ("/assets/app.js"). Never reads outside the root.
  //  Rejected    : the path is unsafe (".." segments, NUL, backslash, hidden files) -> 400
  //  Unavailable : the frontend has not been built (no index.html)                  -> 404 with a hint
  //  NotFound    : unknown file with an extension (e.g. /assets/missing.js)         -> 404
  //  Served      : file, directory index or SPA fallback (extension-less path -> index.html)
  Outcome serve(const std::string& path, HttpResponse& res) const;

  static bool is_safe_request_path(const std::string& decoded_path);
  static std::string mime_for(const std::string& extension);

 private:
  std::filesystem::path root_;
};

}  // namespace mf
