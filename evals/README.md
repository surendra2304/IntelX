# INTELX Evaluation Suites

Contains offline benchmarks, citation verification evals, and truthfulness scoring datasets.

## 🎯 What Mock Mode Evals Prove

Mock Mode evaluations (`make eval` / `python -m evals.run`) verify **pipeline mechanical integrity and architectural invariants**:
1. **Citation Validity**: Machine-enforces that all `[S:id]` and `[C:id]` citations in output reports resolve to valid primary database records.
2. **Verbatim Span Integrity**: Enforces that `document.text[span_start:span_end] == quote` holds with zero character offset deviations.
3. **State Machine Execution**: Verifies that the complete DAG transitions through Planning, Discovery, Retrieval, Extraction, Verification, Analysis, Synthesis, and Review without deadlock or unhandled exceptions.
4. **Null Result Correctness**: Confirms that unsupported or unphysical objectives (e.g. perpetual energy in vacuum) conclude with `INSUFFICIENT_EVIDENCE` and surface research gaps rather than fabricating claims.
5. **Independence Deduplication**: Enforces that syndicated wire copies sharing $\ge 40\%$ 3-gram overlap are recognized as non-independent and do not inflate corroboration confidence.

### What Mock Mode Evals Do NOT Prove
Mock Mode evals do **NOT** measure real-world research quality, reasoning depth, or nuanced natural language synthesis. Contradiction recall, groundedness, and extraction precision in Mock Mode are verified by construction against deterministic fixture heuristics. These metrics only become true indicators of open-ended research quality when evaluated against live LLM providers (`openai_compatible` or `anthropic`).

## ⚡ Execution Latency Explanation
In early development revisions, the mock evaluation suite exhibited an average run latency of ~19.2 seconds per task. This occurred because `WebSearchConnector` generated placeholder public web URLs (`https://en.wikipedia.org/...`, `https://arxiv.org/...`), which caused `HttpFetchConnector` to initiate live external socket connections that stalled on TCP connection timeouts and DNS errors (10–15s per failure). With the local fixture routing fix, `WebSearchConnector` produces local `file://` fixture URIs that are resolved and normalized in memory and on local disk by `FileConnector` in < 1ms with zero network I/O, reducing average task execution latency to ~0.41s.
