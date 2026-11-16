#include "measureflow/report/report_generator.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

#include "measureflow/report/pdf_writer.hpp"
#include "measureflow/util/strings.hpp"
#include "measureflow/util/time.hpp"

namespace mf {

namespace {

struct Rgb {
  double r, g, b;
};

Rgb status_color(Status s) {
  switch (s) {
    case Status::Pass: return {0.10, 0.50, 0.22};
    case Status::Fail: return {0.81, 0.13, 0.18};
    case Status::Error: return {0.74, 0.30, 0.0};
    case Status::Cancelled: return {0.43, 0.46, 0.51};
    default: return {0.2, 0.4, 0.8};
  }
}

const char* status_css(Status s) {
  switch (s) {
    case Status::Pass: return "#1a7f37";
    case Status::Fail: return "#cf222e";
    case Status::Error: return "#bc4c00";
    case Status::Cancelled: return "#6e7781";
    default: return "#0969da";
  }
}

std::string fmt_value(const TaskResult& t) {
  if (!t.measured) return "-";
  return format_g(t.measured->value, 6) + " " + t.measured->unit;
}

std::string fmt_limits(const TaskResult& t) {
  const std::string lo = t.limits.min ? format_g(*t.limits.min, 6) : "";
  const std::string hi = t.limits.max ? format_g(*t.limits.max, 6) : "";
  if (lo.empty() && hi.empty()) return "-";
  if (lo.empty()) return "<= " + hi + " " + t.limits.unit;
  if (hi.empty()) return ">= " + lo + " " + t.limits.unit;
  return lo + " .. " + hi + " " + t.limits.unit;
}

std::string fmt_ms(double ms) {
  if (ms >= 1000.0) return format_fixed(ms / 1000.0, 2) + " s";
  return format_fixed(ms, 1) + " ms";
}

struct SweepPoint {
  double f, v;
  Status status;
};

struct SweepData {
  std::vector<SweepPoint> pts;
  std::optional<double> lo, hi;
  std::string unit;
};

SweepData sweep_of(const RunRecord& run) {
  SweepData d;
  for (const auto& t : run.tasks) {
    if (t.kind != "freq_sweep" || !t.measured || !t.inputs.frequency_hz) continue;
    d.pts.push_back({*t.inputs.frequency_hz, t.measured->value, t.status});
    d.unit = t.measured->unit;
    if (t.limits.min) d.lo = t.limits.min;
    if (t.limits.max) d.hi = t.limits.max;
  }
  std::sort(d.pts.begin(), d.pts.end(), [](const SweepPoint& a, const SweepPoint& b) { return a.f < b.f; });
  return d;
}

struct Axes {
  double fmin, fmax, ymin, ymax;
};

Axes axes_for(const SweepData& d) {
  Axes a;
  a.fmin = d.pts.front().f;
  a.fmax = d.pts.back().f;
  if (a.fmax <= a.fmin * 1.01) a.fmax = a.fmin * 2;
  a.ymin = a.ymax = d.pts.front().v;
  for (const auto& p : d.pts) {
    a.ymin = std::min(a.ymin, p.v);
    a.ymax = std::max(a.ymax, p.v);
  }
  if (d.lo) a.ymin = std::min(a.ymin, *d.lo);
  if (d.hi) a.ymax = std::max(a.ymax, *d.hi);
  const double span = std::max(a.ymax - a.ymin, 1.0);
  a.ymin -= span * 0.1;
  a.ymax += span * 0.1;
  return a;
}

double xmap(const Axes& a, double f, double x0, double w) {
  return x0 + (std::log10(f) - std::log10(a.fmin)) / (std::log10(a.fmax) - std::log10(a.fmin)) * w;
}
double ymap(const Axes& a, double v, double y0, double h) { return y0 + (v - a.ymin) / (a.ymax - a.ymin) * h; }

std::string svg_chart(const SweepData& d) {
  const double W = 640, H = 280, L = 56, R = 16, T = 16, B = 40;
  const double pw = W - L - R, ph = H - T - B;
  const Axes a = axes_for(d);
  auto X = [&](double f) { return xmap(a, f, L, pw); };
  auto Y = [&](double v) { return T + ph - ((v - a.ymin) / (a.ymax - a.ymin)) * ph; };
  std::string s = "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 640 280\" width=\"640\" height=\"280\" role=\"img\" aria-label=\"Frequency sweep chart\">";
  s += "<rect x=\"0\" y=\"0\" width=\"640\" height=\"280\" fill=\"#ffffff\"/>";
  // y grid
  for (int i = 0; i <= 4; ++i) {
    const double v = a.ymin + (a.ymax - a.ymin) * i / 4.0;
    const double y = Y(v);
    s += "<line x1=\"" + format_fixed(L, 1) + "\" y1=\"" + format_fixed(y, 1) + "\" x2=\"" + format_fixed(L + pw, 1) + "\" y2=\"" + format_fixed(y, 1) + "\" stroke=\"#d0d7de\" stroke-width=\"1\"/>";
    s += "<text x=\"" + format_fixed(L - 6, 1) + "\" y=\"" + format_fixed(y + 4, 1) + "\" font-size=\"11\" text-anchor=\"end\" fill=\"#57606a\">" + format_fixed(v, 1) + "</text>";
  }
  // x ticks at the measured frequencies
  for (const auto& p : d.pts) {
    const double x = X(p.f);
    s += "<line x1=\"" + format_fixed(x, 1) + "\" y1=\"" + format_fixed(T + ph, 1) + "\" x2=\"" + format_fixed(x, 1) + "\" y2=\"" + format_fixed(T + ph + 4, 1) + "\" stroke=\"#57606a\"/>";
    s += "<text x=\"" + format_fixed(x, 1) + "\" y=\"" + format_fixed(T + ph + 16, 1) + "\" font-size=\"10\" text-anchor=\"middle\" fill=\"#57606a\">" + format_g(p.f, 5) + "</text>";
  }
  s += "<text x=\"" + format_fixed(L + pw / 2, 1) + "\" y=\"" + format_fixed(H - 6, 1) + "\" font-size=\"11\" text-anchor=\"middle\" fill=\"#24292f\">Frequency (Hz, log scale)</text>";
  s += "<text x=\"12\" y=\"" + format_fixed(T + ph / 2, 1) + "\" font-size=\"11\" text-anchor=\"middle\" fill=\"#24292f\" transform=\"rotate(-90 12 " + format_fixed(T + ph / 2, 1) + ")\">" + html_escape(d.unit) + "</text>";
  s += "<rect x=\"" + format_fixed(L, 1) + "\" y=\"" + format_fixed(T, 1) + "\" width=\"" + format_fixed(pw, 1) + "\" height=\"" + format_fixed(ph, 1) + "\" fill=\"none\" stroke=\"#8c959f\"/>";
  auto limit_line = [&](double v, const char* label) {
    const double y = Y(v);
    s += "<line x1=\"" + format_fixed(L, 1) + "\" y1=\"" + format_fixed(y, 1) + "\" x2=\"" + format_fixed(L + pw, 1) + "\" y2=\"" + format_fixed(y, 1) + "\" stroke=\"#cf222e\" stroke-width=\"1.2\" stroke-dasharray=\"6 4\"/>";
    s += "<text x=\"" + format_fixed(L + pw - 4, 1) + "\" y=\"" + format_fixed(y - 3, 1) + "\" font-size=\"10\" text-anchor=\"end\" fill=\"#cf222e\">" + label + " " + format_g(v, 5) + "</text>";
  };
  if (d.lo) limit_line(*d.lo, "min");
  if (d.hi) limit_line(*d.hi, "max");
  std::string pts;
  for (const auto& p : d.pts) pts += format_fixed(X(p.f), 1) + "," + format_fixed(Y(p.v), 1) + " ";
  s += "<polyline points=\"" + pts + "\" fill=\"none\" stroke=\"#0969da\" stroke-width=\"2\"/>";
  for (const auto& p : d.pts) {
    s += std::string("<circle cx=\"") + format_fixed(X(p.f), 1) + "\" cy=\"" + format_fixed(Y(p.v), 1) + "\" r=\"4\" fill=\"" + status_css(p.status) + "\" stroke=\"#ffffff\" stroke-width=\"1\"/>";
  }
  s += "</svg>";
  return s;
}

std::string td(const std::string& v, const std::string& cls = {}) {
  return std::string("<td") + (cls.empty() ? "" : " class=\"" + cls + "\"") + ">" + html_escape(v) + "</td>";
}

std::string badge(Status s) { return std::string("<span class=\"badge\" style=\"background:") + status_css(s) + "\">" + to_string(s) + "</span>"; }

}  // namespace

std::string run_to_html(const RunRecord& run) {
  const RunCounts c = count_tasks(run);
  std::string h;
  h += "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">";
  h += "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">";
  h += "<title>MeasureFlow report " + html_escape(run.run_id) + "</title><style>";
  h += "body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:0;background:#f6f8fa;color:#24292f}";
  h += "main{max-width:1040px;margin:0 auto;padding:24px}";
  h += "h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px;border-bottom:1px solid #d0d7de;padding-bottom:4px}";
  h += ".card{background:#fff;border:1px solid #d0d7de;border-radius:8px;padding:16px;margin-top:12px;overflow-x:auto}";
  h += ".badge{display:inline-block;color:#fff;border-radius:12px;padding:2px 10px;font-size:12px;font-weight:600}";
  h += "table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #eaeef2;padding:6px 8px;text-align:left;vertical-align:top}";
  h += "th{background:#f6f8fa;font-weight:600}td.num{text-align:right;font-variant-numeric:tabular-nums}";
  h += "dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:0;font-size:13px}dt{color:#57606a}dd{margin:0}";
  h += "code,.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}.muted{color:#57606a;font-size:12px}";
  h += "@media print{body{background:#fff}.card{border:none;padding:0}}";
  h += "</style></head><body><main>";
  h += "<h1>MeasureFlow Test Report</h1>";
  h += "<div>" + badge(run.status) + " <span class=\"mono\">" + html_escape(run.run_id) + "</span></div>";
  h += "<div class=\"card\"><dl>";
  auto row = [&](const std::string& k, const std::string& v) { h += "<dt>" + html_escape(k) + "</dt><dd>" + html_escape(v) + "</dd>"; };
  row("Sequence", run.sequence_name + " (" + run.sequence_id + (run.sequence_version.empty() ? "" : " v" + run.sequence_version) + ")");
  if (!run.label.empty()) row("Label", run.label);
  row("DUT", run.dut.profile + " / firmware " + run.dut.firmware);
  row("Created", run.created_at);
  row("Started", run.started_at.empty() ? "-" : run.started_at);
  row("Finished", run.finished_at.empty() ? "-" : run.finished_at);
  row("Duration", fmt_ms(run.duration_ms));
  row("Task retries allowed", std::to_string(run.retries));
  row("Results", std::to_string(c.pass) + " PASS, " + std::to_string(c.fail) + " FAIL, " + std::to_string(c.error) + " ERROR, " + std::to_string(c.cancelled) + " CANCELLED");
  if (run.error) row("Run error", run.error->code + ": " + run.error->message);
  h += "</dl></div>";

  if (!run.parameters.empty()) {
    h += "<h2>Parameters</h2><div class=\"card\"><table><tr><th>Name</th><th>Value</th></tr>";
    for (const auto& kv : run.parameters) h += "<tr>" + td(kv.first, "mono") + td(format_g(kv.second, 9), "mono") + "</tr>";
    h += "</table></div>";
  }

  h += "<h2>Steps</h2><div class=\"card\"><table><tr><th>Step</th><th>Type</th><th>Status</th><th>Duration</th><th>Message</th></tr>";
  for (const auto& s : run.steps) {
    h += "<tr>" + td(s.name) + td(s.type, "mono") + "<td>" + badge(s.status) + "</td>" + td(fmt_ms(s.duration_ms)) + td(s.message) + "</tr>";
  }
  h += "</table></div>";

  h += "<h2>Measurements</h2><div class=\"card\"><table><tr><th>#</th><th>Test</th><th>Kind</th><th>Value</th><th>Limits</th><th>Status</th><th>Attempts</th><th>Message</th></tr>";
  int n = 0;
  for (const auto& t : run.tasks) {
    h += "<tr>" + td(std::to_string(++n)) + td(t.test_name) + td(t.kind, "mono") + td(fmt_value(t), "num") + td(fmt_limits(t), "num") +
         "<td>" + badge(t.status) + "</td>" + td(std::to_string(t.attempts), "num") +
         td(t.error_code.empty() ? t.message : t.error_code + ": " + t.message) + "</tr>";
  }
  if (run.tasks.empty()) h += "<tr><td colspan=\"8\" class=\"muted\">No measurements were recorded.</td></tr>";
  h += "</table></div>";

  const SweepData sw = sweep_of(run);
  if (!sw.pts.empty()) {
    h += "<h2>Frequency sweep</h2><div class=\"card\">" + svg_chart(sw) + "<div class=\"muted\">Dashed lines: tolerance limits. Marker colour = task status.</div></div>";
  }

  h += "<p class=\"muted\">Generated by MeasureFlow. All instruments are simulated; results are for demonstration only and not valid for real hardware or medical devices.</p>";
  h += "</main></body></html>\n";
  return h;
}

// ---------------------------------------------------------------------------------------------- PDF

namespace {

using Font = PdfWriter::Font;

std::string fit(Font f, double size, const std::string& text, double max_w) {
  if (PdfWriter::text_width(f, size, text) <= max_w) return text;
  std::string t = text;
  while (!t.empty() && PdfWriter::text_width(f, size, t + "...") > max_w) {
    // drop a whole UTF-8 character
    size_t cut = t.size() - 1;
    while (cut > 0 && (static_cast<unsigned char>(t[cut]) & 0xC0) == 0x80) --cut;
    t.erase(cut);
  }
  return t + "...";
}

class PdfReport {
 public:
  explicit PdfReport(const RunRecord& run) : run_(run) {}

