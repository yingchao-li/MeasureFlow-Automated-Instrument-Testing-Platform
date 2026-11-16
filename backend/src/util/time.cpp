#include "measureflow/util/time.hpp"

#include <cstdio>
#include <ctime>

namespace mf {

namespace {

struct Civil {
  int y;
  unsigned m;
  unsigned d;
};

Civil civil_from_days(int64_t z) {
  z += 719468;
  const int64_t era = (z >= 0 ? z : z - 146096) / 146097;
  const unsigned doe = static_cast<unsigned>(z - era * 146097);
  const unsigned yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
  const int64_t y = static_cast<int64_t>(yoe) + era * 400;
  const unsigned doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
  const unsigned mp = (5 * doy + 2) / 153;
  const unsigned d = doy - (153 * mp + 2) / 5 + 1;
  const unsigned m = mp < 10 ? mp + 3 : mp - 9;
  return Civil{static_cast<int>(y + (m <= 2 ? 1 : 0)), m, d};
}

bool is_leap(int y) { return (y % 4 == 0 && y % 100 != 0) || y % 400 == 0; }

unsigned days_in_month(int y, unsigned m) {
  static const unsigned table[12] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  if (m == 2 && is_leap(y)) return 29;
  return table[m - 1];
}

bool all_digits(const std::string& s, size_t pos, size_t n) {
  if (pos + n > s.size()) return false;
  for (size_t i = 0; i < n; ++i) {
    if (s[pos + i] < '0' || s[pos + i] > '9') return false;
  }
  return true;
}

int to_int(const std::string& s, size_t pos, size_t n) {
  int v = 0;
  for (size_t i = 0; i < n; ++i) v = v * 10 + (s[pos + i] - '0');
  return v;
}

struct Parts {
  int year, month, day, hour, minute, second, millis;
};

Parts split(SystemClock::time_point tp) {
  const auto ms_total = std::chrono::duration_cast<std::chrono::milliseconds>(tp.time_since_epoch()).count();
  int64_t secs = ms_total / 1000;
  int64_t ms = ms_total % 1000;
  if (ms < 0) {
    ms += 1000;
    secs -= 1;
  }
  int64_t days = secs / 86400;
  int64_t rem = secs % 86400;
  if (rem < 0) {
    rem += 86400;
    days -= 1;
  }
  const Civil c = civil_from_days(days);
  return Parts{c.y, static_cast<int>(c.m), static_cast<int>(c.d), static_cast<int>(rem / 3600),
               static_cast<int>((rem % 3600) / 60), static_cast<int>(rem % 60), static_cast<int>(ms)};
}

}  // namespace

std::string iso_from(SystemClock::time_point tp) {
  const Parts p = split(tp);
  char buf[40];
  std::snprintf(buf, sizeof buf, "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ", p.year, p.month, p.day, p.hour,
                p.minute, p.second, p.millis);
  return buf;
}

std::string iso_now() { return iso_from(SystemClock::now()); }

std::string compact_stamp(SystemClock::time_point tp) {
  const Parts p = split(tp);
  char buf[32];
  std::snprintf(buf, sizeof buf, "%04d%02d%02d-%02d%02d%02d", p.year, p.month, p.day, p.hour, p.minute,
                p.second);
  return buf;
}

int64_t days_from_civil(int y, unsigned m, unsigned d) {
  y -= m <= 2 ? 1 : 0;
  const int64_t era = (y >= 0 ? y : y - 399) / 400;
  const unsigned yoe = static_cast<unsigned>(y - era * 400);
  const unsigned doy = (153 * (m > 2 ? m - 3 : m + 9) + 2) / 5 + d - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + static_cast<int64_t>(doe) - 719468;
}

std::string date_from_days(int64_t days) {
  const Civil c = civil_from_days(days);
  char buf[24];
  std::snprintf(buf, sizeof buf, "%04d-%02u-%02u", c.y, c.m, c.d);
  return buf;
}

std::optional<int64_t> parse_iso_date(const std::string& s) {
  if (s.size() != 10 || !all_digits(s, 0, 4) || s[4] != '-' || !all_digits(s, 5, 2) || s[7] != '-' ||
      !all_digits(s, 8, 2)) {
    return std::nullopt;
  }
  const int y = to_int(s, 0, 4);
  const int m = to_int(s, 5, 2);
  const int d = to_int(s, 8, 2);
  if (m < 1 || m > 12 || d < 1 || d > static_cast<int>(days_in_month(y, static_cast<unsigned>(m)))) {
    return std::nullopt;
  }
  return days_from_civil(y, static_cast<unsigned>(m), static_cast<unsigned>(d));
}

int64_t today_days() {
  const auto secs = std::chrono::duration_cast<std::chrono::seconds>(SystemClock::now().time_since_epoch()).count();
  return secs / 86400;
}

std::optional<int64_t> parse_iso_millis(const std::string& s) {
  // YYYY-MM-DDTHH:MM:SS(.mmm)Z
  if (s.size() < 20 || s.back() != 'Z') return std::nullopt;
  const auto date = parse_iso_date(s.substr(0, 10));
  if (!date || s[10] != 'T' || !all_digits(s, 11, 2) || s[13] != ':' || !all_digits(s, 14, 2) ||
      s[16] != ':' || !all_digits(s, 17, 2)) {
    return std::nullopt;
  }
  const int hh = to_int(s, 11, 2), mm = to_int(s, 14, 2), ss = to_int(s, 17, 2);
  if (hh > 23 || mm > 59 || ss > 60) return std::nullopt;
  int ms = 0;
  if (s.size() > 20) {
    if (s.size() < 22 || s[19] != '.' || !all_digits(s, 20, s.size() - 21)) return std::nullopt;
    const std::string frac = (s.substr(20, s.size() - 21) + "000").substr(0, 3);
    ms = to_int(frac, 0, 3);
  } else if (s.size() != 20) {
    return std::nullopt;
  }
  return ((*date * 86400) + hh * 3600 + mm * 60 + ss) * 1000 + ms;
}

}  // namespace mf
