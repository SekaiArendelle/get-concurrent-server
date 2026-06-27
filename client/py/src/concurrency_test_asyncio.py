import asyncio
import argparse
import time

import httpx

from src._test_common import percentile, print_summary


async def worker(client, url, stats, samples, concurrency):
    consecutive_fails = 0
    while True:
        try:
            start = time.perf_counter()
            r = await client.get(url)
            ms = (time.perf_counter() - start) * 1000
            stats.append({"ok": r.is_success, "ms": ms})
            if r.is_success:
                samples.append(int(r.text.strip()))
            consecutive_fails = 0
        except asyncio.CancelledError:
            break
        except Exception as e:
            ms = (time.perf_counter() - start) * 1000
            stats.append({"ok": False, "ms": ms})
            consecutive_fails += 1
            if len(stats) <= concurrency:
                print(f"[worker] {type(e).__name__}: {e}", flush=True)
            elif consecutive_fails == 50:
                print(f"[worker] {consecutive_fails} consecutive failures -- "
                      f"last: {type(e).__name__}: {e}", flush=True)
            elif consecutive_fails % 200 == 0:
                print(f"[worker] {consecutive_fails} consecutive failures and counting",
                      flush=True)


async def reporter(stats, samples):
    last_total = 0
    last_time = time.monotonic()
    try:
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            total = len(stats)
            ok = sum(1 for s in stats if s["ok"])
            failed = total - ok
            elapsed = now - last_time
            qps = (total - last_total) / elapsed if elapsed > 0 else 0
            last_total = total
            last_time = now

            if total == 0:
                if elapsed >= 5:
                    print(f"[reporter] no requests completed in {elapsed:.0f}s",
                          flush=True)
                continue

            ms_vals = sorted(s["ms"] for s in stats if s["ok"])
            parts = [
                time.strftime("%H:%M:%S"),
                f"Total: {total}  OK: {ok}  Failed: {failed}",
            ]
            if qps > 0:
                parts.append(f"QPS: {qps:.1f}")
            if ms_vals:
                p50 = percentile(ms_vals, 50)
                p95 = percentile(ms_vals, 95)
                p99 = percentile(ms_vals, 99)
                parts.append(f"P50: {p50:.0f}ms  P95: {p95:.0f}ms  P99: {p99:.0f}ms")
            elif total > 0:
                parts.append("(all requests failed -- no latency data)")

            avg_c = sum(samples) / len(samples) if samples else 0
            parts.append(
                f"Concurrency: avg {avg_c:.1f}  max {max(samples)}  min {min(samples)}"
                if samples
                else "(no concurrency data)"
            )

            print(" | ".join(parts), flush=True)
    except asyncio.CancelledError:
        pass


async def main():
    parser = argparse.ArgumentParser(description="Concurrency test tool (asyncio)")
    parser.add_argument("--url", default="http://localhost:3000", help="Server URL")
    parser.add_argument("-c", "--concurrency", type=int, default=10, help="Concurrency level")
    parser.add_argument("-e", "--endpoint", default="concurrent", help="Endpoint path")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds")
    parser.add_argument(
        "--client-pool", type=int, default=0,
        help="Number of AsyncClient pools (0 = one per worker)"
    )
    args = parser.parse_args()

    raw_url = args.url.rstrip("/")
    if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
        raw_url = f"http://{raw_url}"
    base_url = raw_url
    target_url = f"{base_url}/{args.endpoint.lstrip('/')}"

    print(f"Target: {target_url}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Timeout: {args.timeout}s")
    print("Press Ctrl+C to stop\n")

    stats = []
    samples = []

    print("Checking server connectivity...", end=" ", flush=True)
    try:
        async with httpx.AsyncClient(timeout=args.timeout) as probe:
            r = await probe.get(f"{base_url}/concurrent")
            body = r.text.strip()
            print(f"reachable (response: {body!r})", flush=True)
    except Exception as e:
        print(f"UNREACHABLE!", flush=True)
        print(f"[connectivity] {type(e).__name__}: {e}", flush=True)
        return

    num_pools = args.client_pool or args.concurrency
    limits = httpx.Limits(max_connections=None, max_keepalive_connections=None)
    pools = [
        httpx.AsyncClient(timeout=httpx.Timeout(args.timeout), limits=limits)
        for _ in range(num_pools)
    ]

    worker_tasks = [
        asyncio.create_task(
            worker(pools[i % num_pools], target_url, stats, samples, args.concurrency)
        )
        for i in range(args.concurrency)
    ]
    all_tasks = list(worker_tasks)

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
        for c in pools:
            await c.aclose()

    print_summary(stats, samples)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
