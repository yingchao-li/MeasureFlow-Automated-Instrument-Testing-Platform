// Unified error type used across layers; the API layer maps it to the
// error body documented in docs/INTERFACE.md (section 5).
#pragma once

#include <stdexcept>
#include <string>

namespace mf {

enum class ErrorCode {
  InvalidArgument,
  ForbiddenHost,
  NotFound,
  NotConnected,
  InstrumentBusy,
  Conflict,
  CommunicationError,
  Timeout,
  Internal
};

const char* to_string(ErrorCode code);
int http_status(ErrorCode code);

class MfError : public std::runtime_error {
 public:
  MfError(ErrorCode code, std::string message, std::string field = {}, std::string kind = {});
  ErrorCode code() const { return code_; }
  const std::string& field() const { return field_; }
  const std::string& kind() const { return kind_; }

 private:
  ErrorCode code_;
  std::string field_;
  std::string kind_;
};

}  // namespace mf