  std::string build() {
    new_page();
    title_block();
    meta_block();
    steps_table();
    tasks_table();
    sweep_chart();
    footers();
    return pdf_.render("MeasureFlow report " + run_.run_id, creation_stamp());
  }

 private:
  static constexpr double kMargin = 40;
  static constexpr double kRow = 15;

  void new_page() {
    pdf_.add_page();
    y_ = pdf_.height() - kMargin;
  }

  void ensure(double needed) {
    if (y_ - needed < kMargin + 20) {
      new_page();
      pdf_.set_fill(0.35, 0.38, 0.42);
      pdf_.text(kMargin, y_ - 10, Font::Helvetica, 9, "MeasureFlow report - " + run_.run_id + " (continued)");
      y_ -= 24;
    }
  }

  void section(const std::string& title) {
    ensure(40);
    y_ -= 10;
    pdf_.set_fill(0.14, 0.16, 0.18);
    pdf_.text(kMargin, y_ - 12, Font::HelveticaBold, 12, title);
    pdf_.set_stroke(0.82, 0.84, 0.87);
    pdf_.set_line_width(0.6);
    pdf_.line(kMargin, y_ - 16, pdf_.width() - kMargin, y_ - 16);
    y_ -= 26;
  }

  void title_block() {
    pdf_.set_fill(0.04, 0.41, 0.85);
    pdf_.rect(0, pdf_.height() - 64, pdf_.width(), 64, true, false);
    pdf_.set_fill(1, 1, 1);
    pdf_.text(kMargin, pdf_.height() - 36, Font::HelveticaBold, 20, "MeasureFlow Test Report");
    pdf_.text(kMargin, pdf_.height() - 53, Font::Courier, 10, run_.run_id);
    const Rgb c = status_color(run_.status);
    const std::string st = to_string(run_.status);
    const double bw = PdfWriter::text_width(Font::HelveticaBold, 12, st) + 20;
    pdf_.set_fill(c.r, c.g, c.b);
    pdf_.rect(pdf_.width() - kMargin - bw, pdf_.height() - 44, bw, 22, true, false);
    pdf_.set_fill(1, 1, 1);
    pdf_.text(pdf_.width() - kMargin - bw + 10, pdf_.height() - 38, Font::HelveticaBold, 12, st);
    y_ = pdf_.height() - 64;
  }

