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


async def worker(client, url, stats, concurrency):
    consecutive_fails = 0
    while True:
        try:
            start = time.perf_counter()
            r = await client.get(url)
            ms = (time.perf_counter() - start) * 1000
            stats.append({"ok": r.is_success, "ms": ms})
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
                print(f"[worker] {consecutive_fails} consecutive failures — "
                      f"last: {type(e).__name__}: {e}", flush=True)
            elif consecutive_fails % 200 == 0:
                print(f"[worker] {consecutive_fails} consecutive failures and counting",
                      flush=True)


async def monitor(client, url, samples):
    error_count = 0
    while True:
        try:
            r = await client.get(url)
            samples.append(int(r.text))
        except asyncio.CancelledError:
            break
        except Exception as e:
            error_count += 1
            if error_count <= 5:
                print(f"[monitor] {type(e).__name__}: {e} "
                      f"(body={r.text!r})", flush=True)
            elif error_count % 30 == 0:
                print(f"[monitor] {error_count} consecutive monitor errors — "
                      f"last: {type(e).__name__}", flush=True)
        await asyncio.sleep(1)


async def reporter(stats, samples):
    last_ok = 0
    last_total = 0
    last_time = time.monotonic()
    all_fail_since = None
    try:
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            total = len(stats)
            ok = sum(1 for s in stats if s["ok"])
            failed = total - ok
            elapsed = now - last_time
            qps = (total - last_total) / elapsed if elapsed > 0 else 0

            delta_total = total - last_total
            delta_ok = ok - last_ok

            last_total = total
            last_ok = ok
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
                parts.append("(all requests failed — no latency data)")

            if delta_total > 0 and delta_ok == 0:
                if all_fail_since is None:
                    all_fail_since = now
                fail_duration = now - all_fail_since
                warn = f"! ALL {delta_total} NEW REQUESTS FAILED"
                if fail_duration >= 3:
                    warn += f" — failing for {fail_duration:.0f}s"
                parts.append(warn)
            else:
                all_fail_since = None

            if samples:
                avg_c = sum(samples) / len(samples)
                parts.append(
                    f"Concurrency: avg {avg_c:.1f}  max {max(samples)}  min {min(samples)}"
                )
            else:
                parts.append("(no concurrency data — monitor not running or failing)")

            print(" | ".join(parts), flush=True)
    except asyncio.CancelledError:
        pass


def print_summary(stats, samples):
    if not stats:
        return
    ms_vals = sorted(s["ms"] for s in stats if s["ok"])
    ok_count = sum(1 for s in stats if s["ok"])
    fail_count = len(stats) - ok_count

    print("\n=== Final Summary ===")
    print(f"Total: {len(stats)}  |  OK: {ok_count}  |  Failed: {fail_count}")

    if ms_vals:
        p50 = percentile(ms_vals, 50)
        p95 = percentile(ms_vals, 95)
        p99 = percentile(ms_vals, 99)
        avg = sum(ms_vals) / len(ms_vals)
        print(
            f"Avg: {avg:.0f}ms  |  "
            f"P50: {p50:.0f}ms  |  P95: {p95:.0f}ms  |  P99: {p99:.0f}ms"
        )
    else:
        print("No successful requests — no latency data")

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
        "--timeout", type=float, default=30.0, help="Request timeout in seconds"
    )
    parser.add_argument(
        "--monitor", action="store_true", help="Also sample /concurrent"
    )
    args = parser.parse_args()

    raw_url = args.url.rstrip("/")
    if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
        raw_url = f"http://{raw_url}"
    base_url = raw_url
    target_url = f"{base_url}/{args.endpoint.lstrip('/')}"
    monitor_url = f"{base_url}/concurrent"

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

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(args.timeout),
    ) as client:
        worker_tasks = [
            asyncio.create_task(worker(client, target_url, stats, args.concurrency))
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
