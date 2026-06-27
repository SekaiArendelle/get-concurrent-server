# get-concurrent-server

A Rust HTTP server that tracks and exposes current concurrent request count, plus a Python test client.

## Server

```bash
cargo run
```

Starts on `http://localhost:3000`.

### Endpoints

| Path | Description |
|---|---|
| `GET /concurrent` | Returns current in-flight request count (includes itself) |
| `GET /slow` | Sleeps ~1s (normal distribution, σ=200ms) — used to observe concurrency buildup |

## Test Clients

See [`client/py/README.md`](client/py/README.md) for usage.

Two implementations are available:
- **asyncio** — `httpx.AsyncClient` with distributed connection pools
- **ThreadPool** — custom thread pool with task queue (ported from physicslab)