  void kv(const std::string& k, const std::string& v) {
    ensure(kRow);
    pdf_.set_fill(0.35, 0.38, 0.42);
    pdf_.text(kMargin, y_ - 11, Font::Helvetica, 9.5, k);
    pdf_.set_fill(0.1, 0.12, 0.14);
    pdf_.text(kMargin + 130, y_ - 11, Font::Helvetica, 9.5, fit(Font::Helvetica, 9.5, v, pdf_.width() - 2 * kMargin - 130));
    y_ -= kRow;
  }

  void meta_block() {
    const RunCounts c = count_tasks(run_);
    section("Summary");
    kv("Sequence", run_.sequence_name + " (" + run_.sequence_id + (run_.sequence_version.empty() ? "" : " v" + run_.sequence_version) + ")");
    if (!run_.label.empty()) kv("Label", run_.label);
    kv("DUT", run_.dut.profile + " / firmware " + run_.dut.firmware);
    kv("Created", run_.created_at);
    kv("Started / finished", (run_.started_at.empty() ? "-" : run_.started_at) + "  /  " + (run_.finished_at.empty() ? "-" : run_.finished_at));
    kv("Duration", fmt_ms(run_.duration_ms));
    kv("Task retries allowed", std::to_string(run_.retries));
    kv("Results", std::to_string(c.pass) + " PASS, " + std::to_string(c.fail) + " FAIL, " + std::to_string(c.error) + " ERROR, " + std::to_string(c.cancelled) + " CANCELLED");
    if (run_.error) kv("Run error", run_.error->code + ": " + run_.error->message);
    if (!run_.parameters.empty()) {
      std::string p;
      for (const auto& kvp : run_.parameters) p += (p.empty() ? "" : ", ") + kvp.first + "=" + format_g(kvp.second, 6);
      kv("Parameters", p);
    }
  }

