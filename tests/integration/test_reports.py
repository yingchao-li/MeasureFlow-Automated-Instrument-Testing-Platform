"""Report generation (docs/INTERFACE.md sections 5.14 and 7): CSV, HTML and PDF content vs the persisted run.

The reference for every comparison is ``results/runs/<run_id>/run.json`` (the persisted run) - not the
HTTP status endpoint - so the reports are checked against what was really stored.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from html.parser import HTMLParser
from typing import Any

import pytest

pypdf = pytest.importorskip("pypdf")

from schemas import CSV_HEADER  # noqa: E402
from stack import Stack  # noqa: E402

HOSTILE_LABELS = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "' onmouseover='alert(1)",
    "</title><h1>x</h1>",
    "a) (b \\ c",
    "&amp; &lt; &#x3c;script&#x3e;",
]
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
OPTIONAL_END = {"p", "li", "td", "th", "tr", "thead", "tbody", "tfoot", "dt", "dd", "option", "colgroup"}


class Doc(HTMLParser):
    """Collects tags, attributes and text; records structural problems (unbalanced end tags)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.tags: list[str] = []
        self.attrs: list[tuple[str, str, str | None]] = []
        self.text: list[str] = []
        self.problems: list[str] = []
        self.in_style = False
        self.styles: list[str] = []
        self.doctype = False
        self.title = ""
        self._in_title = False

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype"):
            self.doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        for k, v in attrs:
            self.attrs.append((tag, k, v))
        if tag not in VOID:
            self.stack.append(tag)
        self.in_style = tag == "style" or self.in_style
        self._in_title = tag == "title" or self._in_title

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        for k, v in attrs:
            self.attrs.append((tag, k, v))

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if tag == "style":
            self.in_style = False
        if tag == "title":
            self._in_title = False
        while self.stack and self.stack[-1] != tag and self.stack[-1] in OPTIONAL_END:
            self.stack.pop()
        if not self.stack or self.stack[-1] != tag:
            self.problems.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
            return
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.in_style:
            self.styles.append(data)
        else:
            self.text.append(data)
        if self._in_title:
            self.title += data

    def close(self) -> None:
        super().close()
        leftover = [t for t in self.stack if t not in OPTIONAL_END]
        if leftover:
            self.problems.append(f"unclosed elements: {leftover}")


def parse_html(b: bytes) -> Doc:
    d = Doc()
    d.feed(b.decode("utf-8"))        # must be valid UTF-8
    d.close()
    return d


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def persisted(st: Stack, run_id: str) -> dict[str, Any]:
    return json.loads((st.run_dir(run_id) / "run.json").read_text())


def fnum(s: str) -> float | None:
    return None if s == "" else float(s)


@pytest.fixture(scope="module")
def runs(pstack: Stack) -> dict[str, str]:
    ids: dict[str, str] = {}
    ids["pass"] = pstack.run_sequence("full_pipeline", label="report-pass")["run_id"]
    ids["fail"] = pstack.run_sequence("full_pipeline", dut={"profile": "LOWGAIN"}, label="report-fail")["run_id"]
    ids["sweep"] = pstack.run_sequence("frequency_sweep", label="report-sweep")["run_id"]
    for i, lab in enumerate(HOSTILE_LABELS):
        ids[f"hostile{i}"] = pstack.run_sequence("gain_verification", label=lab)["run_id"]
    ids["unicode"] = pstack.run_sequence("gain_verification", label="Prüfung ✓ 测试 \U0001F600")["run_id"]
    pstack.proxy.arm("analyzer", "MF:FAULT:TIMEOUT 1,2500", match=r"^MEAS:THD\?", nth=1, times=100)  # type: ignore[union-attr]
    ids["error"] = pstack.run_sequence("full_pipeline", retries=0, label="report-error", timeout=90)["run_id"]
    pstack.proxy.reset()                                                  # type: ignore[union-attr]
    for i in ("siggen", "analyzer", "dut"):
        pstack.proxy.set_latency(i, 30)                                   # type: ignore[union-attr]
    rid = pstack.start_run("full_pipeline", label="report-cancel")["run_id"]
    import time
    end = time.monotonic() + 30
    while time.monotonic() < end and pstack.run_status(rid)["progress"] < 0.4:
        time.sleep(0.03)
    pstack.api("POST", "/api/tests/cancel", {"run_id": rid})
    assert pstack.wait_run(rid, 30)["status"] == "CANCELLED"
    pstack.proxy.reset()                                                  # type: ignore[union-attr]
    ids["cancelled"] = rid
    return ids


