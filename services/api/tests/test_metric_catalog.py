"""The API's list of metrics is the one rl_analysis computes (A40). No database needed."""

from ma_api.stats import METRIC_IDS
from rl_analysis.registry import METRICS


def test_the_api_knows_exactly_the_computed_metrics() -> None:
    assert {metric.id for metric in METRICS} == METRIC_IDS


def test_every_route_of_the_site_declares_what_it_answers() -> None:
    """The site's client is generated from these: an undeclared answer would type as anything."""
    from ma_api.app import create_app
    from ma_api.settings import Settings

    paths = create_app(Settings(database_url="unused")).openapi()["paths"]
    for path, operations in paths.items():
        for method, operation in operations.items():
            answers = operation["responses"]
            ok = next((code for code in ("200", "201", "202") if code in answers), None)
            # No body to describe: 204, the 202 of an erasure, the redirects of a sign-in.
            if ok is None or path == "/health" or "content" not in answers[ok]:
                continue
            content = answers[ok].get("content", {}).get("application/json", {})
            assert content.get("schema", {}).get("$ref"), f"{method.upper()} {path}"
