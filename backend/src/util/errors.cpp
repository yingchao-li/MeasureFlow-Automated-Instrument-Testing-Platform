#include "measureflow/util/errors.hpp"

namespace mf {

const char* to_string(ErrorCode code) {
  switch (code) {
    case ErrorCode::InvalidArgument: return "INVALID_ARGUMENT";
    case ErrorCode::ForbiddenHost: return "FORBIDDEN_HOST";
    case ErrorCode::NotFound: return "NOT_FOUND";
    case ErrorCode::NotConnected: return "NOT_CONNECTED";
    case ErrorCode::InstrumentBusy: return "INSTRUMENT_BUSY";
    case ErrorCode::Conflict: return "CONFLICT";
    case ErrorCode::CommunicationError: return "COMMUNICATION_ERROR";
    case ErrorCode::Timeout: return "TIMEOUT";
    case ErrorCode::Internal: return "INTERNAL";
  }
  return "INTERNAL";
}

int http_status(ErrorCode code) {
  switch (code) {
    case ErrorCode::InvalidArgument: return 400;
    case ErrorCode::ForbiddenHost: return 403;
    case ErrorCode::NotFound: return 404;
    case ErrorCode::NotConnected: return 409;
    case ErrorCode::InstrumentBusy: return 409;
    case ErrorCode::Conflict: return 409;
    case ErrorCode::CommunicationError: return 502;
    case ErrorCode::Timeout: return 504;
    case ErrorCode::Internal: return 500;
  }
  return 500;
}

MfError::MfError(ErrorCode code, std::string message, std::string field, std::string kind)
    : std::runtime_error(std::move(message)),
      code_(code),
      field_(std::move(field)),
      kind_(std::move(kind)) {}

}  // namespace mf