  struct Col {
    const char* title;
    double x;  // offset from the left margin
    double w;
  };

  void header_row(const std::vector<Col>& cols) {
    ensure(kRow + 4);
    pdf_.set_fill(0.93, 0.95, 0.96);
    pdf_.rect(kMargin, y_ - kRow, pdf_.width() - 2 * kMargin, kRow, true, false);
    pdf_.set_fill(0.1, 0.12, 0.14);
    for (const auto& c : cols) pdf_.text(kMargin + c.x + 3, y_ - 11, Font::HelveticaBold, 8.5, c.title);
    y_ -= kRow;
  }

  void cell(const Col& c, const std::string& text, Font f = Font::Helvetica, double size = 8.5) {
    pdf_.text(kMargin + c.x + 3, y_ - 11, f, size, fit(f, size, text, c.w - 6));
  }

  void row_rule() {
    pdf_.set_stroke(0.9, 0.92, 0.94);
    pdf_.set_line_width(0.4);
    pdf_.line(kMargin, y_, pdf_.width() - kMargin, y_);
  }

  void status_cell(const Col& c, Status s) {
    const Rgb col = status_color(s);
    pdf_.set_fill(col.r, col.g, col.b);
    cell(c, to_string(s), Font::HelveticaBold, 8.5);
    pdf_.set_fill(0.1, 0.12, 0.14);
  }

