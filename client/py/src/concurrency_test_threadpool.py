import argparse
import threading
import time

import requests

from src._threadpool import ThreadPool
from src._test_common import percentile, print_summary


def do_request(url, timeout):
    start = time.perf_counter()
    try:
        r = requests.get(url, timeout=timeout)
        ms = (time.perf_counter() - start) * 1000
        return {"ok": r.ok, "ms": ms}
    except Exception as e:
        ms = (time.perf_counter() - start) * 1000
        return {"ok": False, "ms": ms, "error": str(e)}


def reporter(stats, stop_event, samples, args):
    last_ok = 0
    last_total = 0
    last_time = time.monotonic()
    while not stop_event.is_set():
        time.sleep(1)
        now = time.monotonic()
        total = len(stats)
        ok = sum(1 for s in stats if s["ok"])
        failed = total - ok
        elapsed = now - last_time
        qps = (total - last_total) / elapsed if elapsed > 0 else 0
        last_total = total
        last_ok = ok
        last_time = now

        if total == 0:
            if elapsed >= 5:
                print(f"[reporter] no requests completed in {elapsed:.0f}s", flush=True)
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
        if samples:
            avg_c = sum(samples) / len(samples)
            parts.append(
                f"Concurrency: avg {avg_c:.1f}  max {max(samples)}  min {min(samples)}"
            )
        else:
            parts.append("(no concurrency data -- monitor not running or failing)")
        print(" | ".join(parts), flush=True)


def monitor_worker(url, samples, stop_event, timeout):
    error_count = 0
    with requests.Session() as s:
        while not stop_event.is_set():
            try:
                r = s.get(url, timeout=timeout)
                samples.append(int(r.text.strip()))
                error_count = 0
            except Exception as e:
                error_count += 1
                if error_count <= 5:
                    print(f"[monitor] {type(e).__name__}: {e}", flush=True)
                elif error_count % 30 == 0:
                    print(f"[monitor] {error_count} consecutive monitor errors", flush=True)
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Concurrency test tool (ThreadPool)")
    parser.add_argument("--url", default="http://localhost:3000", help="Server URL")
    parser.add_argument("-c", "--concurrency", type=int, default=10, help="Worker thread count")
    parser.add_argument("-e", "--endpoint", default="concurrent", help="Endpoint path")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds")
    parser.add_argument("--monitor", action="store_true", help="Also sample /concurrent")
    args = parser.parse_args()

    raw_url = args.url.rstrip("/")
    if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
        raw_url = f"http://{raw_url}"
    base_url = raw_url
    target_url = f"{base_url}/{args.endpoint.lstrip('/')}"
    monitor_url = f"{base_url}/concurrent"

    print(f"Target: {target_url}")
    print(f"Concurrency (ThreadPool workers): {args.concurrency}")
    print(f"Timeout: {args.timeout}s")
    print("Press Ctrl+C to stop\n")

    print("Checking server connectivity...", end=" ", flush=True)
    try:
        r = requests.get(f"{base_url}/concurrent", timeout=args.timeout)
        body = r.text.strip()
        print(f"reachable (response: {body!r})", flush=True)
    except Exception as e:
        print(f"UNREACHABLE!", flush=True)
        print(f"[connectivity] {type(e).__name__}: {e}", flush=True)
        return

    stats = []
    samples = []
    stop_event = threading.Event()

    report_thread = threading.Thread(
        target=reporter, args=(stats, stop_event, samples, args), daemon=True
    )
    report_thread.start()

    if args.monitor:
        mon_thread = threading.Thread(
            target=monitor_worker,
            args=(monitor_url, samples, stop_event, args.timeout),
            daemon=True,
        )
        mon_thread.start()

    buffer_target = args.concurrency * 2
    tasks = []

    pool = ThreadPool(max_workers=args.concurrency)
    try:
        while not stop_event.is_set():
            while len(tasks) < buffer_target:
                tasks.append(pool.submit(do_request, target_url, args.timeout))

            if tasks[0].has_result():
                stats.append(tasks.pop(0).result())
            else:
                time.sleep(0.001)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        pool.cancel_all_pending_tasks()
        pool.wait()

    print_summary(stats, samples)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
