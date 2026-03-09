import json
import time

from modules.perf_monitor import PerfSampler


def test_perf_sampler_writes_metrics(tmp_path):
    logs = []
    metrics_file = tmp_path / "metrics.jsonl"
    sampler = PerfSampler(
        name="unit",
        sample_interval=5.0,
        history_size=5,
        log_fn=logs.append,
        metrics_file=str(metrics_file),
    )

    start = sampler.start_iteration()
    time.sleep(0.01)
    sampler.end_iteration(start)

    start = sampler.start_iteration()
    time.sleep(0.01)
    sampler.end_iteration(start, failed=True)

    assert logs, "PerfSampler should emit log output when forced"
    assert metrics_file.exists(), "PerfSampler should create metrics file"

    payloads = [json.loads(line) for line in metrics_file.read_text().splitlines() if line.strip()]
    assert payloads, "PerfSampler should append JSON payloads"
    assert payloads[-1]["failures"] >= 1
    assert payloads[-1]["iter_avg_ms"] >= 0