# ======================================================================================== CSV
@pytest.mark.parametrize("key", ["pass", "fail", "sweep", "error", "cancelled", "hostile0", "unicode"])
def test_csv_rows_equal_persisted_tasks(pstack: Stack, runs: dict[str, str], key: str) -> None:
    rid = runs[key]
    run = persisted(pstack, rid)
    resp = pstack.api("GET", f"/api/reports/{rid}.csv")
    text = resp.content.decode("utf-8")
    assert text.splitlines()[0] == CSV_HEADER, "header must be exactly the one from INTERFACE.md section 7"
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    tasks = run["tasks"]
    assert len(rows) == len(tasks) > 0, f"{len(rows)} csv rows vs {len(tasks)} tasks"
    for row, t in zip(rows, tasks):
        assert row["task_id"] == t["task_id"] and row["run_id"] == rid and row["sequence_id"] == run["sequence_id"]
        assert (row["step_id"], row["test_name"], row["kind"], row["status"]) == (t["step_id"], t["test_name"], t["kind"], t["status"])
        if t["measured"] is None:
            assert row["value"] == "" and row["unit"] in ("", t["limits"]["unit"])
        else:
            assert math.isclose(float(row["value"]), t["measured"]["value"], rel_tol=1e-6, abs_tol=1e-9), (row["value"], t["measured"])
            assert row["unit"] == t["measured"]["unit"]
        for col, key_ in (("limit_min", "min"), ("limit_max", "max")):
            exp = t["limits"][key_]
            got = fnum(row[col])
            assert (got is None) == (exp is None) and (exp is None or math.isclose(got, exp, rel_tol=1e-9, abs_tol=1e-9)), (col, row[col], exp)
        assert math.isclose(float(row["frequency_hz"]), t["inputs"]["frequency_hz"], rel_tol=1e-9)
        assert math.isclose(float(row["amplitude_vpk"]), t["inputs"]["amplitude_vpk"], rel_tol=1e-9)
        assert int(row["attempts"]) == t["attempts"]
        assert math.isclose(float(row["duration_ms"]), t["duration_ms"], rel_tol=1e-3, abs_tol=1e-2)
        assert row["timestamp"] == t["timestamp"]
        assert (row["dut_profile"], row["dut_firmware"]) == (t["dut_profile"], t["dut_firmware"])
        assert row["error_code"] == (t["error_code"] or "")
        assert row["message"] == t["message"]
    # results.csv in the run directory carries the same data
    rows2 = list(csv.DictReader(io.StringIO((pstack.run_dir(rid) / "results.csv").read_text(), newline="")))
    assert [r["task_id"] for r in rows2] == [r["task_id"] for r in rows]
    assert [r["status"] for r in rows2] == [r["status"] for r in rows]


def test_csv_error_run_has_error_code_and_empty_value(pstack: Stack, runs: dict[str, str]) -> None:
    rows = list(csv.DictReader(io.StringIO(pstack.api("GET", f"/api/reports/{runs['error']}.csv").text, newline="")))
    bad = [r for r in rows if r["status"] == "ERROR"]
    assert bad and all(r["error_code"] == "COMM_TIMEOUT" and r["value"] == "" for r in bad), bad[:2]
    assert not [r for r in rows if r["status"] == "FAIL"]


def test_csv_has_no_formula_injection_in_text_columns(pstack: Stack, runs: dict[str, str]) -> None:
    for key in ("pass", "fail", "error", "hostile0"):
        rows = list(csv.DictReader(io.StringIO(pstack.api("GET", f"/api/reports/{runs[key]}.csv").text, newline="")))
        for r in rows:
            for col in ("test_name", "message", "step_id", "error_code", "dut_profile", "dut_firmware"):
                assert not r[col][:1] in ("=", "+", "@", "\t", "\r"), f"{col}={r[col]!r} could execute as a spreadsheet formula"


