// Sequence loading, validation, parameter resolution, templating and plan building (bad inputs included).
#include <filesystem>

#include "catch_amalgamated.hpp"
#include "fake_scpi.hpp"
#include "measureflow/engine/sequence.hpp"
#include "measureflow/util/errors.hpp"

using namespace mf;
namespace fs = std::filesystem;

namespace {

// A valid sequence document with optional fragments substituted for the defaults.
std::string seq_json(const std::string& steps_override = {}, const std::string& params_override = {}, const std::string& extra_top = {}) {
  const std::string params = params_override.empty()
                                 ? R"("frequency_hz":{"label":"Frequency","unit":"Hz","default":1000,"min":20,"max":20000},
                                      "gain_min_db":{"label":"Min","unit":"dB","default":19,"min":-20,"max":60})"
                                 : params_override;
  const std::string steps = steps_override.empty()
                                ? R"({"id":"init","type":"init","name":"Init","instruments":["siggen","analyzer","dut"]},
                                     {"id":"cfg","type":"configure_signal","name":"Stimulus ${frequency_hz} Hz","function":"SIN","frequency_hz":"${frequency_hz}","amplitude_vpk":0.05,"output":true,"settle_ms":5},
                                     {"id":"cfg_dut","type":"configure_dut","name":"DUT","settings":{"gain_db":18}},
                                     {"id":"gain","type":"measure","name":"Gain @ ${frequency_hz}","measurement":"gain","limits":{"min":"${gain_min_db}","max":21,"unit":"dB"}},
                                     {"id":"cleanup","type":"cleanup","name":"Cleanup"},
                                     {"id":"report","type":"report","name":"Report"})"
                                : steps_override;
  return R"({"id":"t_seq","name":"Test Sequence","version":"1.0.0","description":"d",)" + extra_top +
         R"("dut":{"profile":"NORMAL","firmware":"1.0.0"},"parameters":{)" + params + R"(},"steps":[)" + steps + "]}";
}

void expect_invalid(const std::string& json, const std::string& needle = {}) {
  try {
    parse_sequence(json, "test.json");
    FAIL("expected the sequence to be rejected: " << json.substr(0, 200));
  } catch (const MfError& e) {
    CHECK(e.code() == ErrorCode::InvalidArgument);
    if (!needle.empty()) CHECK(std::string(e.what()).find(needle) != std::string::npos);
  }
}

}  // namespace

TEST_CASE("a valid sequence parses into typed definitions", "[sequence]") {
  const SequenceDef s = parse_sequence(seq_json(), "test.json");
  CHECK(s.id == "t_seq");
  CHECK(s.version == "1.0.0");
  CHECK(s.dut.profile == "NORMAL");
  REQUIRE(s.steps.size() == 6);
  CHECK(s.steps[0].type == StepType::Init);
  CHECK(s.steps[0].instruments.size() == 3);
  CHECK(s.steps[1].frequency_hz.kind == NumExpr::Kind::Param);
  CHECK(s.steps[1].amplitude_vpk.kind == NumExpr::Kind::Literal);
  CHECK(s.steps[1].output);
  CHECK(s.steps[3].measurement == Measurement::Gain);
  CHECK(s.steps[3].limits.min.kind == NumExpr::Kind::Param);
  CHECK(s.steps[3].limits.max.value == 21.0);
  REQUIRE(s.find_param("frequency_hz") != nullptr);
  CHECK(s.find_param("frequency_hz")->max == 20000);
  CHECK(s.find_param("nope") == nullptr);
}

TEST_CASE("null limits are open bounds", "[sequence]") {
  const std::string steps = R"({"id":"thd","type":"measure","name":"THD","measurement":"thd","limits":{"min":null,"max":1.0,"unit":"%"}})";
  const SequenceDef s = parse_sequence(seq_json(steps), "t.json");
  CHECK(s.steps[0].limits.min.is_null());
  const ResolvedPlan p = build_plan(s, resolve_parameters(s, {}));
  CHECK_FALSE(p.steps[0].limits.min.has_value());
  CHECK(p.steps[0].limits.max == 1.0);
  CHECK(p.steps[0].limits.unit == "%");
}

