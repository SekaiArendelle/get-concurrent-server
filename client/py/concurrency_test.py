import asyncio
import argparse
import time

import httpx


def percentile(sorted_data, p):
    n = len(sorted_data)
    if n == 0:
        return 0.0
    k = (n - 1) * p / 100
    f = int(k)
    c = f + 1
    if c >= n:
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


async def worker(client, url, stats):
    while True:
        try:
            start = time.perf_counter()
            r = await client.get(url)
            ms = (time.perf_counter() - start) * 1000
            stats.append({"ok": r.is_success, "ms": ms})
        except asyncio.CancelledError:
            break
        except Exception:
            ms = (time.perf_counter() - start) * 1000
            stats.append({"ok": False, "ms": ms})


async def monitor(client, url, samples):
    while True:
        try:
            r = await client.get(url)
            samples.append(int(r.text))
        except asyncio.CancelledError:
            break
        except Exception:
            pass
        await asyncio.sleep(1)


async def reporter(stats, samples):
    last_count = 0
    last_time = time.monotonic()
    try:
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            current_count = len(stats)
            elapsed = now - last_time
            qps = (current_count - last_count) / elapsed if elapsed > 0 else 0
            last_count = current_count
            last_time = now

            if current_count == 0:
                continue

            ms_vals = sorted(s["ms"] for s in stats)
            p50 = percentile(ms_vals, 50)
            p95 = percentile(ms_vals, 95)
            p99 = percentile(ms_vals, 99)

            parts = [
                time.strftime("%H:%M:%S"),
                f"Completed: {current_count}",
                f"QPS: {qps:.1f}",
                f"P50: {p50:.0f}ms  P95: {p95:.0f}ms  P99: {p99:.0f}ms",
            ]
            if samples:
                avg_c = sum(samples) / len(samples)
                parts.append(
                    f"Server concurrency: avg {avg_c:.1f}  max {max(samples)}  min {min(samples)}"
                )
            print(" | ".join(parts))
    except asyncio.CancelledError:
        pass


def print_summary(stats, samples):
    if not stats:
        return
    ms_vals = sorted(s["ms"] for s in stats)
    ok_count = sum(1 for s in stats if s["ok"])
    fail_count = len(stats) - ok_count
    p50 = percentile(ms_vals, 50)
    p95 = percentile(ms_vals, 95)
    p99 = percentile(ms_vals, 99)
    avg = sum(ms_vals) / len(ms_vals)

    print("\n=== Final Summary ===")
    print(f"Total: {len(stats)}  |  OK: {ok_count}  |  Failed: {fail_count}")
    print(
        f"Avg: {avg:.0f}ms  |  "
        f"P50: {p50:.0f}ms  |  P95: {p95:.0f}ms  |  P99: {p99:.0f}ms"
    )
    if samples:
        print(
            f"Server concurrency: avg {sum(samples)/len(samples):.1f}  "
            f"max {max(samples)}  min {min(samples)}"
        )


async def main():
    parser = argparse.ArgumentParser(description="Concurrency test tool")
    parser.add_argument(
        "--url", default="http://localhost:3000", help="Server URL"
    )
    parser.add_argument(
        "-c", "--concurrency", type=int, default=10, help="Concurrency level"
    )
    parser.add_argument(
        "-e", "--endpoint", default="concurrent", help="Endpoint path"
    )
    parser.add_argument(
        "--monitor", action="store_true", help="Also sample /concurrent"
    )
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    target_url = f"{base_url}/{args.endpoint.lstrip('/')}"
    monitor_url = f"{base_url}/concurrent"

    print(f"Target: {target_url}")
    print(f"Concurrency: {args.concurrency}")
    print("Press Ctrl+C to stop\n")

    stats = []
    samples = []

    async with httpx.AsyncClient() as client:
        worker_tasks = [
            asyncio.create_task(worker(client, target_url, stats))
            for _ in range(args.concurrency)
        ]
        all_tasks = list(worker_tasks)

        if args.monitor:
            monitor_task = asyncio.create_task(
                monitor(client, monitor_url, samples)
            )
            all_tasks.append(monitor_task)

        report_task = asyncio.create_task(reporter(stats, samples))
        all_tasks.append(report_task)

        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            for t in all_tasks:
                t.cancel()
            await asyncio.gather(*all_tasks, return_exceptions=True)

    print_summary(stats, samples)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