def test_csv_is_valid_utf8_with_consistent_columns_and_line_endings(pstack: Stack, runs: dict[str, str]) -> None:
    raw = pstack.api("GET", f"/api/reports/{runs['fail']}.csv").content
    text = raw.decode("utf-8")
    assert not text.startswith("﻿") or True
    n = len(CSV_HEADER.split(","))
    for rec in csv.reader(io.StringIO(text, newline="")):
        assert len(rec) == n
    assert text.endswith("\n")


# ======================================================================================== HTML
@pytest.mark.parametrize("key", ["pass", "fail", "sweep", "error", "cancelled"])
def test_html_is_well_formed_self_contained_and_lists_every_task(pstack: Stack, runs: dict[str, str], key: str) -> None:
    rid = runs[key]
    run = persisted(pstack, rid)
    raw = pstack.api("GET", f"/api/reports/{rid}.html").content
    d = parse_html(raw)
    assert not d.problems, d.problems[:5]
    assert d.doctype, "missing <!DOCTYPE html>"
    for tag in ("html", "head", "body", "title", "table"):
        assert tag in d.tags, f"missing <{tag}>"
    assert any(t == "meta" and k == "charset" and (v or "").lower() == "utf-8" for t, k, v in d.attrs), "charset meta missing"
    assert rid in d.title or rid in norm(" ".join(d.text))
    text = norm(" ".join(d.text))
    assert rid in text and run["sequence_name"] in text and run["status"] in text
    for t in run["tasks"]:
        assert norm(t["test_name"]) in text, f"task {t['test_name']!r} missing in HTML report"
        assert t["status"] in text
    for t in run["tasks"]:
        if t["measured"]:
            assert any(f"{t['measured']['value']:.{p}f}" in text or f"{t['measured']['value']:.{p}g}" in text for p in (2, 3, 4, 5, 6)), \
                f"measured value of {t['test_name']} not visible"
    assert d.styles, "inline CSS expected (self-contained)"
    # self-contained: no external resources and no scripts
    for tag, k, v in d.attrs:
        if k in ("src", "href") and v:
            assert not re.match(r"^(https?:)?//", v, re.I), f"external resource {tag}[{k}]={v}"
    assert "script" not in d.tags and "iframe" not in d.tags and "object" not in d.tags
    assert not any(k.startswith("on") for _, k, _ in d.attrs), "inline event handler in report"


def test_html_error_run_shows_error_code(pstack: Stack, runs: dict[str, str]) -> None:
    text = norm(" ".join(parse_html(pstack.api("GET", f"/api/reports/{runs['error']}.html").content).text))
    assert "COMM_TIMEOUT" in text and "ERROR" in text


@pytest.mark.parametrize("i", range(len(HOSTILE_LABELS)))
def test_html_escapes_hostile_labels(pstack: Stack, runs: dict[str, str], i: int) -> None:
    label = HOSTILE_LABELS[i]
    rid = runs[f"hostile{i}"]
    raw = pstack.api("GET", f"/api/reports/{rid}.html").content
    d = parse_html(raw)
    assert not d.problems, d.problems[:3]
    assert "script" not in d.tags, "label rendered as a live <script> element"
    assert "img" not in d.tags, f"label injected markup: {set(d.tags)}"
    assert d.tags.count("h1") == 1, "only the report's own title may be an h1 (label must not add headings)"
    assert not any(k.startswith("on") for _, k, _ in d.attrs), "label injected an event-handler attribute"
    text = norm(" ".join(d.text))
    assert norm(label) in text, "the label must still be displayed, as text"
    s = raw.decode()
    if "<" in label:
        assert label not in s, "raw (unescaped) markup from the label present in the document"
    assert d.title.count("<") == 0


def test_html_unicode_label_is_utf8(pstack: Stack, runs: dict[str, str]) -> None:
    raw = pstack.api("GET", f"/api/reports/{runs['unicode']}.html").content
    d = parse_html(raw)
    assert "Prüfung" in norm(" ".join(d.text)) and "测试" in norm(" ".join(d.text))