TEST_CASE("malformed or unsafe sequences are rejected with a precise message", "[sequence][validation]") {
  SECTION("not JSON / wrong top-level type") {
    expect_invalid("{not json", "not valid JSON");
    expect_invalid("[]", "top level");
    expect_invalid("", "");
  }
  SECTION("identity") {
    expect_invalid(R"({"id":"../x","name":"n","steps":[{"id":"a","type":"init","name":"x"}]})", "id");
    expect_invalid(R"({"id":"ok","name":"","steps":[{"id":"a","type":"init","name":"x"}]})", "name");
    expect_invalid(R"({"id":"ok","name":"n"})", "steps");
    expect_invalid(R"({"id":"ok","name":"n","steps":[]})", "steps");
  }
  SECTION("unknown step type") {
    expect_invalid(seq_json(R"({"id":"x","type":"explode","name":"X"})"), "unknown step type");
  }
  SECTION("duplicate and invalid step ids") {
    expect_invalid(seq_json(R"({"id":"a","type":"init","name":"A"},{"id":"a","type":"cleanup","name":"B"})"), "duplicate step id");
    expect_invalid(seq_json(R"({"id":"a b","type":"init","name":"A"})"), "id");
  }
  SECTION("missing required step fields") {
    expect_invalid(seq_json(R"({"id":"c","type":"configure_signal","name":"C","amplitude_vpk":0.05,"output":true})"), "frequency_hz");
    expect_invalid(seq_json(R"({"id":"c","type":"configure_signal","name":"C","frequency_hz":1000,"output":true})"), "amplitude_vpk");
    expect_invalid(seq_json(R"({"id":"m","type":"measure","name":"M","measurement":"gain"})"), "limits");
    expect_invalid(seq_json(R"({"id":"m","type":"measure","name":"M","limits":{"unit":"dB"}})"), "measurement");
  }
  SECTION("unknown measurement and sweep restrictions") {
    expect_invalid(seq_json(R"({"id":"m","type":"measure","name":"M","measurement":"power","limits":{"unit":"W"}})"), "unknown measurement");
    expect_invalid(seq_json(R"({"id":"s","type":"sweep","name":"S","measurement":"thd","amplitude_vpk":0.05,"points_hz":[100],"limits":{"unit":"%"}})"), "gain");
    expect_invalid(seq_json(R"({"id":"s","type":"sweep","name":"S","measurement":"gain","amplitude_vpk":0.05,"points_hz":[],"limits":{"unit":"dB"}})"), "points_hz");
  }
  SECTION("wrong value types") {
    expect_invalid(seq_json(R"({"id":"c","type":"configure_signal","name":"C","frequency_hz":"loud","amplitude_vpk":0.05,"output":true})"), "template");
    expect_invalid(seq_json(R"({"id":"c","type":"configure_signal","name":"C","frequency_hz":1000,"amplitude_vpk":0.05,"output":"yes"})"), "boolean");
    expect_invalid(seq_json(R"({"id":"c","type":"configure_signal","name":"C","frequency_hz":true,"amplitude_vpk":0.05,"output":true})"), "number");
  }
  SECTION("template referencing an undeclared parameter") {
    expect_invalid(seq_json(R"({"id":"c","type":"configure_signal","name":"C","frequency_hz":"${nope}","amplitude_vpk":0.05,"output":true})"), "undeclared parameter");
  }
  SECTION("parameter declarations") {
    expect_invalid(seq_json({}, R"("frequency_hz":{"label":"F","unit":"Hz","default":5,"min":10,"max":20})"), "default outside");
    expect_invalid(seq_json({}, R"("frequency_hz":{"label":"F","unit":"Hz","default":15,"min":20,"max":10})"), "min > max");
    expect_invalid(seq_json({}, R"("frequency_hz":{"label":"F","unit":"Hz","default":"x","min":10,"max":20})"), "number");
    expect_invalid(seq_json({}, R"("bad name!":{"label":"F","unit":"Hz","default":15,"min":10,"max":20})"), "parameter name");
  }
  SECTION("too many steps") {
    std::string steps;
    for (int i = 0; i < 101; ++i) steps += std::string(i ? "," : "") + R"({"id":"s)" + std::to_string(i) + R"(","type":"cleanup","name":"c"})";
    expect_invalid(seq_json(steps), "too many steps");
  }
}

TEST_CASE("extra unknown keys are tolerated, missing optional ones default", "[sequence]") {
  const SequenceDef s = parse_sequence(seq_json({}, {}, R"("x_comment":"hello",)"), "t.json");
  CHECK(s.id == "t_seq");
}

