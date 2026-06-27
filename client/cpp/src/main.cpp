#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <format>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <curl/curl.h>

using namespace std::chrono_literals;

// -- config ----------------------------------------------------------------

struct Config {
    std::string url = "http://localhost:3000";
    std::string endpoint = "concurrent";
    int concurrency = 10;
    double timeout = 30.0;
};

Config parse_args(int argc, char* argv[]) {
    Config c;
    for (int i = 1; i < argc; ++i) {
        std::string_view a = argv[i];
        auto next = [&] { return std::string_view(argv[++i]); };
        if (a == "--url" && i + 1 < argc) c.url = next();
        else if ((a == "-c" || a == "--concurrency") && i + 1 < argc) c.concurrency = std::stoi(std::string(next()));
        else if ((a == "-e" || a == "--endpoint") && i + 1 < argc) c.endpoint = next();
        else if (a == "--timeout" && i + 1 < argc) c.timeout = std::stod(std::string(next()));
    }
    return c;
}

// -- stats -----------------------------------------------------------------

struct Stats {
    std::mutex mtx;
    std::vector<double> latencies_ms;
    std::vector<int> concurrencies;
    uint64_t ok_ = 0;
    uint64_t fail_ = 0;

    void record(double ms, bool success, int concurrency) {
        std::lock_guard l(mtx);
        latencies_ms.push_back(ms);
        if (success) {
            concurrencies.push_back(concurrency);
            ++ok_;
        } else {
            ++fail_;
        }
    }

    auto snapshot() {
        struct Snapshot {
            uint64_t total, ok, fail;
            double p50{}, p95{}, p99{};
            double avg_c{};
            int max_c{}, min_c{};
        };
        Snapshot s;
        std::lock_guard l(mtx);
        s.ok = ok_;
        s.fail = fail_;
        s.total = ok_ + fail_;

        if (!latencies_ms.empty()) {
            auto sorted = latencies_ms;
            std::ranges::sort(sorted);
            auto p = [&](double pc) {
                size_t k = static_cast<size_t>((sorted.size() - 1) * pc / 100.0);
                return sorted[k];
            };
            s.p50 = p(50); s.p95 = p(95); s.p99 = p(99);
        } else {
            s.p50 = s.p95 = s.p99 = -1;
        }

        if (!concurrencies.empty()) {
            double sum = 0;
            s.max_c = concurrencies[0];
            s.min_c = concurrencies[0];
            for (auto v : concurrencies) {
                sum += v;
                if (v > s.max_c) s.max_c = v;
                if (v < s.min_c) s.min_c = v;
            }
            s.avg_c = sum / concurrencies.size();
        }
        return s;
    }
};

// -- per-request context ---------------------------------------------------

struct RequestCtx {
    std::string body;
    std::chrono::steady_clock::time_point start;
};

static size_t write_cb(char* data, size_t size, size_t nmemb, void* userp) {
    auto& buf = *static_cast<std::string*>(userp);
    buf.append(data, size * nmemb);
    return size * nmemb;
}

// -- globals for Ctrl+C ----------------------------------------------------

static std::atomic<int> g_running = 1;

#ifdef _WIN32
static BOOL WINAPI on_ctrl_event(DWORD) {
    g_running = 0;
    return TRUE;
}
#endif

// -- reporter --------------------------------------------------------------

void reporter_thread(Stats& stats) {
    uint64_t last_total = 0;
    auto last_time = std::chrono::steady_clock::now();

    while (g_running) {
        std::this_thread::sleep_for(1s);
        auto now = std::chrono::steady_clock::now();
        double elapsed = std::chrono::duration<double>(now - last_time).count();
        last_time = now;

        auto s = stats.snapshot();
        double qps = (s.total - last_total) / elapsed;
        last_total = s.total;

        auto t = std::chrono::system_clock::now();
        auto tt = std::chrono::system_clock::to_time_t(t);
        std::tm tm;
        localtime_s(&tm, &tt);

        std::string line = std::format(
            "{:02d}:{:02d}:{:02d} | Total: {}  OK: {}  Failed: {}",
            tm.tm_hour, tm.tm_min, tm.tm_sec, s.total, s.ok, s.fail);

        if (qps > 0.001)
            line += std::format(" | QPS: {:.1f}", qps);

        if (s.total > 0 && s.p50 >= 0)
            line += std::format(" | P50: {:.0f}ms  P95: {:.0f}ms  P99: {:.0f}ms", s.p50, s.p95, s.p99);
        else if (s.total > 0)
            line += " | (all requests failed -- no latency data)";

        if (s.total > 0)
            line += std::format(" | Concurrency: avg {:.1f}  max {}  min {}", s.avg_c, s.max_c, s.min_c);

        std::cout << line << std::endl;
    }
}

