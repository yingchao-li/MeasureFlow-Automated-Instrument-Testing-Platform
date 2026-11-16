#include "measureflow/scpi/scpi_error.hpp"

namespace mf {

const char* to_string(ScpiErrorKind kind) {
  switch (kind) {
    case ScpiErrorKind::Timeout: return "timeout";
    case ScpiErrorKind::Disconnected: return "disconnected";
    case ScpiErrorKind::InvalidResponse: return "invalid_response";
    case ScpiErrorKind::ResponseTooLarge: return "response_too_large";
    case ScpiErrorKind::Instrument: return "instrument";
    case ScpiErrorKind::Cancelled: return "cancelled";
  }
  return "unknown";
}

bool is_communication_kind(ScpiErrorKind kind) {
  return kind == ScpiErrorKind::Timeout || kind == ScpiErrorKind::Disconnected ||
         kind == ScpiErrorKind::InvalidResponse || kind == ScpiErrorKind::ResponseTooLarge;
}

}  // namespace mf
