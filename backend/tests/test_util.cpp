// util: strict number parsing, string helpers (CSV/HTML escaping), dates, ids, atomic file writes, logger.
#include <cmath>
#include <filesystem>
#include <fstream>
#include <limits>
#include <set>
#include <sstream>
#include <thread>

#include "catch_amalgamated.hpp"
#include "fake_scpi.hpp"
#include "measureflow/util/errors.hpp"
#include "measureflow/util/fs.hpp"
#include "measureflow/util/ids.hpp"
#include "measureflow/util/logger.hpp"
#include "measureflow/util/strings.hpp"
#include "measureflow/util/time.hpp"

using namespace mf;
namespace fs = std::filesystem;

TEST_CASE("parse_number_strict accepts only the SCPI numeric grammar", "[util][parse]") {
  SECTION("valid numbers") {
    CHECK(parse_number_strict("1000")->value == 1000.0);
    CHECK(parse_number_strict("  -0.5 ")->value == -0.5);
    CHECK(parse_number_strict("+1.5e-3")->value == Catch::Approx(0.0015));
    CHECK(parse_number_strict(".25")->value == 0.25);
    CHECK(parse_number_strict("3.")->value == 3.0);
    CHECK(parse_number_strict("1E3")->value == 1000.0);
  }
  SECTION("textual non-finite values are classified, not rejected") {
    CHECK(parse_number_strict("NAN")->cls == NumberClass::NaN);
    CHECK(parse_number_strict("nan")->cls == NumberClass::NaN);
    CHECK(parse_number_strict("INF")->cls == NumberClass::PosInf);
    CHECK(parse_number_strict("+Inf")->cls == NumberClass::PosInf);
    CHECK(parse_number_strict("-INF")->cls == NumberClass::NegInf);
    CHECK(std::isinf(parse_number_strict("-INF")->value));
    CHECK_FALSE(parse_number_strict("NAN")->is_finite());
  }
  SECTION("garbage is rejected") {
    for (const char* bad : {"", " ", "abc", "1,5", "1e", "e5", "0x10", "1 2", "--1", "+-1", ".", "1.2.3", "#!GARBAGE~~", "1e+", "∞", "1\x01"}) {
      INFO("input: " << bad);
      CHECK_FALSE(parse_number_strict(bad).has_value());
    }
  }
  SECTION("overflow is not silently turned into a number") {
    const auto huge = parse_number_strict("1e999");
    CHECK((!huge.has_value() || !huge->is_finite()));
  }
  SECTION("parse_finite_strict rejects NaN and Inf") {
    CHECK(parse_finite_strict("2.5").value() == 2.5);
    CHECK_FALSE(parse_finite_strict("NAN").has_value());
    CHECK_FALSE(parse_finite_strict("INF").has_value());
  }
}

TEST_CASE("parse_int_strict enforces range and syntax", "[util][parse]") {
  CHECK(parse_int_strict("42", 0, 100) == 42);
  CHECK(parse_int_strict("+7", 0, 100) == 7);
  CHECK(parse_int_strict("-3", -5, 5) == -3);
  CHECK_FALSE(parse_int_strict("101", 0, 100).has_value());
  CHECK_FALSE(parse_int_strict("1.0", 0, 100).has_value());
  CHECK_FALSE(parse_int_strict("12abc", 0, 100).has_value());
  CHECK_FALSE(parse_int_strict("", 0, 100).has_value());
  CHECK_FALSE(parse_int_strict("99999999999999999999", 0, 100).has_value());
}

