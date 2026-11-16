// net + scpi: framing, partial reads, limits, timeouts, retries, reconnect, invalid responses, NaN/Inf,
// error queue handling and cancellation, all against the in-process fake server.
#include <atomic>
#include <chrono>
#include <cmath>
#include <mutex>
#include <thread>

#include "catch_amalgamated.hpp"
#include "fake_scpi.hpp"
#include "measureflow/net/tcp_connection.hpp"
#include "measureflow/scpi/scpi_client.hpp"
#include "measureflow/scpi/scpi_parse.hpp"

using namespace mf;
using namespace std::chrono_literals;
using mftest::FakeScpiServer;
using mftest::Reply;

namespace {

// A tiny generic instrument: numeric/echo/queue behaviour, no domain logic.
struct Echo {
  std::mutex mu;
  std::vector<std::string> errq;
  FakeScpiServer server{[this](const std::string& up, const std::string& raw) -> Reply {
    std::lock_guard<std::mutex> lk(mu);
    if (up == "*IDN?") return {std::string("MeasureFlow,VSG-1000,SN-SIM-0001,1.0.0"), false};
    if (up == "*CLS") { errq.clear(); return {}; }
    if (up == "SYST:ERR?") {
      if (errq.empty()) return {std::string("0,\"No error\""), false};
      const std::string e = errq.front();
      errq.erase(errq.begin());
      return {e, false};
    }
    if (up == "EMPTY?") return {std::string(), false};
    if (up == "NUM?") return {std::string("1.5"), true};
    if (up == "ONE?") return {std::string("1"), true};
    if (up == "NANQ?") return {std::string("NAN"), true};
    if (up == "SET 99") { errq.push_back("-222,\"Data out of range\""); errq.push_back("-102,\"Syntax error\""); return {}; }
    if (up.rfind("SET ", 0) == 0) return {};
    if (up.rfind("ECHO? ", 0) == 0) return {raw.substr(6), false};
    if (up == "BAD?") { errq.push_back("-113,\"Undefined header\""); return {}; }  // failed query: no response line
    errq.push_back("-113,\"Undefined header\"");
    return {};
  }};
};

ScpiConfig cfg_for(const Echo& e, int timeout_ms = 300, int retries = 2) {
  ScpiConfig c;
  c.id = "dev";
  c.port = e.server.port();
  c.timeout_ms = timeout_ms;
  c.connect_timeout_ms = 300;
  c.max_retries = retries;
  c.backoff_base_ms = 2;
  c.backoff_max_ms = 5;
  return c;
}

}  // namespace

TEST_CASE("scpi parse helpers", "[scpi][parse]") {
  const auto e = parse_error_response("-222,\"Data out of range\"");
  REQUIRE(e.has_value());
  CHECK(e->code == -222);
  CHECK(e->message == "Data out of range");
  CHECK(parse_error_response("0,\"No error\"")->code == 0);
  CHECK_FALSE(parse_error_response("garbage").has_value());
  CHECK_FALSE(parse_error_response("abc,\"x\"").has_value());
  CHECK_FALSE(parse_error_response("").has_value());

  const auto idn = parse_idn("MeasureFlow, VSG-1000 ,SN-SIM-0001,1.0.0");
  REQUIRE(idn.has_value());
  CHECK(idn->model == "VSG-1000");
  CHECK(idn->firmware == "1.0.0");
  CHECK_FALSE(parse_idn("a,b,c").has_value());
  CHECK_FALSE(parse_idn("a,b,,d").has_value());
  CHECK_FALSE(parse_idn("a,b,c,d,e").has_value());

  CHECK(parse_bool_response("1") == true);
  CHECK(parse_bool_response("OFF") == false);
  CHECK(parse_bool_response(" on ") == true);
  CHECK_FALSE(parse_bool_response("2").has_value());

  const auto list = parse_number_list("1, 2.5,-3e2,NAN");
  REQUIRE(list.has_value());
  REQUIRE(list->size() == 4);
  CHECK((*list)[2].value == -300.0);
  CHECK((*list)[3].cls == NumberClass::NaN);
  CHECK_FALSE(parse_number_list("1,,2").has_value());
  CHECK_FALSE(parse_number_list("1,x").has_value());
  CHECK(split_fields("a, b ,c") == std::vector<std::string>{"a", "b", "c"});
}