  void steps_table() {
    section("Steps");
    std::vector<Col> c = {{"Step", 0, 150}, {"Type", 150, 90}, {"Status", 240, 70}, {"Duration", 310, 60}, {"Message", 370, 145}};
    header_row(c);
    for (const auto& s : run_.steps) {
      ensure(kRow);
      pdf_.set_fill(0.1, 0.12, 0.14);
      cell(c[0], s.name);
      cell(c[1], s.type, Font::Courier, 8);
      status_cell(c[2], s.status);
      pdf_.set_fill(0.1, 0.12, 0.14);
      cell(c[3], fmt_ms(s.duration_ms));
      cell(c[4], s.message);
      y_ -= kRow;
      row_rule();
    }
  }

  void tasks_table() {
    section("Measurements");
    std::vector<Col> c = {{"#", 0, 22}, {"Test", 22, 135}, {"Value", 157, 78}, {"Limits", 235, 98}, {"Status", 333, 62}, {"Att.", 395, 24}, {"Message", 419, 96}};
    header_row(c);
    if (run_.tasks.empty()) {
      pdf_.set_fill(0.35, 0.38, 0.42);
      pdf_.text(kMargin + 3, y_ - 11, Font::Helvetica, 9, "No measurements were recorded.");
      y_ -= kRow;
      return;
    }
    int n = 0;
    for (const auto& t : run_.tasks) {
      if (y_ - kRow < kMargin + 20) {
        ensure(kRow + 40);
        header_row(c);
      }
      pdf_.set_fill(0.1, 0.12, 0.14);
      cell(c[0], std::to_string(++n));
      cell(c[1], t.test_name);
      cell(c[2], fmt_value(t));
      cell(c[3], fmt_limits(t));
      status_cell(c[4], t.status);
      pdf_.set_fill(0.1, 0.12, 0.14);
      cell(c[5], std::to_string(t.attempts));
      cell(c[6], t.error_code.empty() ? t.message : t.error_code);
      y_ -= kRow;
      row_rule();
    }
  }

