import time


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
        print("No successful requests -- no latency data")

    if samples:
        print(
            f"Server concurrency: avg {sum(samples)/len(samples):.1f}  "
            f"max {max(samples)}  min {min(samples)}"
        )