TEST_CASE("resolve_parameters applies defaults and validates overrides", "[sequence][params]") {
  const SequenceDef s = parse_sequence(seq_json(), "t.json");
  auto p = resolve_parameters(s, {});
  CHECK(p.at("frequency_hz") == 1000);
  CHECK(p.at("gain_min_db") == 19);
  p = resolve_parameters(s, {{"frequency_hz", 2000}});
  CHECK(p.at("frequency_hz") == 2000);
  CHECK(p.at("gain_min_db") == 19);
  // boundaries are inclusive
  CHECK_NOTHROW(resolve_parameters(s, {{"frequency_hz", 20}}));
  CHECK_NOTHROW(resolve_parameters(s, {{"frequency_hz", 20000}}));
  // out of range, unknown, non-finite
  for (const auto& bad : std::vector<std::map<std::string, double>>{
           {{"frequency_hz", 19.999}}, {{"frequency_hz", 20000.001}}, {{"unknown", 1}}, {{"frequency_hz", std::nan("")}},
           {{"frequency_hz", std::numeric_limits<double>::infinity()}}}) {
    try {
      resolve_parameters(s, bad);
      FAIL("expected rejection of " << bad.begin()->first << "=" << bad.begin()->second);
    } catch (const MfError& e) {
      CHECK(e.code() == ErrorCode::InvalidArgument);
      CHECK(e.field().rfind("parameters.", 0) == 0);
    }
  }
}

TEST_CASE("render_template substitutes known parameters only", "[sequence][template]") {
  const std::map<std::string, double> p{{"frequency_hz", 1000}, {"amp", 0.05}};
  CHECK(render_template("Gain @ ${frequency_hz} Hz", p) == "Gain @ 1000 Hz");
  CHECK(render_template("${amp}/${frequency_hz}", p) == "0.05/1000");
  CHECK(render_template("${unknown} stays", p) == "${unknown} stays");
  CHECK(render_template("no template", p) == "no template");
  CHECK(render_template("unterminated ${frequency_hz", p) == "unterminated ${frequency_hz");
  CHECK(render_template("$ {x} $", p) == "$ {x} $");
  CHECK(render_template("", p).empty());
}

TEST_CASE("build_plan resolves templates and counts planned work", "[sequence][plan]") {
  const SequenceDef s = parse_sequence(seq_json(), "t.json");
  const auto params = resolve_parameters(s, {{"frequency_hz", 2500}, {"gain_min_db", 18.5}});
  const ResolvedPlan plan = build_plan(s, params);
  REQUIRE(plan.steps.size() == 6);
  CHECK(plan.steps[1].name == "Stimulus 2500 Hz");
  CHECK(std::get<double>(plan.steps[1].signal.at("frequency_hz")) == 2500);
  CHECK(std::get<bool>(plan.steps[1].signal.at("output")) == true);
  CHECK(plan.steps[1].settle_ms == 5);
  CHECK(std::get<double>(plan.steps[2].dut.at("gain_db")) == 18);
  CHECK(plan.steps[3].limits.min == 18.5);
  CHECK(plan.steps[3].limits.max == 21.0);
  CHECK(plan.planned_tasks == 1);
  CHECK(plan.planned_units == 6);  // 1 task + 5 non-measure steps
}

TEST_CASE("build_plan expands sweeps into one task per point", "[sequence][plan]") {
  const std::string steps = R"({"id":"sw","type":"sweep","name":"Sweep","measurement":"gain","amplitude_vpk":0.05,"points_hz":[100,"${frequency_hz}",8000],"limits":{"min":10,"max":25,"unit":"dB"}})";
  const SequenceDef s = parse_sequence(seq_json(steps), "t.json");
  const ResolvedPlan plan = build_plan(s, resolve_parameters(s, {}));
  CHECK(plan.planned_tasks == 3);
  CHECK(plan.steps[0].points_hz == std::vector<double>{100, 1000, 8000});
  CHECK(plan.steps[0].sweep_amplitude_vpk == 0.05);
}