// -- main ------------------------------------------------------------------

int main(int argc, char* argv[]) {
#ifdef _WIN32
    SetConsoleCtrlHandler(on_ctrl_event, TRUE);
#endif

    Config cfg = parse_args(argc, argv);

    std::string target = cfg.url;
    if (!target.ends_with('/')) target += '/';
    target += cfg.endpoint;

    std::cout << std::format("Target: {}\n", target);
    std::cout << std::format("Concurrency: {}\n", cfg.concurrency);
    std::cout << std::format("Timeout: {}s\n", cfg.timeout);
    std::cout << "Press Ctrl+C to stop\n\n";

    // connectivity check
    {
        auto* easy = curl_easy_init();
        curl_easy_setopt(easy, CURLOPT_URL, target.c_str());
        curl_easy_setopt(easy, CURLOPT_TIMEOUT_MS, static_cast<long>(cfg.timeout * 1000));
        curl_easy_setopt(easy, CURLOPT_NOBODY, 1L);
        CURLcode rc = curl_easy_perform(easy);
        if (rc != CURLE_OK) {
            std::cerr << std::format("UNREACHABLE! {}\n", curl_easy_strerror(rc));
            curl_easy_cleanup(easy);
            return 1;
        }
        long http_code = 0;
        curl_easy_getinfo(easy, CURLINFO_RESPONSE_CODE, &http_code);
        std::cout << std::format("reachable (response: {})\n", http_code);
        curl_easy_cleanup(easy);
    }

    Stats stats;
    std::thread reporter(reporter_thread, std::ref(stats));

    std::vector<RequestCtx> ctxs(cfg.concurrency);
    std::vector<CURL*> handles(cfg.concurrency);
    auto* multi = curl_multi_init();

    for (int i = 0; i < cfg.concurrency; ++i) {
        auto* easy = curl_easy_init();
        handles[i] = easy;
        curl_easy_setopt(easy, CURLOPT_URL, target.c_str());
        curl_easy_setopt(easy, CURLOPT_TIMEOUT_MS, static_cast<long>(cfg.timeout * 1000));
        curl_easy_setopt(easy, CURLOPT_WRITEFUNCTION, write_cb);
        curl_easy_setopt(easy, CURLOPT_WRITEDATA, &ctxs[i].body);
        curl_easy_setopt(easy, CURLOPT_PRIVATE, reinterpret_cast<void*>(static_cast<intptr_t>(i)));
        ctxs[i].start = std::chrono::steady_clock::now();
        curl_multi_add_handle(multi, easy);
    }

    while (g_running) {
        int still = 0;
        curl_multi_perform(multi, &still);

        int left = 0;
        while (auto* msg = curl_multi_info_read(multi, &left)) {
            if (msg->msg != CURLMSG_DONE) continue;
            auto* easy = msg->easy_handle;

            void* priv = nullptr;
            curl_easy_getinfo(easy, CURLINFO_PRIVATE, &priv);
            int idx = static_cast<int>(reinterpret_cast<intptr_t>(priv));
            auto& ctx = ctxs[idx];

            auto now = std::chrono::steady_clock::now();
            double ms = std::chrono::duration<double, std::milli>(now - ctx.start).count();

            long http_code = 0;
            curl_easy_getinfo(easy, CURLINFO_RESPONSE_CODE, &http_code);
            bool ok = (http_code == 200);

            int concurrency = 0;
            if (ok && !ctx.body.empty()) {
                try { concurrency = std::stoi(ctx.body); }
                catch (...) {}
            }

            stats.record(ms, ok, concurrency);

            // re-arm the handle
            curl_multi_remove_handle(multi, easy);
            ctx.body.clear();
            ctx.start = now;
            curl_multi_add_handle(multi, easy);
        }

        curl_multi_poll(multi, nullptr, 0, 10, nullptr);
    }

    // stop reporter
    reporter.join();

    // clean up all handles still in multi
    int still = 0;
    curl_multi_perform(multi, &still);
    for (auto* easy : handles) {
        curl_multi_remove_handle(multi, easy);
        curl_easy_cleanup(easy);
    }
    curl_multi_cleanup(multi);

    // print summary
    auto s = stats.snapshot();
    std::cout << "\n=== Final Summary ===" << std::endl;
    std::cout << std::format("Total: {}  |  OK: {}  |  Failed: {}\n", s.total, s.ok, s.fail);
    if (s.total > 0 && s.p50 >= 0)
        std::cout << std::format("P50: {:.0f}ms  |  P95: {:.0f}ms  |  P99: {:.0f}ms\n", s.p50, s.p95, s.p99);
    if (s.total > 0)
        std::cout << std::format("Server concurrency: avg {:.1f}  max {}  min {}\n", s.avg_c, s.max_c, s.min_c);

    return 0;
}
