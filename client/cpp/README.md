# cc-bench

C++ concurrency benchmarking client using `libcurl` non-blocking I/O.

## Prerequisites

```bash
pixi install
```

## Build

```bash
pixi run build
```

Produces `build/Release/bench.exe`.

## Usage

```bash
pixi run run -- --url http://localhost:3000 -c 2000 -e slow
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--url` | `http://localhost:3000` | Server address |
| `-c` | `10` | Number of concurrent connections |
| `-e` | `concurrent` | Endpoint path |
| `--timeout` | `30` | Request timeout in seconds |

## Implementation

- I/O engine: `curl_multi_perform` + `curl_multi_poll` (IOCP on Windows)
- Per-request context stored via `CURLOPT_PRIVATE`
- Concurrency data read from response body (same as Python clients)
- Reporter thread prints QPS / percentiles / concurrency every second

## Source layout

```
src/main.cpp        # single-file implementation
CMakeLists.txt      # C++23, find_package(CURL)
pixi.toml           # conda-forge dependencies
```
