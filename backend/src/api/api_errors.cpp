#include "measureflow/api/api_errors.hpp"

#include "json.hpp"
#include "measureflow/scpi/scpi_error.hpp"

namespace mf {

using nlohmann::json;

static void fill(HttpResponse& res, int status, ErrorCode code, const std::string& message, json details) {
  res.status = status;
  res.content_type = "application/json";
  res.body = json{{"error", json{{"code", to_string(code)}, {"message", message}, {"details", details}}}}.dump(-1, ' ', false, json::error_handler_t::replace);
}

void write_error(HttpResponse& res, ErrorCode code, const std::string& message, const std::string& details_json) {
  json d = json::parse(details_json, nullptr, false);
  if (d.is_discarded() || !d.is_object()) d = json::object();
  fill(res, http_status(code), code, message, d);
}

void write_plain_error(HttpResponse& res, int status, ErrorCode code, const std::string& message) {
  fill(res, status, code, message, json::object());
}

void write_exception(HttpResponse& res, const std::exception_ptr& ep) {
  try {
    std::rethrow_exception(ep);
  } catch (const MfError& e) {
    json d = json::object();
    if (!e.field().empty()) d["field"] = e.field();
    if (!e.kind().empty()) d["kind"] = e.kind();
    fill(res, http_status(e.code()), e.code(), e.what(), d);
  } catch (const ScpiError& e) {
    json d = json::object();
    d["kind"] = to_string(e.kind());
    d["instrument"] = e.instrument();
    if (!e.command().empty()) d["command"] = e.command().substr(0, 128);
    if (e.kind() == ScpiErrorKind::Instrument) d["scpi_code"] = e.instrument_code();
    const ErrorCode code = e.kind() == ScpiErrorKind::Timeout ? ErrorCode::Timeout : ErrorCode::CommunicationError;
    fill(res, http_status(code), code, e.what(), d);
  } catch (const json::exception& e) {
    fill(res, 400, ErrorCode::InvalidArgument, std::string("malformed JSON: ") + e.what(), json::object());
  } catch (const std::exception& e) {
    fill(res, 500, ErrorCode::Internal, std::string("internal error: ") + e.what(), json::object());
  } catch (...) {
    fill(res, 500, ErrorCode::Internal, "internal error", json::object());
  }
}

}  // namespace mf
