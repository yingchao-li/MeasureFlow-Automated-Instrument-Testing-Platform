#pragma once

#include "measureflow/api/http_types.hpp"
#include "measureflow/engine/result_store.hpp"
#include "measureflow/engine/runner.hpp"
#include "measureflow/engine/sequence.hpp"
#include "measureflow/env/environment.hpp"
#include "measureflow/instruments/registry.hpp"
#include "measureflow/report/report_service.hpp"
#include "measureflow/util/logger.hpp"

namespace mf {

struct AppServices {
  Logger& logger;
  InstrumentRegistry& registry;
  const SequenceLibrary& sequences;
  ResultStore& store;
  ReportService& reports;
  TestRunner& runner;
  EnvironmentManager& env;
};

void register_system_routes(Router& router, AppServices& svc);      // health, environment, logs
void register_instrument_routes(Router& router, AppServices& svc);  // instruments/*, measurements/live
void register_test_routes(Router& router, AppServices& svc);        // sequences, tests/*
void register_report_routes(Router& router, AppServices& svc);      // reports/*

inline void register_all_routes(Router& router, AppServices& svc) {
  register_system_routes(router, svc);
  register_instrument_routes(router, svc);
  register_test_routes(router, svc);
  register_report_routes(router, svc);
}

}  // namespace mf
