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
| `GET /slow` | Sleeps 10 seconds — used to observe concurrency buildup |

## Test Client

```bash
cd client/py
uv run concurrency_test.py -c 50 -e concurrent --monitor
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--url` | `http://localhost:3000` | Server address |
| `-c` | `10` | Concurrency level |
| `-e` | `concurrent` | Endpoint path (`concurrent` or `slow`) |
| `--monitor` | off | Also poll `/concurrent` to observe server concurrency |

Press `Ctrl+C` to stop — prints a final summary with percentiles.

### Examples

```bash
# 20 concurrent requests hitting /slow, with server monitoring
uv run concurrency_test.py -c 20 -e slow --monitor

# 100 concurrent requests hitting /concurrent
uv run concurrency_test.py -c 100 -e concurrent
```
