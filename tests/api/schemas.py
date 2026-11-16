"""JSON schemas derived from docs/INTERFACE.md section 5 (the binding contract).

Schemas validate *shape and types* of success bodies; extra keys are tolerated (forward
compatible) except where the contract says otherwise. Semantic invariants that a schema cannot
express (PASS => inside limits, FAIL => outside limits, ERROR => no measured value, ...) live in
:func:`assert_task_semantics`.
"""
from __future__ import annotations

import math
import re
from typing import Any, Optional

import jsonschema

TS = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"}
TS_NULL = {"anyOf": [TS, {"type": "null"}]}
STR_NULL = {"type": ["string", "null"]}
NUM_NULL = {"type": ["number", "null"]}
RUN_ID = {"type": "string", "pattern": r"^run-\d{8}-\d{6}-[0-9a-f]{4}$"}
RUN_STATUS = ["PENDING", "RUNNING", "PASS", "FAIL", "ERROR", "CANCELLED"]
TASK_STATUS = ["PENDING", "RUNNING", "PASS", "FAIL", "ERROR", "CANCELLED"]
KINDS = ["rms", "gain", "thd", "snr", "noise_floor", "freq_sweep"]
ERROR_CODES_ERROR = ["COMM_TIMEOUT", "COMM_DISCONNECTED", "COMM_INVALID_RESPONSE", "COMM_RESPONSE_TOO_LARGE",
                     "MEASUREMENT_NAN", "MEASUREMENT_INF", "INSTRUMENT_ERROR", "NOT_CONNECTED", "INTERNAL"]
ERROR_CODES_FAIL = ["OUT_OF_TOLERANCE_LOW", "OUT_OF_TOLERANCE_HIGH"]
API_ERROR_CODES = ["INVALID_ARGUMENT", "FORBIDDEN_HOST", "NOT_FOUND", "NOT_CONNECTED", "INSTRUMENT_BUSY",
                   "CONFLICT", "COMMUNICATION_ERROR", "TIMEOUT", "INTERNAL"]


def _obj(props: dict[str, Any], required: Optional[list[str]] = None, extra: bool = True) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props) if required is None else required,
            "additionalProperties": extra}


ERROR_BODY = _obj({
    "error": _obj({"code": {"enum": API_ERROR_CODES}, "message": {"type": "string", "minLength": 1},
                   "details": {"type": ["object", "null"]}}, ["code", "message"]),
}, extra=False)

CHECK = _obj({"name": {"type": "string"}, "status": {"enum": ["ok", "warn", "fail"]}, "detail": {"type": "string"}})

HEALTH = _obj({
    "status": {"enum": ["ok", "degraded", "down"]}, "version": {"type": "string"}, "time": TS,
    "uptime_s": {"type": "number", "minimum": 0}, "instruments_online": {"type": "integer", "minimum": 0},
    "instruments_total": {"type": "integer", "minimum": 0}, "running_test": STR_NULL,
    "software": _obj({"backend": {"type": "string"}, "simulator": {"type": ["string", "null"]},
                      "config_version": {"type": "string"}}),
    "checks": {"type": "array", "items": CHECK},
})

ENVIRONMENT = _obj({
    "software": _obj({"backend": {"type": "string"}, "simulator": {"type": ["string", "null"]},
                      "config_version": {"type": "string"}, "compiler": {"type": "string"},
                      "api_version": {"type": "string"}}),
    "instruments": {"type": "array", "items": _obj({"id": {"type": "string"}, "idn": STR_NULL,
                                                    "firmware": STR_NULL, "state": {"type": "string"}})},
    "calibration": {"type": "array", "items": _obj({
        "instrument_id": {"type": "string"}, "certificate": {"type": "string"},
        "calibrated_on": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "due": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}, "days_remaining": {"type": "integer"},
        "status": {"enum": ["valid", "due_soon", "expired"]}, "simulated": {"type": "boolean"}})},
    "dependencies": {"type": "array", "items": CHECK},
    "history": _obj({"runs": {"type": "integer"}, "tasks": {"type": "integer"},
                     "first_run": {"type": ["string", "null"]}, "last_run": {"type": ["string", "null"]}}),
    "config": _obj({"instruments_version": {"type": "string"}, "sequences": {"type": "integer"}}),
})

