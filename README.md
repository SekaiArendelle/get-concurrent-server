# get-concurrent-server

A Rust HTTP server that tracks and exposes current concurrent request count, plus Python and C++ test clients.

## Server

```bash
cargo run
```

Starts on `http://localhost:3000`.

### Endpoints

| Path | Description |
|---|---|
| `GET /concurrent` | Returns current in-flight request count (includes itself) |
| `GET /slow` | Sleeps ~1s (normal distribution, σ=200ms), returns the concurrency count at response time — used to observe concurrency buildup |

## Test Clients

| Language | Directory | Description |
|---|---|---|
| Python | [`client/py/`](client/py/README.md) | asyncio (`httpx`) and ThreadPool (`requests`) |
| C++ | [`client/cpp/README.md`](client/cpp/README.md) | `libcurl` `multi_*` non-blocking I/O |