TEST_CASE("string helpers", "[util][strings]") {
  CHECK(trim("  a b \t\r\n") == "a b");
  CHECK(to_upper("sOur:Freq") == "SOUR:FREQ");
  CHECK(split("a,b,,c", ',') == std::vector<std::string>{"a", "b", "", "c"});
  CHECK(is_printable_ascii("SOUR:FREQ 1000"));
  CHECK_FALSE(is_printable_ascii("a\nb"));
  CHECK_FALSE(is_printable_ascii(std::string("a\0b", 3)));
  CHECK_FALSE(is_printable_ascii("caf\xC3\xA9"));
  CHECK(is_valid_id("run-20261116-120000-ab12"));
  CHECK_FALSE(is_valid_id(""));
  CHECK_FALSE(is_valid_id("../etc"));
  CHECK_FALSE(is_valid_id("a/b"));
  CHECK_FALSE(is_valid_id(std::string(65, 'a')));
  CHECK(format_g(0.1 + 0.2, 6) == "0.3");
  CHECK(format_g(std::nan(""), 6) == "NaN");
  CHECK(format_fixed(1.0 / 3.0, 2) == "0.33");
  CHECK(format_fixed(std::numeric_limits<double>::infinity(), 2) == "Inf");
}

TEST_CASE("csv_escape follows RFC 4180 and defuses spreadsheet formulas", "[util][csv]") {
  CHECK(csv_escape("plain") == "plain");
  CHECK(csv_escape("a,b") == "\"a,b\"");
  CHECK(csv_escape("say \"hi\"") == "\"say \"\"hi\"\"\"");
  CHECK(csv_escape("line1\nline2") == "\"line1\nline2\"");
  CHECK(csv_escape("=SUM(A1:A2)") == "'=SUM(A1:A2)");
  CHECK(csv_escape("+1+1") == "'+1+1");
  CHECK(csv_escape("@cmd") == "'@cmd");
  CHECK(csv_escape("-5 dB") == "'-5 dB");
  CHECK(csv_escape("=1,2") == "\"'=1,2\"");
  // numeric cells are not text cells: a negative number must stay a number
  CHECK(csv_escape("-5.5", false) == "-5.5");
}

TEST_CASE("html_escape neutralises markup", "[util][html]") {
  CHECK(html_escape("<script>alert('x')</script>") == "&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt;");
  CHECK(html_escape("a & b \"q\"") == "a &amp; b &quot;q&quot;");
  CHECK(html_escape("plain text") == "plain text");
  const std::string out = html_escape("<img src=x onerror=alert(1)>");
  CHECK(out.find('<') == std::string::npos);
  CHECK(out.find('>') == std::string::npos);
}

TEST_CASE("truncate_utf8 never cuts a multibyte sequence", "[util][strings]") {
  CHECK(truncate_utf8("short", 10) == "short");
  CHECK(truncate_utf8("abcdefghij", 8) == "abcde...");
  const std::string s = "ab\xC3\xA9\xC3\xA9\xC3\xA9\xC3\xA9";  // ab + 4x e-acute (10 bytes)
  const std::string t = truncate_utf8(s, 7);
  // result must be valid UTF-8: no dangling continuation byte before the ellipsis
  const std::string body = t.substr(0, t.size() - 3);
  for (size_t i = 0; i < body.size(); ++i) {
    if ((static_cast<unsigned char>(body[i]) & 0xC0) == 0x80) {
      REQUIRE(i > 0);
      CHECK((static_cast<unsigned char>(body[i - 1]) & 0x80) != 0);
    }
  }
  CHECK(body.size() % 2 == 0);  // 2 ascii chars + whole 2-byte characters
}

TEST_CASE("civil date arithmetic and ISO parsing", "[util][time]") {
  CHECK(days_from_civil(1970, 1, 1) == 0);
  CHECK(days_from_civil(2000, 3, 1) - days_from_civil(2000, 2, 28) == 2);  // leap year
  CHECK(days_from_civil(1900, 3, 1) - days_from_civil(1900, 2, 28) == 1);  // not a leap year
  CHECK(date_from_days(days_from_civil(2027, 10, 1)) == "2027-10-01");
  CHECK(parse_iso_date("2024-02-29").has_value());
  CHECK_FALSE(parse_iso_date("2023-02-29").has_value());
  CHECK_FALSE(parse_iso_date("2024-13-01").has_value());
  CHECK_FALSE(parse_iso_date("2024-00-10").has_value());
  CHECK_FALSE(parse_iso_date("2024-1-1").has_value());
  CHECK_FALSE(parse_iso_date("2024-01-01x").has_value());
  CHECK(*parse_iso_date("1970-01-02") == 1);
  CHECK(*parse_iso_millis("1970-01-01T00:00:01.250Z") == 1250);
  CHECK(*parse_iso_millis("1970-01-01T00:01:00Z") == 60000);
  CHECK_FALSE(parse_iso_millis("1970-01-01 00:00:01").has_value());
  CHECK_FALSE(parse_iso_millis("1970-01-01T25:00:00Z").has_value());
  const std::string now = iso_now();
  CHECK(now.size() == 24);
  CHECK(now.back() == 'Z');
  CHECK(parse_iso_millis(now).has_value());
  CHECK(today_days() > days_from_civil(2025, 1, 1));
}

