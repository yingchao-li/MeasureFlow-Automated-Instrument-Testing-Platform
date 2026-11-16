// Report renderers: self-contained HTML (inline CSS + inline SVG chart) and PDF (PdfWriter).
#pragma once

#include <string>

#include "measureflow/engine/types.hpp"

namespace mf {

// Every dynamic string is HTML-escaped; the document references no external resources.
std::string run_to_html(const RunRecord& run);
std::string run_to_pdf(const RunRecord& run);

}  // namespace mf