TEST_CASE("build_plan rejects physically invalid values before any instrument is touched", "[sequence][plan][validation]") {
  auto plan_for = [](const std::string& steps, std::map<std::string, double> overrides = {}) {
    const SequenceDef s = parse_sequence(seq_json(steps), "t.json");
    return build_plan(s, resolve_parameters(s, overrides));
  };
  SECTION("frequency outside the generator range") {
    // parameter range allows 20 Hz, but a literal of 5 Hz in the step is below the generator minimum
    CHECK_THROWS_AS(plan_for(R"({"id":"c","type":"configure_signal","name":"C","frequency_hz":5,"amplitude_vpk":0.05,"output":true})"), MfError);
    CHECK_THROWS_AS(plan_for(R"({"id":"c","type":"configure_signal","name":"C","frequency_hz":30000,"amplitude_vpk":0.05,"output":true})"), MfError);
  }
  SECTION("amplitude outside the generator range") {
    CHECK_THROWS_AS(plan_for(R"({"id":"c","type":"configure_signal","name":"C","frequency_hz":1000,"amplitude_vpk":9,"output":true})"), MfError);
    CHECK_THROWS_AS(plan_for(R"({"id":"c","type":"configure_signal","name":"C","frequency_hz":1000,"amplitude_vpk":-1,"output":true})"), MfError);
  }
  SECTION("inverted limits") {
    try {
      plan_for(R"({"id":"m","type":"measure","name":"M","measurement":"gain","limits":{"min":25,"max":20,"unit":"dB"}})");
      FAIL("expected rejection");
    } catch (const MfError& e) {
      CHECK(std::string(e.what()).find("lower limit") != std::string::npos);
    }
  }
  SECTION("inverted limits produced by overriding parameters") {
    const std::string steps = R"({"id":"m","type":"measure","name":"M","measurement":"gain","limits":{"min":"${gain_min_db}","max":21,"unit":"dB"}})";
    CHECK_NOTHROW(plan_for(steps, {{"gain_min_db", 20}}));
    CHECK_THROWS_AS(plan_for(steps, {{"gain_min_db", 22}}), MfError);
  }
  SECTION("sweep point outside the generator range") {
    CHECK_THROWS_AS(plan_for(R"({"id":"s","type":"sweep","name":"S","measurement":"gain","amplitude_vpk":0.05,"points_hz":[100,50000],"limits":{"unit":"dB"}})"), MfError);
  }
  SECTION("invalid DUT setting") {
    CHECK_THROWS_AS(plan_for(R"({"id":"d","type":"configure_dut","name":"D","settings":{"gain_db":500}})"), MfError);
  }
}

TEST_CASE("SequenceLibrary loads a directory and reports broken files without failing", "[sequence][library]") {
  mftest::TempRoot root("{}");
  const fs::path dir = fs::path(root.path()) / "configs" / "sequences";
  root.write("configs/sequences/broken.json", "{ not json");
  root.write("configs/sequences/unknown_step.json", seq_json(R"({"id":"x","type":"explode","name":"X"})"));
  root.write("configs/sequences/ignored.txt", "not a sequence");
  SequenceLibrary lib;
  lib.load_directory(dir);
  CHECK(lib.size() == 7);  // the seven shipped sequences
  CHECK(lib.errors().size() == 2);
  REQUIRE(lib.find("gain_verification") != nullptr);
  CHECK(lib.find("nope") == nullptr);
  const auto list = lib.list();
  REQUIRE(list.size() == 7);
  for (size_t i = 1; i < list.size(); ++i) CHECK(list[i - 1]->id < list[i]->id);  // sorted by id
}

TEST_CASE("every shipped sequence builds a valid plan with its defaults", "[sequence][library]") {
  SequenceLibrary lib;
  lib.load_directory(fs::path(MF_REPO_ROOT) / "configs" / "sequences");
  REQUIRE(lib.errors().empty());
  REQUIRE(lib.size() == 7);
  for (const auto* s : lib.list()) {
    INFO("sequence " << s->id);
    const ResolvedPlan plan = build_plan(*s, resolve_parameters(*s, {}));
    CHECK(plan.planned_tasks >= 1);
    CHECK(plan.steps.size() == s->steps.size());
  }
  CHECK(build_plan(*lib.find("full_pipeline"), resolve_parameters(*lib.find("full_pipeline"), {})).planned_tasks == 13);
}

TEST_CASE("SequenceLibrary::add replaces an entry with the same id", "[sequence][library]") {
  SequenceLibrary lib;
  lib.add(parse_sequence(seq_json(), "a"));
  CHECK(lib.size() == 1);
  SequenceDef copy = parse_sequence(seq_json(), "b");
  copy.name = "Replaced";
  lib.add(copy);
  CHECK(lib.size() == 1);
  CHECK(lib.find("t_seq")->name == "Replaced");
}