TEST_CASE("scpi error kinds classify communication failures", "[scpi]") {
  CHECK(is_communication_kind(ScpiErrorKind::Timeout));
  CHECK(is_communication_kind(ScpiErrorKind::Disconnected));
  CHECK(is_communication_kind(ScpiErrorKind::InvalidResponse));
  CHECK(is_communication_kind(ScpiErrorKind::ResponseTooLarge));
  CHECK_FALSE(is_communication_kind(ScpiErrorKind::Instrument));
  CHECK_FALSE(is_communication_kind(ScpiErrorKind::Cancelled));
}

TEST_CASE("TcpConnection framing: terminators, leftovers and limits", "[net]") {
  std::atomic<bool> go{false};
  FakeScpiServer srv([&](const std::string& up, const std::string&) -> Reply {
    if (up == "TWO?") return {std::string("first\r\nsecond"), false};  // CRLF inside one write, second line follows
    if (up == "HUGE?") return {std::string(5000, 'x'), false};
    (void)go;
    return {};
  });
  TcpConnection c;
  c.connect("127.0.0.1", srv.port(), 500);
  REQUIRE(c.is_open());
  c.send_all("TWO?\n", 500);
  CHECK(c.recv_line(100, 500, 1000) == "first");  // '\r' is stripped
  CHECK(c.recv_line(100, 500, 1000) == "second");  // bytes after the first terminator were kept
  c.send_all("HUGE?\n", 500);
  CHECK_THROWS_MATCHES(c.recv_line(1000, 500, 1000), NetError, Catch::Matchers::Predicate<NetError>([](const NetError& e) { return e.kind() == NetErrorKind::TooLarge; }));
}

TEST_CASE("TcpConnection errors: refused, timeout, peer close, interrupt, cancel", "[net]") {
  SECTION("connection refused") {
    FakeScpiServer tmp([](const std::string&, const std::string&) -> Reply { return {}; });
    const uint16_t port = tmp.port();
    tmp.stop();
    TcpConnection c;
    CHECK_THROWS_MATCHES(c.connect("127.0.0.1", port, 300), NetError,
                         Catch::Matchers::Predicate<NetError>([](const NetError& e) { return e.kind() == NetErrorKind::ConnectFailed; }));
    CHECK_FALSE(c.is_open());
  }
  SECTION("read timeout when the peer stays silent") {
    FakeScpiServer srv([](const std::string&, const std::string&) -> Reply { return {}; });
    TcpConnection c;
    c.connect("127.0.0.1", srv.port(), 500);
    c.send_all("NOTHING\n", 500);
    const auto t0 = std::chrono::steady_clock::now();
    CHECK_THROWS_MATCHES(c.recv_line(100, 150, 1000), NetError, Catch::Matchers::Predicate<NetError>([](const NetError& e) { return e.kind() == NetErrorKind::Timeout; }));
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count();
    CHECK(ms >= 140);
    CHECK(ms < 600);
  }
  SECTION("total timeout bounds a slowly trickling line") {
    FakeScpiServer srv([](const std::string&, const std::string&) -> Reply { return {std::string("0123456789abcdefghij"), false}; });
    srv.f_fragment = 1;
    srv.fragment_chunk = 1;
    srv.fragment_delay_ms = 40;  // each chunk arrives within the per-read timeout, the whole line takes ~800 ms
    TcpConnection c;
    c.connect("127.0.0.1", srv.port(), 500);
    c.send_all("Q?\n", 500);
    CHECK_THROWS_MATCHES(c.recv_line(100, 200, 300), NetError, Catch::Matchers::Predicate<NetError>([](const NetError& e) { return e.kind() == NetErrorKind::Timeout; }));
  }
  SECTION("peer closes the connection") {
    FakeScpiServer srv([](const std::string&, const std::string&) -> Reply { return {}; });
    srv.f_disconnect = 1;
    TcpConnection c;
    c.connect("127.0.0.1", srv.port(), 500);
    c.send_all("ANY\n", 500);
    CHECK_THROWS_MATCHES(c.recv_line(100, 500, 1000), NetError, Catch::Matchers::Predicate<NetError>([](const NetError& e) { return e.kind() == NetErrorKind::Closed; }));
  }
  SECTION("interrupt wakes a blocked reader") {
    FakeScpiServer srv([](const std::string&, const std::string&) -> Reply { return {}; });
    TcpConnection c;
    c.connect("127.0.0.1", srv.port(), 500);
    std::thread t([&] {
      std::this_thread::sleep_for(60ms);
      c.interrupt();
    });
    const auto t0 = std::chrono::steady_clock::now();
    CHECK_THROWS_AS(c.recv_line(100, 3000, 3000), NetError);
    CHECK(std::chrono::steady_clock::now() - t0 < 1500ms);
    t.join();
  }
  SECTION("cancel flag is polled while waiting") {
    FakeScpiServer srv([](const std::string&, const std::string&) -> Reply { return {}; });
    TcpConnection c;
    c.connect("127.0.0.1", srv.port(), 500);
    std::atomic<bool> cancel{false};
    std::thread t([&] {
      std::this_thread::sleep_for(60ms);
      cancel = true;
    });
    const auto t0 = std::chrono::steady_clock::now();
    CHECK_THROWS_MATCHES(c.recv_line(100, 3000, 3000, &cancel), NetError, Catch::Matchers::Predicate<NetError>([](const NetError& e) { return e.kind() == NetErrorKind::Cancelled; }));
    CHECK(std::chrono::steady_clock::now() - t0 < 1000ms);
    t.join();
  }
}