INSTRUMENT = _obj({
    "id": {"enum": ["siggen", "analyzer", "dut"]}, "name": {"type": "string"},
    "kind": {"enum": ["signal_generator", "audio_analyzer", "device_under_test"]},
    "host": {"type": "string"}, "port": {"type": "integer", "minimum": 1, "maximum": 65535},
    "state": {"enum": ["disconnected", "connecting", "connected", "error"]},
    "idn": STR_NULL, "firmware": STR_NULL, "last_error": {"type": ["string", "object", "null"]},
    "last_seen": TS_NULL, "latency_ms": NUM_NULL, "leased_by": STR_NULL,
    "calibration": {"type": ["object", "null"]}, "settings": {"type": ["object", "null"]},
})
INSTRUMENTS = _obj({"instruments": {"type": "array", "items": INSTRUMENT}})
INSTRUMENT_ONE = _obj({"instrument": INSTRUMENT})

COMMAND_RESULT = _obj({
    "id": {"type": "string"}, "command": {"type": "string"}, "is_query": {"type": "boolean"},
    "response": STR_NULL, "duration_ms": {"type": "number", "minimum": 0}, "timestamp": TS,
    "error": {"anyOf": [{"type": "null"}, _obj({"code": {"type": "integer"}, "message": {"type": "string"}})]},
}, ["id", "command", "is_query", "response", "duration_ms", "timestamp", "error"])

LIVE = _obj({
    "timestamp": TS,
    "stimulus": _obj({"function": {"type": "string"}, "frequency_hz": {"type": "number"},
                      "amplitude_vpk": {"type": "number"}, "output": {"type": "boolean"}}),
    "waveform": _obj({"sample_rate_hz": {"type": "number"}, "unit": {"const": "V"},
                      "samples": {"type": "array", "items": {"type": "number"}}}),
    "spectrum": _obj({"sample_rate_hz": {"type": "number"}, "nfft": {"type": "integer"}, "df_hz": {"type": "number"},
                      "unit": {"const": "dBV"}, "freq_hz": {"type": "array", "items": {"type": "number"}},
                      "magnitude": {"type": "array", "items": {"type": "number"}}}),
    "metrics": _obj({"rms_v": NUM_NULL, "gain_db": NUM_NULL, "thd_percent": NUM_NULL, "snr_db": NUM_NULL,
                     "noise_floor_dbv": NUM_NULL}),
    "duration_ms": {"type": "number", "minimum": 0},
    "warnings": {"type": "array", "items": {"type": "string"}},
})

PARAMETER = _obj({"key": {"type": "string"}, "label": {"type": "string"}, "unit": {"type": "string"},
                  "default": {"type": "number"}, "min": {"type": "number"}, "max": {"type": "number"}})
SEQUENCES = _obj({"sequences": {"type": "array", "items": _obj({
    "id": {"type": "string"}, "name": {"type": "string"}, "version": {"type": "string"},
    "description": {"type": "string"}, "parameters": {"type": "array", "items": PARAMETER},
    "dut": _obj({"profile": {"type": "string"}, "firmware": {"type": "string"}}),
    "steps": {"type": "array", "minItems": 1, "items": _obj({"id": {"type": "string"}, "type": {"type": "string"},
                                                            "name": {"type": "string"}})}})}})

COUNTS = _obj({k: {"type": "integer", "minimum": 0} for k in
               ["PASS", "FAIL", "ERROR", "CANCELLED", "PENDING", "RUNNING"]})
