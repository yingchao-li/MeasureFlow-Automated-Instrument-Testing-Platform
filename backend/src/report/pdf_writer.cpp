#include "measureflow/report/pdf_writer.hpp"

#include <cstdio>
#include <stdexcept>

namespace mf {

namespace {

const int kHelveticaWidths[95] = {
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556,
    556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778,
    722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278,
    278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584};

std::string num(double v) {
  char buf[48];
  std::snprintf(buf, sizeof buf, "%.2f", v);
  return buf;
}

struct Decoded {
  unsigned cp;
  size_t len;
};

Decoded decode_utf8(const std::string& s, size_t i) {
  const auto b0 = static_cast<unsigned char>(s[i]);
  if (b0 < 0x80) return {b0, 1};
  if ((b0 & 0xE0) == 0xC0 && i + 1 < s.size() && (static_cast<unsigned char>(s[i + 1]) & 0xC0) == 0x80) {
    return {((b0 & 0x1Fu) << 6) | (static_cast<unsigned char>(s[i + 1]) & 0x3Fu), 2};
  }
  if ((b0 & 0xF0) == 0xE0 && i + 2 < s.size() && (static_cast<unsigned char>(s[i + 1]) & 0xC0) == 0x80 &&
      (static_cast<unsigned char>(s[i + 2]) & 0xC0) == 0x80) {
    return {((b0 & 0x0Fu) << 12) | ((static_cast<unsigned char>(s[i + 1]) & 0x3Fu) << 6) | (static_cast<unsigned char>(s[i + 2]) & 0x3Fu), 3};
  }
  if ((b0 & 0xF8) == 0xF0 && i + 3 < s.size()) return {0x10000, 4};
  return {0xFFFD, 1};
}

}  // namespace

PdfWriter::PdfWriter(double page_width, double page_height) : w_(page_width), h_(page_height) {}

const char* PdfWriter::font_name(Font f) {
  switch (f) {
    case Font::Helvetica: return "Helvetica";
    case Font::HelveticaBold: return "Helvetica-Bold";
    case Font::Courier: return "Courier";
  }
  return "Helvetica";
}

const char* PdfWriter::font_key(Font f) {
  switch (f) {
    case Font::Helvetica: return "F1";
    case Font::HelveticaBold: return "F2";
    case Font::Courier: return "F3";
  }
  return "F1";
}

int PdfWriter::add_page() {
  pages_.emplace_back();
  current_ = static_cast<int>(pages_.size()) - 1;
  return current_;
}

void PdfWriter::select_page(int index) {
  if (index < 0 || index >= static_cast<int>(pages_.size())) throw std::out_of_range("pdf page index");
  current_ = index;
}

#define MF_PDF_REQUIRE_PAGE() \
  if (current_ < 0) add_page()

void PdfWriter::set_fill(double r, double g, double b) {
  MF_PDF_REQUIRE_PAGE();
  pages_[static_cast<size_t>(current_)] += num(r) + " " + num(g) + " " + num(b) + " rg\n";
}

void PdfWriter::set_stroke(double r, double g, double b) {
  MF_PDF_REQUIRE_PAGE();
  pages_[static_cast<size_t>(current_)] += num(r) + " " + num(g) + " " + num(b) + " RG\n";
}

void PdfWriter::set_line_width(double w) {
  MF_PDF_REQUIRE_PAGE();
  pages_[static_cast<size_t>(current_)] += num(w) + " w\n";
}

void PdfWriter::set_dash(double on, double off) {
  MF_PDF_REQUIRE_PAGE();
  auto& c = pages_[static_cast<size_t>(current_)];
  if (on <= 0 && off <= 0) c += "[] 0 d\n";
  else c += "[" + num(on) + " " + num(off) + "] 0 d\n";
}

std::string PdfWriter::to_winansi(const std::string& s) {
  std::string out;
  out.reserve(s.size());
  for (size_t i = 0; i < s.size();) {
    const Decoded d = decode_utf8(s, i);
    i += d.len;
    const unsigned cp = d.cp;
    if (cp == '\t') out += ' ';
    else if (cp >= 0x20 && cp < 0x7F) out += static_cast<char>(cp);
    else if (cp >= 0xA0 && cp <= 0xFF) out += static_cast<char>(cp);
    else if (cp == 0x2013) out += static_cast<char>(0x96);
    else if (cp == 0x2014) out += static_cast<char>(0x97);
    else if (cp == 0x2018) out += static_cast<char>(0x91);
    else if (cp == 0x2019) out += static_cast<char>(0x92);
    else if (cp == 0x201C) out += static_cast<char>(0x93);
    else if (cp == 0x201D) out += static_cast<char>(0x94);
    else if (cp == 0x2022) out += static_cast<char>(0x95);
    else if (cp == 0x2026) out += static_cast<char>(0x85);
    else if (cp == 0x20AC) out += static_cast<char>(0x80);
    else if (cp < 0x20 || cp == 0x7F) out += ' ';
    else out += '?';
  }
  return out;
}

std::string PdfWriter::escape_literal(const std::string& w) {
  std::string out;
  for (char ch : w) {
    const auto c = static_cast<unsigned char>(ch);
    if (c == '\\' || c == '(' || c == ')') {
      out += '\\';
      out += static_cast<char>(c);
    } else if (c >= 0x20 && c < 0x7F) {
      out += static_cast<char>(c);
    } else {
      char buf[8];
      std::snprintf(buf, sizeof buf, "\\%03o", static_cast<unsigned>(c));
      out += buf;
    }
  }
  return out;
}

double PdfWriter::text_width(Font font, double size, const std::string& utf8) {
  const std::string w = to_winansi(utf8);
  double units = 0;
  for (char ch : w) {
    const auto c = static_cast<unsigned char>(ch);
    if (font == Font::Courier) {
      units += 600;
    } else if (c >= 32 && c <= 126) {
      units += kHelveticaWidths[c - 32];
    } else {
      units += 556;
    }
  }
  if (font == Font::HelveticaBold) units *= 1.06;
  return units * size / 1000.0;
}

void PdfWriter::text(double x, double y, Font font, double size, const std::string& utf8) {
  MF_PDF_REQUIRE_PAGE();
  pages_[static_cast<size_t>(current_)] += "BT /" + std::string(font_key(font)) + " " + num(size) + " Tf " + num(x) + " " + num(y) +
                                           " Td (" + escape_literal(to_winansi(utf8)) + ") Tj ET\n";
}

void PdfWriter::line(double x1, double y1, double x2, double y2) {
  MF_PDF_REQUIRE_PAGE();
  pages_[static_cast<size_t>(current_)] += num(x1) + " " + num(y1) + " m " + num(x2) + " " + num(y2) + " l S\n";
}

void PdfWriter::rect(double x, double y, double w, double h, bool fill, bool stroke) {
  MF_PDF_REQUIRE_PAGE();
  const char* op = fill && stroke ? "B" : (fill ? "f" : (stroke ? "S" : "n"));
  pages_[static_cast<size_t>(current_)] += num(x) + " " + num(y) + " " + num(w) + " " + num(h) + " re " + op + "\n";
}

void PdfWriter::polyline(const std::vector<std::pair<double, double>>& pts) {
  if (pts.size() < 2) return;
  MF_PDF_REQUIRE_PAGE();
  std::string s;
  for (size_t i = 0; i < pts.size(); ++i) s += num(pts[i].first) + " " + num(pts[i].second) + (i == 0 ? " m " : " l ");
  s += "S\n";
  pages_[static_cast<size_t>(current_)] += s;
}

std::string PdfWriter::render(const std::string& title, const std::string& creation_date) const {
  // Object numbering: 1 catalog, 2 pages, 3..5 fonts, 6 info, then (page, content) pairs.
  const size_t n_pages = pages_.empty() ? 1 : pages_.size();
  const size_t first_page_obj = 7;
  const size_t total_objs = 6 + 2 * n_pages;

  std::string out;
  std::vector<size_t> offsets(total_objs + 1, 0);
  auto begin_obj = [&](size_t n) {
    offsets[n] = out.size();
    out += std::to_string(n) + " 0 obj\n";
  };

  out += "%PDF-1.4\n%\xE2\xE3\xCF\xD3\n";
  begin_obj(1);
  out += "<< /Type /Catalog /Pages 2 0 R >>\nendobj\n";
  begin_obj(2);
  out += "<< /Type /Pages /Count " + std::to_string(n_pages) + " /Kids [";
  for (size_t i = 0; i < n_pages; ++i) out += (i ? " " : "") + std::to_string(first_page_obj + 2 * i) + " 0 R";
  out += "] >>\nendobj\n";
  const Font fonts[3] = {Font::Helvetica, Font::HelveticaBold, Font::Courier};
  for (size_t i = 0; i < 3; ++i) {
    begin_obj(3 + i);
    out += std::string("<< /Type /Font /Subtype /Type1 /BaseFont /") + font_name(fonts[i]) + " /Encoding /WinAnsiEncoding >>\nendobj\n";
  }
  begin_obj(6);
  out += "<< /Title (" + escape_literal(to_winansi(title)) + ") /Producer (MeasureFlow backend) /Creator (MeasureFlow)";
  if (creation_date.size() == 14) out += " /CreationDate (D:" + creation_date + "Z)";
  out += " >>\nendobj\n";

  for (size_t i = 0; i < n_pages; ++i) {
    const std::string content = pages_.empty() ? std::string() : pages_[i];
    const size_t page_obj = first_page_obj + 2 * i;
    begin_obj(page_obj);
    out += "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 " + num(w_) + " " + num(h_) + "] /Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> /Contents " +
           std::to_string(page_obj + 1) + " 0 R >>\nendobj\n";
    begin_obj(page_obj + 1);
    out += "<< /Length " + std::to_string(content.size()) + " >>\nstream\n" + content + "\nendstream\nendobj\n";
  }

  const size_t xref_pos = out.size();
  out += "xref\n0 " + std::to_string(total_objs + 1) + "\n";
  out += "0000000000 65535 f \n";
  for (size_t n = 1; n <= total_objs; ++n) {
    char buf[32];
    std::snprintf(buf, sizeof buf, "%010zu 00000 n \n", offsets[n]);
    out += buf;
  }
  out += "trailer\n<< /Size " + std::to_string(total_objs + 1) + " /Root 1 0 R /Info 6 0 R >>\nstartxref\n" + std::to_string(xref_pos) + "\n%%EOF\n";
  return out;
}

}  // namespace mf
