#pragma once

#include <stdexcept>
#include <string>

namespace mf {

enum class ScpiErrorKind { Timeout, Disconnected, InvalidResponse, ResponseTooLarge, Instrument, Cancelled };

const char* to_string(ScpiErrorKind kind);
// Kinds that indicate a transport/protocol problem (as opposed to an instrument-reported error).
bool is_communication_kind(ScpiErrorKind kind);

class ScpiError : public std::runtime_error {
 public:
  ScpiError(ScpiErrorKind kind, std::string instrument, std::string command, const std::string& message,
            int instrument_code = 0, std::string instrument_message = {})
      : std::runtime_error(message),
        kind_(kind),
        instrument_(std::move(instrument)),
        command_(std::move(command)),
        code_(instrument_code),
        instrument_message_(std::move(instrument_message)) {}
  ScpiErrorKind kind() const { return kind_; }
  const std::string& instrument() const { return instrument_; }
  const std::string& command() const { return command_; }
  // SCPI error number when kind() == Instrument (e.g. -222), else 0.
  int instrument_code() const { return code_; }
  // Message part of the SYST:ERR? entry (e.g. "Data out of range") when kind() == Instrument.
  const std::string& instrument_message() const { return instrument_message_; }

 private:
  ScpiErrorKind kind_;
  std::string instrument_;
  std::string command_;
  int code_;
  std::string instrument_message_;
};

// One entry of the instrument error queue (SYST:ERR?).
struct InstrumentError {
  int code = 0;
  std::string message;
};

}  // namespace mf
