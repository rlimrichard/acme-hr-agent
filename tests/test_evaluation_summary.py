"""The published latency sample stays fixed and uses nearest-rank p95."""

from evaluation.summarize_results import LATENCY_SAMPLE_IDS, percentile_95


def test_latency_sample_has_fifteen_unique_cases():
    assert len(LATENCY_SAMPLE_IDS) == len(set(LATENCY_SAMPLE_IDS)) == 15


def test_nearest_rank_p95():
    assert percentile_95(list(range(1, 16))) == 15
    assert percentile_95(list(range(1, 26))) == 24
