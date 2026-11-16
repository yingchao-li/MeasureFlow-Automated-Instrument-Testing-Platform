#pragma once

#include <exception>
#include <string>

#include "measureflow/api/http_types.hpp"
#include "measureflow/util/errors.hpp"

namespace mf {

// Writes the unified error body {"error":{"code","message","details"}} and the HTTP status.
void write_error(HttpResponse& res, ErrorCode code, const std::string& message, const std::string& details_json = "{}");
// Maps any exception thrown by a handler (MfError, ScpiError, std::exception) to the unified error body.
void write_exception(HttpResponse& res, const std::exception_ptr& ep);
// HTTP 405 / 404 / 413 helpers used by the server adapter.
void write_plain_error(HttpResponse& res, int status, ErrorCode code, const std::string& message);

}  // namespace mf