RUN_SUMMARY = _obj({
    "run_id": RUN_ID, "sequence_id": {"type": "string"}, "sequence_name": {"type": "string"}, "label": STR_NULL,
    "status": {"enum": RUN_STATUS}, "progress": {"type": "number", "minimum": 0, "maximum": 1},
    "current_step": STR_NULL, "cancel_requested": {"type": "boolean"}, "created_at": TS,
    "started_at": TS_NULL, "finished_at": TS_NULL, "duration_ms": NUM_NULL,
    "dut": _obj({"profile": {"type": "string"}, "firmware": {"type": "string"}}),
    "retries": {"type": "integer", "minimum": 0, "maximum": 5}, "counts": COUNTS,
    "error": {"anyOf": [{"type": "null"}, _obj({"code": {"type": "string"}, "message": {"type": "string"}})]},
})

TASK = _obj({
    "task_id": {"type": "string", "pattern": r"^run-\d{8}-\d{6}-[0-9a-f]{4}-T\d{3,}$"}, "run_id": RUN_ID,
    "step_id": {"type": "string"}, "test_name": {"type": "string", "minLength": 1}, "kind": {"enum": KINDS},
    "status": {"enum": TASK_STATUS}, "inputs": {"type": "object"},
    "measured": {"anyOf": [{"type": "null"}, _obj({"value": {"type": "number"}, "unit": {"type": "string"}})]},
    "limits": _obj({"min": NUM_NULL, "max": NUM_NULL, "unit": {"type": "string"}}, ["min", "max"]),
    "duration_ms": {"type": "number", "minimum": 0}, "timestamp": TS,
    "attempts": {"type": "integer", "minimum": 0}, "message": {"type": "string"},
    "error_code": {"enum": ERROR_CODES_ERROR + ERROR_CODES_FAIL + [None]},
    "dut_profile": {"type": "string"}, "dut_firmware": {"type": "string"},
})

LOG_ENTRY = _obj({"seq": {"type": "integer", "minimum": 0}, "ts": TS, "level": {"enum": ["debug", "info", "warn", "error"]},
                  "source": {"enum": ["api", "scpi", "engine", "env", "system"]}, "message": {"type": "string"},
                  "fields": {"type": ["object", "null"]}})

STEP = _obj({"id": {"type": "string"}, "name": {"type": "string"}, "type": {"type": "string"},
             "status": {"type": "string"}, "started_at": TS_NULL, "duration_ms": NUM_NULL, "message": {"type": ["string", "null"]}},
            ["id", "name", "type", "status"])

RUN_DETAIL = {**RUN_SUMMARY, "properties": {
    **RUN_SUMMARY["properties"], "parameters": {"type": "object"}, "steps": {"type": "array", "items": STEP},
    "tasks": {"type": "array", "items": TASK}, "log": {"type": "array", "items": LOG_ENTRY}},
    "required": RUN_SUMMARY["required"] + ["parameters", "steps", "tasks", "log"]}

RUN_ENVELOPE = _obj({"run": RUN_SUMMARY})
STATUS_ENVELOPE = _obj({"run": {"anyOf": [RUN_DETAIL, {"type": "null"}]}})
RESULTS = _obj({"total": {"type": "integer", "minimum": 0}, "limit": {"type": "integer"}, "offset": {"type": "integer"},
                "results": {"type": "array", "items": TASK}})
RUNS = _obj({"total": {"type": "integer", "minimum": 0}, "runs": {"type": "array", "items": RUN_SUMMARY}})
LOGS = _obj({"logs": {"type": "array", "items": LOG_ENTRY}, "last_seq": {"type": "integer", "minimum": 0}})

REPORTS = _obj({"reports": {"type": "array", "items": _obj({
    "run_id": RUN_ID, "sequence_id": {"type": "string"}, "sequence_name": {"type": "string"},
    "status": {"enum": RUN_STATUS}, "created_at": TS, "counts": COUNTS,
    "files": _obj({"csv": {"type": "string"}, "html": {"type": "string"}, "pdf": {"type": "string"}})})}})

KIND_STATS = _obj({"count": {"type": "integer"}, "pass": {"type": "integer"}, "fail": {"type": "integer"},
                   "error": {"type": "integer"}, "mean": NUM_NULL, "std": NUM_NULL, "min": NUM_NULL, "max": NUM_NULL,
                   "unit": {"type": "string"}}, ["count", "mean", "std", "min", "max", "unit"])
