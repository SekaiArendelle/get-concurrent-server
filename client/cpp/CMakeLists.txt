cmake_minimum_required(VERSION 3.26)
project(cc-bench LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(CURL REQUIRED)

add_executable(bench src/main.cpp)
target_link_libraries(bench PRIVATE CURL::libcurl)