  void sweep_chart() {
    const SweepData d = sweep_of(run_);
    if (d.pts.empty()) return;
    const double ch = 170, cw = pdf_.width() - 2 * kMargin;
    section("Frequency sweep");
    ensure(ch + 30);
    const double x0 = kMargin + 40, w = cw - 56, y0 = y_ - ch + 22, h = ch - 40;
    const Axes a = axes_for(d);
    pdf_.set_stroke(0.55, 0.58, 0.62);
    pdf_.set_line_width(0.6);
    pdf_.set_dash(0, 0);
    pdf_.rect(x0, y0, w, h, false, true);
    pdf_.set_fill(0.35, 0.38, 0.42);
    for (int i = 0; i <= 4; ++i) {
      const double v = a.ymin + (a.ymax - a.ymin) * i / 4.0;
      const double y = ymap(a, v, y0, h);
      pdf_.set_stroke(0.85, 0.87, 0.9);
      pdf_.line(x0, y, x0 + w, y);
      pdf_.text(x0 - 30, y - 3, Font::Helvetica, 7.5, format_fixed(v, 1));
    }
    for (const auto& p : d.pts) {
      const double x = xmap(a, p.f, x0, w);
      pdf_.set_stroke(0.55, 0.58, 0.62);
      pdf_.line(x, y0, x, y0 - 3);
      pdf_.text(x - 8, y0 - 12, Font::Helvetica, 7, format_g(p.f, 5));
    }
    pdf_.text(x0 + w / 2 - 50, y0 - 22, Font::Helvetica, 8, "Frequency (Hz, log scale)  /  " + d.unit);
    pdf_.set_stroke(0.81, 0.13, 0.18);
    pdf_.set_dash(4, 3);
    if (d.lo) pdf_.line(x0, ymap(a, *d.lo, y0, h), x0 + w, ymap(a, *d.lo, y0, h));
    if (d.hi) pdf_.line(x0, ymap(a, *d.hi, y0, h), x0 + w, ymap(a, *d.hi, y0, h));
    pdf_.set_dash(0, 0);
    pdf_.set_stroke(0.04, 0.41, 0.85);
    pdf_.set_line_width(1.4);
    std::vector<std::pair<double, double>> pts;
    for (const auto& p : d.pts) pts.emplace_back(xmap(a, p.f, x0, w), ymap(a, p.v, y0, h));
    pdf_.polyline(pts);
    for (size_t i = 0; i < d.pts.size(); ++i) {
      const Rgb c = status_color(d.pts[i].status);
      pdf_.set_fill(c.r, c.g, c.b);
      pdf_.rect(pts[i].first - 2.2, pts[i].second - 2.2, 4.4, 4.4, true, false);
    }
    pdf_.set_line_width(0.6);
    y_ -= ch + 6;
  }

  void footers() {
    const int n = pdf_.page_count();
    for (int i = 0; i < n; ++i) {
      pdf_.select_page(i);
      pdf_.set_fill(0.45, 0.48, 0.52);
      pdf_.text(kMargin, 24, Font::Helvetica, 7.5, "Generated by MeasureFlow - simulated instruments, not valid for real hardware or medical devices.");
      const std::string pg = "Page " + std::to_string(i + 1) + " of " + std::to_string(n);
      pdf_.text(pdf_.width() - kMargin - PdfWriter::text_width(Font::Helvetica, 7.5, pg), 24, Font::Helvetica, 7.5, pg);
    }
  }

  std::string creation_stamp() const {
    std::string c = compact_stamp(SystemClock::now());  // YYYYMMDD-HHMMSS
    c.erase(8, 1);
    return c;
  }

  const RunRecord& run_;
  PdfWriter pdf_;
  double y_ = 0;
};

}  // namespace

std::string run_to_pdf(const RunRecord& run) { return PdfReport(run).build(); }

}  // namespace mf