TEST_CASE("run ids are well formed and unique", "[util][ids]") {
  std::set<std::string> seen;
  for (int i = 0; i < 200; ++i) {
    const std::string id = make_run_id();
    CHECK(is_valid_id(id));
    CHECK(id.rfind("run-", 0) == 0);
    seen.insert(id);
  }
  CHECK(seen.size() > 150);  // 16 bit suffix within one second: collisions are possible but rare
  CHECK(make_task_id("run-x", 7) == "run-x-T007");
}

TEST_CASE("error codes map to the documented HTTP status", "[util][errors]") {
  CHECK(http_status(ErrorCode::InvalidArgument) == 400);
  CHECK(http_status(ErrorCode::ForbiddenHost) == 403);
  CHECK(http_status(ErrorCode::NotFound) == 404);
  CHECK(http_status(ErrorCode::NotConnected) == 409);
  CHECK(http_status(ErrorCode::InstrumentBusy) == 409);
  CHECK(http_status(ErrorCode::Conflict) == 409);
  CHECK(http_status(ErrorCode::CommunicationError) == 502);
  CHECK(http_status(ErrorCode::Timeout) == 504);
  CHECK(http_status(ErrorCode::Internal) == 500);
  CHECK(std::string(to_string(ErrorCode::InstrumentBusy)) == "INSTRUMENT_BUSY");
  const MfError e(ErrorCode::InvalidArgument, "bad", "field_x", "kind_y");
  CHECK(e.field() == "field_x");
  CHECK(e.kind() == "kind_y");
  CHECK(std::string(e.what()) == "bad");
}

TEST_CASE("atomic_write_file replaces content without leaving temp files", "[util][fs]") {
  mftest::TempRoot root("{}", false);
  const fs::path dir = fs::path(root.path()) / "results";
  const fs::path file = dir / "a.json";
  atomic_write_file(file, "first");
  CHECK(read_file(file).value() == "first");
  atomic_write_file(file, "second, longer content");
  CHECK(read_file(file).value() == "second, longer content");
  int entries = 0;
  for (const auto& e : fs::directory_iterator(dir)) {
    (void)e;
    ++entries;
  }
  CHECK(entries == 1);  // no leftover ".tmp" siblings
  CHECK_FALSE(read_file(dir / "missing.json").has_value());
  CHECK(ensure_dir(dir / "x" / "y"));
  CHECK(dir_writable(dir));
  atomic_write_file(dir / "plain-file", "x");
  CHECK_FALSE(dir_writable(dir / "plain-file" / "sub"));  // a directory cannot be created below a regular file
}

TEST_CASE("read_file enforces the size limit", "[util][fs]") {
  mftest::TempRoot root("{}", false);
  const fs::path file = fs::path(root.path()) / "big.txt";
  atomic_write_file(file, std::string(2000, 'x'));
  CHECK(read_file(file, 4096).has_value());
  CHECK_FALSE(read_file(file, 1000).has_value());
}

