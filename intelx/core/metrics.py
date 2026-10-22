"""INTELX Prometheus Telemetry Metrics Registry and Export."""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# 1. Runs metrics
RUNS_TOTAL = Counter(
    "intelx_runs_total",
    "Total research runs processed, labeled by status",
    ["status"],
)

RUN_DURATION_SECONDS = Histogram(
    "intelx_run_duration_seconds",
    "Research run execution duration in seconds",
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
)

ACTIVE_RUNS = Gauge(
    "intelx_active_runs",
    "Number of currently active research investigations in flight",
)

# 2. Pipeline item counts
SOURCES_RETRIEVED_TOTAL = Counter(
    "intelx_sources_retrieved_total",
    "Total external documents and sources retrieved",
)

CLAIMS_EXTRACTED_TOTAL = Counter(
    "intelx_claims_extracted_total",
    "Total factual and numeric claims extracted",
)

FINDINGS_PRODUCED_TOTAL = Counter(
    "intelx_findings_produced_total",
    "Total key findings generated, labeled by status",
    ["status"],  # verified, disputed, unverified
)

CONTRADICTIONS_DETECTED_TOTAL = Counter(
    "intelx_contradictions_detected_total",
    "Total contradictions and disputes detected",
)

# 3. Agent execution duration
AGENT_STEP_DURATION_SECONDS = Histogram(
    "intelx_agent_step_duration_seconds",
    "Agent task execution duration in seconds",
    ["agent"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

# 4. LLM model provider calls
MODEL_PROVIDER_CALLS_TOTAL = Counter(
    "intelx_model_provider_calls_total",
    "Total LLM provider completions, labeled by provider backend",
    ["provider"],
)


def get_metrics_payload() -> tuple[bytes, str]:
    """Render latest Prometheus metrics payload and content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
