"""The API's list of metrics is the one rl_analysis computes (A40). No database needed."""

from ma_api.stats import METRIC_IDS
from rl_analysis.registry import METRICS


def test_the_api_knows_exactly_the_computed_metrics() -> None:
    assert {metric.id for metric in METRICS} == METRIC_IDS