SUMMARY = _obj({
    "generated_at": TS,
    "runs": _obj({k: {"type": "integer", "minimum": 0} for k in ["total", "PASS", "FAIL", "ERROR", "CANCELLED"]}),
    "tasks": _obj({"total": {"type": "integer"}, "PASS": {"type": "integer"}, "FAIL": {"type": "integer"},
                   "ERROR": {"type": "integer"}, "CANCELLED": {"type": "integer"}, "pass_rate": NUM_NULL}),
    "by_kind": {"type": "object", "additionalProperties": KIND_STATS},
    "by_firmware": {"type": "array", "items": _obj({
        "firmware": {"type": "string"}, "tasks": {"type": "integer"}, "pass": {"type": "integer"},
        "fail": {"type": "integer"}, "error": {"type": "integer"}, "pass_rate": NUM_NULL,
        "by_kind": {"type": "object"}})},
    "failure_reasons": {"type": "array", "items": _obj({"reason": {"type": "string"}, "count": {"type": "integer"}})},
    "recovery": _obj({"tasks_with_retry": {"type": "integer"}, "recovered": {"type": "integer"},
                      "unrecovered": {"type": "integer"}, "recovery_rate": NUM_NULL}),
    "trend": {"type": "array", "maxItems": 500, "items": _obj({
        "timestamp": TS, "run_id": {"type": "string"}, "kind": {"enum": KINDS}, "value": {"type": "number"},
        "unit": {"type": "string"}, "status": {"enum": TASK_STATUS}, "firmware": {"type": "string"}})},
})

CSV_HEADER = ("task_id,run_id,sequence_id,step_id,test_name,kind,status,value,unit,limit_min,limit_max,"
              "frequency_hz,amplitude_vpk,attempts,duration_ms,timestamp,dut_profile,dut_firmware,error_code,message")


# --------------------------------------------------------------------------------------------
def validate(instance: Any, schema: dict[str, Any], what: str = "body") -> None:
    """Validate with jsonschema; raise AssertionError with a readable path on failure."""
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    if errors:
        e = errors[0]
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        raise AssertionError(f"{what}: schema violation at {path}: {e.message} (+{len(errors) - 1} more)")


def assert_error_body(body: Any, code: Optional[str] = None) -> dict[str, Any]:
    validate(body, ERROR_BODY, "error body")
    if code is not None:
        assert body["error"]["code"] == code, f"expected error code {code}, got {body['error']}"
    return body["error"]


def assert_task_semantics(t: dict[str, Any]) -> None:
    """Semantic invariants of one task (section 5.12): FAIL/ERROR must never be conflated."""
    status = t["status"]
    lim = t["limits"]
    m = t["measured"]
    if status in ("PASS", "FAIL"):
        assert m is not None and math.isfinite(m["value"]), f"{t['task_id']}: {status} without finite value"
        v = m["value"]
        below = lim["min"] is not None and v < lim["min"]
        above = lim["max"] is not None and v > lim["max"]
        if status == "PASS":
            assert not below and not above, f"{t['task_id']}: PASS but {v} outside [{lim['min']},{lim['max']}]"
            assert t["error_code"] is None
        else:
            assert below or above, f"{t['task_id']}: FAIL but {v} inside [{lim['min']},{lim['max']}]"
            want = "OUT_OF_TOLERANCE_LOW" if below else "OUT_OF_TOLERANCE_HIGH"
            assert t["error_code"] == want, f"{t['task_id']}: error_code {t['error_code']} != {want}"
    elif status == "ERROR":
        assert m is None, f"{t['task_id']}: ERROR with measured value"
        assert t["error_code"] in ERROR_CODES_ERROR, f"{t['task_id']}: bad ERROR code {t['error_code']}"
    elif status == "CANCELLED":
        assert m is None
        assert t["error_code"] is None
    # attempts >= 1 for every task that ran
    if status in ("PASS", "FAIL", "ERROR"):
        assert t["attempts"] >= 1


_ID_RX = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def valid_run_id(s: str) -> bool:
    return bool(_ID_RX.match(s))