TEST_CASE("ScpiClient basic query/write and framing", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev));
  c.connect();
  CHECK(c.query("*IDN?") == "MeasureFlow,VSG-1000,SN-SIM-0001,1.0.0");
  CHECK(c.query_double("NUM?") == 1.5);
  c.write("SET 5");
  CHECK(c.query("ECHO? hello world") == "hello world");
  CHECK(dev.server.count_received("SET 5") == 1);
  CHECK(c.stats().commands >= 4);
}

TEST_CASE("ScpiClient reassembles fragmented responses", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev, 500));
  c.connect();
  dev.server.f_fragment = 2;
  dev.server.fragment_chunk = 3;
  dev.server.fragment_delay_ms = 5;
  CHECK(c.query("ECHO? the quick brown fox jumps") == "the quick brown fox jumps");
  CHECK(dev.server.f_fragment.load() == 1);
  CHECK(c.stats().retries == 0);
}

TEST_CASE("ScpiClient enforces the response size limit", "[scpi][client]") {
  Echo dev;
  ScpiConfig cfg = cfg_for(dev, 1000, 0);
  cfg.max_response_bytes = 64 * 1024;
  ScpiClient c(cfg);
  c.connect();
  dev.server.f_oversize = 1;  // > 2 MiB response
  try {
    c.query("ECHO? x");
    FAIL("expected ResponseTooLarge");
  } catch (const ScpiError& e) {
    CHECK(e.kind() == ScpiErrorKind::ResponseTooLarge);
  }
  CHECK_FALSE(c.is_open());  // the stream is unusable after an oversize line
  CHECK(c.query("ECHO? again") == "again");  // and a new connection is opened transparently
  CHECK(dev.server.accepted_connections() == 2);
}

TEST_CASE("ScpiClient timeouts: retried, then reported as Timeout", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev, 120, 2));
  c.connect();
  dev.server.set_reply_delay_ms(400);
  const auto t0 = std::chrono::steady_clock::now();
  try {
    c.query("NUM?");
    FAIL("expected timeout");
  } catch (const ScpiError& e) {
    CHECK(e.kind() == ScpiErrorKind::Timeout);
    CHECK(e.instrument() == "dev");
    CHECK(e.command() == "NUM?");
  }
  CHECK(std::chrono::steady_clock::now() - t0 < 5s);
  CHECK(dev.server.count_received("NUM?") == 3);  // 1 + max_retries
  CHECK(c.stats().retries == 2);
  dev.server.set_reply_delay_ms(0);
  std::this_thread::sleep_for(500ms);  // let the stale replies drain
  CHECK(c.query_double("NUM?") == 1.5);  // the desynchronised stream was dropped, not reused
}