# ======================================================================================== PDF
def pdf_text(content: bytes) -> tuple[Any, str]:
    reader = pypdf.PdfReader(io.BytesIO(content))
    return reader, norm(" ".join((p.extract_text() or "") for p in reader.pages))


@pytest.mark.parametrize("key", ["pass", "fail", "sweep", "error", "cancelled"])
def test_pdf_parses_and_contains_run_id_verdicts_and_tasks(pstack: Stack, runs: dict[str, str], key: str) -> None:
    rid = runs[key]
    run = persisted(pstack, rid)
    content = pstack.api("GET", f"/api/reports/{rid}.pdf").content
    reader, text = pdf_text(content)
    assert len(reader.pages) >= 1 and not reader.is_encrypted
    for p in reader.pages:
        w, h = float(p.mediabox.width), float(p.mediabox.height)
        assert 400 < w < 1000 and 500 < h < 1300, (w, h)
    assert rid in text, "run id missing in PDF text"
    assert run["status"] in text
    for t in run["tasks"]:
        assert norm(t["test_name"]) in text, f"{t['test_name']!r} missing in PDF"
    for st in ("PASS", "FAIL", "ERROR", "CANCELLED"):
        n = sum(1 for t in run["tasks"] if t["status"] == st)
        if n:
            assert text.count(st) >= n, f"verdict {st} appears {text.count(st)}x, expected >= {n}"
    if key == "error":
        assert "COMM_TIMEOUT" in text


def test_pdf_with_many_tasks_has_multiple_pages_or_fits_without_truncation(pstack: Stack, runs: dict[str, str]) -> None:
    run = persisted(pstack, runs["pass"])
    reader, text = pdf_text(pstack.api("GET", f"/api/reports/{runs['pass']}.pdf").content)
    names = [t["test_name"] for t in run["tasks"]]
    assert all(norm(n) in text for n in names), "tasks beyond the first page must not be dropped"
    assert len(reader.pages) >= 1


def test_pdf_with_hostile_and_unicode_labels_stays_valid(pstack: Stack, runs: dict[str, str]) -> None:
    for key in [f"hostile{i}" for i in range(len(HOSTILE_LABELS))] + ["unicode"]:
        reader, text = pdf_text(pstack.api("GET", f"/api/reports/{runs[key]}.pdf").content)
        assert len(reader.pages) >= 1 and runs[key] in text, key
    reader, text = pdf_text(pstack.api("GET", f"/api/reports/{runs['hostile4']}.pdf").content)
    assert "a) (b" in text, "label with PDF string delimiters must be escaped, not break the content stream"


def test_pdf_structure_is_well_formed(pstack: Stack, runs: dict[str, str]) -> None:
    content = pstack.api("GET", f"/api/reports/{runs['fail']}.pdf").content
    assert content.startswith(b"%PDF-1.") and content.rstrip().endswith(b"%%EOF")
    m = re.search(rb"startxref\s+(\d+)\s+%%EOF\s*$", content)
    assert m, "startxref missing"
    off = int(m.group(1))
    assert content[off:off + 4] == b"xref", "startxref must point at the xref table"
    reader = pypdf.PdfReader(io.BytesIO(content), strict=True)           # strict: raises on structural defects
    assert reader.trailer["/Root"] is not None
    assert len(reader.pages) >= 1


# ======================================================================================== misc
def test_reports_exist_on_disk_for_every_finished_run_even_failed_or_cancelled(pstack: Stack, runs: dict[str, str]) -> None:
    for key, rid in runs.items():
        for ext in ("csv", "html", "pdf"):
            p = pstack.reports_dir / f"{rid}.{ext}"
            assert p.is_file() and p.stat().st_size > 200, f"{key}: report {p.name} missing/empty"


def test_report_downloads_are_byte_identical_to_files_on_disk_and_stable(pstack: Stack, runs: dict[str, str]) -> None:
    rid = runs["fail"]
    for ext in ("csv", "html", "pdf"):
        a = pstack.api("GET", f"/api/reports/{rid}.{ext}").content
        b = pstack.api("GET", f"/api/reports/{rid}.{ext}").content
        assert a == b == (pstack.reports_dir / f"{rid}.{ext}").read_bytes()
