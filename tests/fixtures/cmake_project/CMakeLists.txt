cmake_minimum_required(VERSION 3.16)
project(boostopt_2a_fixture CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

add_library(stats STATIC stats.cpp)

add_executable(stats_test stats_test.cpp)
target_link_libraries(stats_test PRIVATE stats)

add_executable(stats_bench stats_bench.cpp)
target_link_libraries(stats_bench PRIVATE stats)

# An unrelated TU + test — must NOT be selected when BOOSTOPT targets stats.cpp (2A-1).
add_library(other STATIC other.cpp)
add_executable(other_test other_test.cpp)
target_link_libraries(other_test PRIVATE other)

enable_testing()
add_test(NAME stats_correctness COMMAND stats_test)
add_test(NAME stats_bench COMMAND stats_bench)
add_test(NAME other_correctness COMMAND other_test)
