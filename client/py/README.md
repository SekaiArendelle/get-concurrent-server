# Test Clients

Two test clients for concurrency benchmarking against a target server.

Both read concurrency data directly from `/slow` response body — no separate
monitor request needed.

## Dependencies

- **asyncio**: `httpx`
- **ThreadPool**: `requests`

```bash
uv sync
```

## asyncio

```bash
uv run python -m src.concurrency_test_asyncio -c 50 -e slow
```

Uses `httpx.AsyncClient`. Workers are distributed across configurable client pools
to avoid connection pool bottlenecks.

| Flag | Default | Description |
|---|---|---|
| `--url` | `http://localhost:3000` | Server address |
| `-c` | `10` | Concurrency level |
| `-e` | `concurrent` | Endpoint path |
| `--client-pool` | `0` | `AsyncClient` pool count (`0` = one per worker) |

## ThreadPool

```bash
uv run python -m src.concurrency_test_threadpool -c 50 -e slow
```

Uses a custom `ThreadPool` (ported from `physicslab`). Tasks are submitted to a
queue; worker threads pick them up in a tight polling loop. The main thread keeps
the queue populated and collects results via `has_result()` polling.

| Flag | Default | Description |
|---|---|---|
| `--url` | `http://localhost:3000` | Server address |
| `-c` | `10` | Worker thread count |
| `-e` | `concurrent` | Endpoint path |

## Source layout

```
src/
├── __init__.py
├── _test_common.py              # Shared: percentile, print_summary
├── _threadpool.py               # ThreadPool implementation
├── concurrency_test_asyncio.py  # asyncio test
└── concurrency_test_threadpool.py  # ThreadPool test
```