TEST_CASE("ScpiClient succeeds after a transient failure", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev, 300, 2));
  c.connect();
  REQUIRE(dev.server.wait_accepted(1));
  SECTION("peer drops the connection once") {
    dev.server.f_disconnect = 1;
    CHECK(c.query_double("NUM?") == 1.5);
    CHECK(c.stats().retries == 1);
    CHECK(dev.server.accepted_connections() == 2);
  }
  SECTION("garbage once") {
    dev.server.f_garbage = 1;
    const std::string r = c.query("ECHO? fine", {}, [](const std::string& s) { return s == "fine"; });
    CHECK(r == "fine");
    CHECK(c.stats().retries == 1);
  }
  SECTION("one delayed response") {
    dev.server.f_timeout = 1;
    dev.server.timeout_delay_ms = 1500;
    CHECK(c.query_double("NUM?") == 1.5);
    CHECK(c.stats().retries == 1);
  }
}

TEST_CASE("ScpiClient gives up after the configured retries", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev, 300, 2));
  c.connect();
  dev.server.f_disconnect = 100;
  try {
    c.query("NUM?");
    FAIL("expected Disconnected");
  } catch (const ScpiError& e) {
    CHECK(e.kind() == ScpiErrorKind::Disconnected);
  }
  CHECK(c.stats().retries == 2);
  CHECK(dev.server.accepted_connections() == 3);
}

TEST_CASE("ScpiClient does not retry non-idempotent calls", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev, 300, 3));
  c.connect();
  dev.server.f_disconnect = 1;
  CallOptions o;
  o.idempotent = false;
  CHECK_THROWS_AS(c.query("NUM?", o), ScpiError);
  CHECK(c.stats().retries == 0);
  CHECK(dev.server.count_received("NUM?") == 1);
  CHECK(c.query_double("NUM?") == 1.5);  // still recovers on the next call
}

TEST_CASE("ScpiClient rejects invalid responses", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev, 300, 0));
  c.connect();
  SECTION("garbage is not a number") {
    dev.server.f_garbage = 1;
    try {
      c.query_double("NUM?");
      FAIL("expected InvalidResponse");
    } catch (const ScpiError& e) {
      CHECK(e.kind() == ScpiErrorKind::InvalidResponse);
    }
  }
  SECTION("validator rejects unexpected content") {
    CHECK_THROWS_AS(c.query("ECHO? hello", {}, [](const std::string& s) { return s == "bye"; }), ScpiError);
  }
  SECTION("empty line") {
    try {
      c.query("EMPTY?");
      FAIL("expected InvalidResponse");
    } catch (const ScpiError& e) {
      CHECK(e.kind() == ScpiErrorKind::InvalidResponse);
    }
  }
  SECTION("non-printable bytes") {
    FakeScpiServer bin([](const std::string&, const std::string&) -> Reply { return {std::string("ab\x01\x02") + "cd", false}; });
    ScpiConfig cfg = cfg_for(dev, 300, 0);
    cfg.port = bin.port();
    ScpiClient c2(cfg);
    c2.connect();
    try {
      c2.query("X?");
      FAIL("expected InvalidResponse");
    } catch (const ScpiError& e) {
      CHECK(e.kind() == ScpiErrorKind::InvalidResponse);
    }
  }
}

TEST_CASE("ScpiClient treats NaN and Inf as valid numeric responses and never retries them", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev, 300, 3));
  c.connect();
  CHECK(std::isnan(c.query_double("NANQ?")));
  dev.server.f_inf = 1;
  const double v = c.query_double("NUM?");
  CHECK(std::isinf(v));
  CHECK(v > 0);
  CHECK(dev.server.count_received("NANQ?") == 1);
  CHECK(dev.server.count_received("NUM?") == 1);
  CHECK(c.stats().retries == 0);
}

