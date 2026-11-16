cmake_minimum_required(VERSION 3.16)
project(MeasureFlowBackend VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(MF_SANITIZE "Build with AddressSanitizer + UndefinedBehaviorSanitizer" OFF)
option(MF_COVERAGE "Build with gcov instrumentation (-O0)" OFF)
option(MF_WERROR   "Treat warnings in MeasureFlow code as errors" OFF)

find_package(Threads REQUIRED)

set(MF_WARNING_FLAGS -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wold-style-cast
                     -Wnon-virtual-dtor -Woverloaded-virtual -Wnull-dereference)
if(MF_WERROR)
  list(APPEND MF_WARNING_FLAGS -Werror)
endif()

set(MF_COMMON_FLAGS "")
if(MF_SANITIZE)
  list(APPEND MF_COMMON_FLAGS -fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=undefined -g)
endif()
if(MF_COVERAGE)
  list(APPEND MF_COMMON_FLAGS --coverage -O0 -g)
endif()

# ---------------------------------------------------------------------------
# Catch2 (vendored amalgamation) compiled once as its own static library.
# ---------------------------------------------------------------------------
add_library(mf_catch2 STATIC third_party/catch_amalgamated.cpp)
target_include_directories(mf_catch2 SYSTEM PUBLIC third_party)
target_compile_options(mf_catch2 PRIVATE -w)
if(MF_SANITIZE)
  target_compile_options(mf_catch2 PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
endif()

# ---------------------------------------------------------------------------
# Core library
# ---------------------------------------------------------------------------
file(GLOB_RECURSE MF_CORE_SOURCES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp)
list(FILTER MF_CORE_SOURCES EXCLUDE REGEX ".*/src/main\\.cpp$")

add_library(measureflow_core STATIC ${MF_CORE_SOURCES})
target_include_directories(measureflow_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_include_directories(measureflow_core SYSTEM PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/third_party)
target_compile_definitions(measureflow_core PUBLIC MF_VERSION="${PROJECT_VERSION}")
target_compile_options(measureflow_core PRIVATE ${MF_WARNING_FLAGS} ${MF_COMMON_FLAGS})
target_link_libraries(measureflow_core PUBLIC Threads::Threads)
if(MF_SANITIZE OR MF_COVERAGE)
  target_link_options(measureflow_core PUBLIC ${MF_COMMON_FLAGS})
endif()

# ---------------------------------------------------------------------------
# Executable
# ---------------------------------------------------------------------------
add_executable(measureflow_backend src/main.cpp)
target_compile_options(measureflow_backend PRIVATE ${MF_WARNING_FLAGS} ${MF_COMMON_FLAGS})
target_link_libraries(measureflow_backend PRIVATE measureflow_core)

# ---------------------------------------------------------------------------
# Tests (Catch2)
# ---------------------------------------------------------------------------
file(GLOB MF_TEST_SOURCES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/tests/*.cpp)
add_executable(measureflow_tests ${MF_TEST_SOURCES})
target_include_directories(measureflow_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/tests)
target_compile_definitions(measureflow_tests PRIVATE
  MF_REPO_ROOT="${CMAKE_CURRENT_SOURCE_DIR}/..")
target_compile_options(measureflow_tests PRIVATE ${MF_WARNING_FLAGS} ${MF_COMMON_FLAGS})
target_link_libraries(measureflow_tests PRIVATE measureflow_core mf_catch2)

enable_testing()
add_test(NAME measureflow_tests COMMAND measureflow_tests)
