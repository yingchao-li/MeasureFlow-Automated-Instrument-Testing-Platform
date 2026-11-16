// Minimal hand-written PDF 1.4 writer: multi-page, base-14 fonts (Helvetica, Helvetica-Bold, Courier),
// text, lines, rectangles, polylines, solid colours. No external libraries.
//
// The output has a correct cross-reference table (byte offsets measured while writing),
// a trailer with /Root and /Info, `startxref` and `%%EOF`.
#pragma once

#include <string>
#include <utility>
#include <vector>

namespace mf {

class PdfWriter {
 public:
  enum class Font { Helvetica, HelveticaBold, Courier };

  explicit PdfWriter(double page_width = 595.28, double page_height = 841.89);

  double width() const { return w_; }
  double height() const { return h_; }

  int add_page();  // appends a page and makes it current; returns its index
  void select_page(int index);
  int page_count() const { return static_cast<int>(pages_.size()); }

  // Colours are 0..1 RGB.
  void set_fill(double r, double g, double b);
  void set_stroke(double r, double g, double b);
  void set_line_width(double w);
  void set_dash(double on, double off);  // (0,0) = solid

  // y is measured from the bottom of the page. Input is UTF-8; characters outside WinAnsi become '?'.
  void text(double x, double y, Font font, double size, const std::string& utf8);
  void line(double x1, double y1, double x2, double y2);
  void rect(double x, double y, double w, double h, bool fill, bool stroke);
  void polyline(const std::vector<std::pair<double, double>>& pts);

  // Approximate advance width in points (exact for Helvetica/Courier regular, ~6 % wider for bold).
  static double text_width(Font font, double size, const std::string& utf8);
  // Converts UTF-8 to single-byte WinAnsi (unsupported code points -> '?').
  static std::string to_winansi(const std::string& utf8);
  // Escapes a WinAnsi string as a PDF literal string body (without the parentheses); bytes >= 0x80 use octal escapes.
  static std::string escape_literal(const std::string& winansi);

  // Serialises the document. `title` and `creation_date` ("YYYYMMDDHHMMSS", UTC) go into /Info.
  std::string render(const std::string& title, const std::string& creation_date) const;

 private:
  static const char* font_name(Font f);
  static const char* font_key(Font f);

  double w_, h_;
  std::vector<std::string> pages_;  // content streams
  int current_ = -1;
};

}  // namespace mf