TEST_CASE("logger ring buffer, filters and per-run capture", "[util][logger]") {
  Logger log(5);
  log.set_min_level(LogLevel::Debug);
  for (int i = 0; i < 8; ++i) log.info("api", "msg " + std::to_string(i));
  const auto all = log.query({});
  REQUIRE(all.size() == 5);  // bounded ring: oldest dropped
  CHECK(all.front().message == "msg 3");
  CHECK(all.back().message == "msg 7");
  CHECK(all.front().seq < all.back().seq);

  Logger l2;
  l2.set_min_level(LogLevel::Debug);
  l2.debug("scpi", "d");
  l2.warn("engine", "w");
  l2.error("scpi", "e");
  LogQuery q;
  q.min_level = LogLevel::Warn;
  CHECK(l2.query(q).size() == 2);
  q = {};
  q.source = "scpi";
  CHECK(l2.query(q).size() == 2);
  q = {};
  q.since_seq = l2.last_seq() - 1;
  CHECK(l2.query(q).size() == 1);
  q = {};
  q.limit = 1;
  CHECK(l2.query(q).size() == 1);

  l2.open_run_capture("run-a", 3);
  for (int i = 0; i < 5; ++i) l2.info("engine", "r" + std::to_string(i), {}, "run-a");
  l2.info("engine", "other", {}, "run-b");
  const auto tail = l2.run_tail("run-a", 2);
  REQUIRE(tail.size() == 2);
  CHECK(tail.back().message == "r4");
  const auto closed = l2.close_run_capture("run-a");
  CHECK(closed.size() == 3);  // capture capacity
  CHECK(l2.run_tail("run-a", 0).empty());
}

TEST_CASE("logger respects the minimum level and writes parsable JSON lines", "[util][logger]") {
  mftest::TempRoot root("{}", false);
  Logger log;
  log.set_min_level(LogLevel::Warn);
  log.info("api", "dropped");
  log.warn("api", "kept \"quoted\"\n", {{"n", int64_t{3}}, {"s", std::string("x")}, {"ok", true}, {"d", 1.5}});
  const auto entries = log.query({});
  REQUIRE(entries.size() == 1);
  const std::string line = Logger::to_json_line(entries[0]);
  CHECK(line.find('\n') == std::string::npos);  // one record per line even when the message contains a newline
  CHECK(line.find("\"level\":\"warn\"") != std::string::npos);
  CHECK(line.find("\\\"quoted\\\"") != std::string::npos);
  CHECK(Logger::to_text_line(entries[0]).find("kept") != std::string::npos);
  CHECK(parse_log_level("warn") == LogLevel::Warn);
  CHECK_FALSE(parse_log_level("loud").has_value());
}

TEST_CASE("logger file sink rotates and keeps a bounded number of files", "[util][logger]") {
  mftest::TempRoot root("{}", false);
  const fs::path file = fs::path(root.path()) / "logs" / "backend.log";
  fs::create_directories(file.parent_path());
  Logger log;
  REQUIRE(log.open_file(file, 2000, 2));
  for (int i = 0; i < 200; ++i) log.info("system", "line number " + std::to_string(i) + " with some padding text");
  int files = 0;
  for (const auto& e : fs::directory_iterator(file.parent_path())) {
    (void)e;
    ++files;
  }
  CHECK(files >= 2);
  CHECK(files <= 3);  // current + `keep` rotated files
  CHECK(fs::file_size(file) <= 2000 + 400);
  atomic_write_file(fs::path(root.path()) / "results" / "plain-file", "x");
  Logger bad;
  CHECK_FALSE(bad.open_file(fs::path(root.path()) / "results" / "plain-file" / "x.log"));
  bad.info("system", "still works in memory");
  CHECK(bad.query({}).size() == 1);
}

TEST_CASE("logger is safe under concurrent writers", "[util][logger]") {
  Logger log(10000);
  std::vector<std::thread> ts;
  for (int t = 0; t < 4; ++t) {
    ts.emplace_back([&log, t] {
      for (int i = 0; i < 250; ++i) log.info("engine", "t" + std::to_string(t) + "-" + std::to_string(i));
    });
  }
  for (auto& t : ts) t.join();
  LogQuery lq;
  lq.limit = 1000;
  const auto e = log.query(lq);
  CHECK(e.size() == 1000);
  std::set<uint64_t> seqs;
  for (const auto& x : e) seqs.insert(x.seq);
  CHECK(seqs.size() == e.size());  // sequence numbers are unique
  CHECK(log.last_seq() == 1000);
}