TEST_CASE("ScpiClient error queue helpers", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev));
  c.connect();
  SECTION("empty queue") { CHECK(c.read_errors().empty()); }
  SECTION("write_checked passes a clean setter") { CHECK_NOTHROW(c.write_checked("SET 1")); }
  SECTION("write_checked reports the first queued error and drains the rest") {
    try {
      c.write_checked("SET 99");
      FAIL("expected instrument error");
    } catch (const ScpiError& e) {
      CHECK(e.kind() == ScpiErrorKind::Instrument);
      CHECK(e.instrument_code() == -222);
      CHECK(e.instrument_message() == "Data out of range");
    }
    CHECK(c.read_errors().empty());
  }
  SECTION("read_errors lists all entries in order") {
    c.write("SET 99");
    const auto errs = c.read_errors();
    REQUIRE(errs.size() == 2);
    CHECK(errs[0].code == -222);
    CHECK(errs[1].code == -102);
  }
  SECTION("read_errors honours max_entries") {
    c.write("SET 99");
    CHECK(c.read_errors(1).size() == 1);
    CHECK(c.read_errors().size() == 1);
  }
}

TEST_CASE("a failed query (no response line) is explained by the error queue", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev, 120, 2));
  c.connect();
  SECTION("queue explains the silence -> Instrument error, no retry") {
    try {
      c.query("BAD?");
      FAIL("expected instrument error");
    } catch (const ScpiError& e) {
      CHECK(e.kind() == ScpiErrorKind::Instrument);
      CHECK(e.instrument_code() == -113);
      CHECK(e.instrument_message() == "Undefined header");
    }
    CHECK(dev.server.count_received("BAD?") == 1);
    CHECK(c.stats().retries == 0);
    CHECK(c.read_errors().empty());  // the probe drained the queue
    CHECK(c.query_double("NUM?") == 1.5);
  }
  SECTION("empty queue -> plain timeout after retries") {
    dev.server.set_reply_delay_ms(600);
    try {
      c.query("NUM?");
      FAIL("expected timeout");
    } catch (const ScpiError& e) {
      CHECK(e.kind() == ScpiErrorKind::Timeout);
    }
    CHECK(c.stats().retries == 2);
  }
  SECTION("explain_timeouts=false keeps the raw timeout") {
    CallOptions o;
    o.explain_timeouts = false;
    o.max_retries = 0;
    try {
      c.query("BAD?", o);
      FAIL("expected timeout");
    } catch (const ScpiError& e) {
      CHECK(e.kind() == ScpiErrorKind::Timeout);
    }
  }
}

TEST_CASE("ScpiClient connection lifecycle", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev, 300, 1));
  CHECK_FALSE(c.wants_connection());
  CHECK_THROWS_AS(c.query("NUM?"), ScpiError);  // never connected: no implicit connect
  c.connect();
  REQUIRE(dev.server.wait_accepted(1));
  CHECK(c.wants_connection());
  CHECK(c.is_open());
  SECTION("transparent reconnect after the peer dropped us") {
    dev.server.drop_connections();
    std::this_thread::sleep_for(100ms);
    CHECK(c.query_double("NUM?") == 1.5);
    CHECK(dev.server.accepted_connections() == 2);
  }
  SECTION("disconnect disarms auto-reconnect") {
    c.disconnect();
    CHECK_FALSE(c.wants_connection());
    CHECK_FALSE(c.is_open());
    try {
      c.query("NUM?");
      FAIL("expected Disconnected");
    } catch (const ScpiError& e) {
      CHECK(e.kind() == ScpiErrorKind::Disconnected);
    }
    CHECK(dev.server.accepted_connections() == 1);
  }
  SECTION("explicit reconnect") {
    c.reconnect();
    CHECK(c.query_double("NUM?") == 1.5);
    CHECK(dev.server.accepted_connections() == 2);
  }
  SECTION("connect failure when the instrument is down") {
    const uint16_t port = dev.server.port();
    dev.server.stop();
    ScpiConfig cfg = cfg_for(dev);
    cfg.port = port;
    ScpiClient dead(cfg);
    try {
      dead.connect();
      FAIL("expected failure");
    } catch (const ScpiError& e) {
      CHECK(e.kind() == ScpiErrorKind::Disconnected);
    }
  }
}

TEST_CASE("ConnectionEpoch detects a connection that was re-established under a setter", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev, 300, 2));
  c.connect();
  REQUIRE(dev.server.wait_accepted(1));
  {
    const ConnectionEpoch e(c);
    c.write("SET 1");
    CHECK_NOTHROW(e.verify("SET 1"));
  }
  {
    const ConnectionEpoch e(c);
    dev.server.drop_connections();
    std::this_thread::sleep_for(100ms);
    CHECK(c.query_double("NUM?") == 1.5);  // transparently reconnected
    try {
      e.verify("SET 2");
      FAIL("expected Disconnected");
    } catch (const ScpiError& err) {
      CHECK(err.kind() == ScpiErrorKind::Disconnected);
    }
  }
  c.disconnect();
  CHECK_THROWS_AS(ConnectionEpoch(c), ScpiError);
}

TEST_CASE("ScpiClient cancellation interrupts a blocked query and keeps the client usable", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev, 3000, 2));
  c.connect();
  std::atomic<bool> cancel{false};
  c.set_cancel_flag(&cancel);
  dev.server.set_reply_delay_ms(2000);
  std::thread t([&] {
    std::this_thread::sleep_for(80ms);
    cancel = true;
  });
  const auto t0 = std::chrono::steady_clock::now();
  try {
    c.query("NUM?");
    FAIL("expected Cancelled");
  } catch (const ScpiError& e) {
    CHECK(e.kind() == ScpiErrorKind::Cancelled);
  }
  t.join();
  CHECK(std::chrono::steady_clock::now() - t0 < 1500ms);
  CHECK(c.stats().retries == 0);  // cancellation is never retried
  // While the flag is set every call fails fast without touching the wire.
  const int before = dev.server.accepted_connections();
  CHECK_THROWS_AS(c.query("NUM?"), ScpiError);
  CHECK(dev.server.accepted_connections() == before);
  cancel = false;
  dev.server.set_reply_delay_ms(0);
  CHECK(c.query_double("NUM?") == 1.5);
}

TEST_CASE("ScpiClient serialises concurrent callers", "[scpi][client]") {
  Echo dev;
  ScpiClient c(cfg_for(dev, 1000, 0));
  c.connect();
  std::atomic<int> bad{0};
  std::vector<std::thread> ts;
  for (int t = 0; t < 4; ++t) {
    ts.emplace_back([&, t] {
      for (int i = 0; i < 40; ++i) {
        const std::string token = "t" + std::to_string(t) + "i" + std::to_string(i);
        if (c.query("ECHO? " + token) != token) ++bad;
      }
    });
  }
  for (auto& t : ts) t.join();
  CHECK(bad.load() == 0);
  CHECK(dev.server.accepted_connections() == 1);
}

TEST_CASE("ScpiClient reports traffic through the communication hook", "[scpi][client]") {
  Echo dev;
  std::mutex mu;
  std::vector<CommEvent> events;
  ScpiClient c(cfg_for(dev, 300, 1), [&](const CommEvent& e) {
    std::lock_guard<std::mutex> lk(mu);
    events.push_back(e);
  });
  c.connect();
  c.query("ECHO? ping");
  dev.server.f_disconnect = 1;
  c.query("NUM?");
  std::lock_guard<std::mutex> lk(mu);
  auto count = [&](CommEvent::Type t) {
    int n = 0;
    for (const auto& e : events) n += e.type == t;
    return n;
  };
  CHECK(count(CommEvent::Type::Connect) == 2);
  CHECK(count(CommEvent::Type::Tx) >= 3);
  CHECK(count(CommEvent::Type::Rx) >= 2);
  CHECK(count(CommEvent::Type::Retry) == 1);
  CHECK(count(CommEvent::Type::Error) == 1);
  for (const auto& e : events) CHECK(e.instrument == "dev");
}

TEST_CASE("probe helpers use short-lived connections", "[scpi][probe]") {
  Echo dev;
  std::string detail;
  CHECK(probe_tcp("127.0.0.1", dev.server.port(), 300, &detail));
  CHECK(detail.find("reachable") != std::string::npos);
  std::string resp;
  CHECK(probe_query("127.0.0.1", dev.server.port(), "*IDN?", 300, &resp));
  CHECK(resp.find("VSG-1000") != std::string::npos);
  dev.server.set_reply_delay_ms(500);
  CHECK_FALSE(probe_query("127.0.0.1", dev.server.port(), "*IDN?", 100, &resp));
  const uint16_t port = dev.server.port();
  dev.server.stop();
  CHECK_FALSE(probe_tcp("127.0.0.1", port, 200, &detail));
  CHECK_FALSE(detail.empty());
}
