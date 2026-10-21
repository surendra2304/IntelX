# Task 2 checkpoint — IntelX

Updated: 2026-10-20 (pass 9)

## Workstream and constraints

Task 2 is evidence-driven research in IntelX. Work only in this checkout. Preserve source provenance, never invent or silently promote claims, and do not commit, push, open PRs, alter workflows/infrastructure, expose secrets, or perform unrelated security testing.

## Branch and worktree

- Branch: `automation/friday-universe-task-2` (tracking `origin/main`).
- No commits or external GitHub writes were made.
- Uncommitted code changes: `intelx/agents/citations.py`, `intelx/agents/verifier.py`, `intelx/core/report.py`, `intelx/db/demo_seeder.py`, `intelx/web/routes.py`, `intelx/web/static/app.js`, `intelx/web/templates/report.html`, `tests/test_artifacts.py`, `tests/test_citation_validation.py`, `tests/test_friday_api.py`, `tests/test_orchestration.py`, `tests/test_trust.py`, and `tests/test_web.py`.
- Both `.github/friday-continuation/task-2-checkpoint.md` and `.github/friday-continuation/task-2-next-run.md` are handoff files and remain uncommitted.

## Implemented

### Citation identity and source provenance

- `CitationValidator.validate` and `repair_or_strip` use shared `resolve_citation_id` logic.
- `format_citation_id` retains an at-least-eight-character citation token and extends it when needed to uniquely resolve among IDs known to a report/export. Markdown and text exports use it for source and claim citations.
- Text export gathers claim IDs globally before formatting findings so duplicate prefixes across separate findings remain disambiguated.
- `/api/citation/{kind}/{token}` uses shared resolution: missing IDs return 404 and ambiguous source/claim prefixes return 409. SQL `LIKE` wildcards in user-provided prefixes are escaped.
- Report claim/source badges and demo-seeded Markdown use complete IDs; spoken export attributes claims to source names rather than shortened citation IDs.
- Regression coverage includes cross-finding duplicate claim prefixes, export citation validation, ambiguous/uniquely extended source and claim prefixes, complete IDs on report pages, and literal `%`/`_` token matching with real source/claim rows.

### Freshness and currentness

- `intelx/core/report.py` parses source publication timestamps consistently (naive timestamps treated as UTC); when a current-status objective cites evidence published before today, the finding is explicitly marked historical and not proof of current status.
- Current-status findings backed by a source without a publication date explicitly say freshness/currentness cannot be verified.
- Source bibliography no longer substitutes the report's current timestamp when `retrieved_at` is absent. It reports missing retrieval and publication timestamps as unrecorded/unknown, and explicitly distinguishes retrieval time from currentness.
- Report source table shows publication date or “Not recorded; freshness unknown”, retrieval time, and a currentness caveat.
- Citation drawer API returns `published_at`; drawer UI displays publication-date uncertainty and clarifies that retrieval time does not establish currentness.
- Regression coverage exercises stale and undated sources in current-status reports, plus web assertions for report and citation-source metadata.

### Explicit FRIDAY horizon through verification

- `/api/v1/friday/research` persists `query_scope.time_horizon` in the run's `scope_json`.
- `intelx/agents/verifier.py` parses only explicitly supplied positive `Nd` and `Ny` horizons. It compares source `published_at` to a single UTC verification time, interpreting naive datetimes as UTC, and passes staleness into `compute_confidence_score`.
- Missing publication dates, missing horizons, unsupported values, and unrepresentably large horizons do not trigger a stale penalty. There is no default cutoff, retrieval-time fallback, or claim-status promotion.
- `tests/test_friday_api.py` asserts that submitted `30d` persists. `tests/test_orchestration.py` persists `{"query_scope": {"time_horizon": "30d"}}` in the deterministic run and uses a `VerifierAgent` spy to confirm the scope reaches verification while run status is `VERIFYING`.
- `tests/test_trust.py` covers old aware and naive timestamps, recent and missing timestamps, no horizon, unsupported values, the exact cutoff, and timestamps one microsecond before and after cutoff.
- The cutoff boundary test uses a fixed UTC verification instant and explicit parsed `30d` horizon. Exact-cutoff publications are fresh; one microsecond before is stale and one microsecond after is fresh. Both adjacent cases are checked in UTC and an equivalent `+05:30` timezone.

## Validation

Commands were executed sequentially after the latest boundary regression:

- `.venv/bin/python -m pytest -q tests/test_trust.py::test_verifier_treats_exact_horizon_cutoff_as_fresh_across_timezones tests/test_trust.py::test_verifier_applies_only_explicit_time_horizon_to_confidence` — **2 passed** (0.23s).
- `.venv/bin/python -m pytest -q` — **302 passed, 3 deselected** (46.66s).
- `.venv/bin/ruff check . && git diff --check` — **passed**.
- `.venv/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/intelx-wheel-check .` — **passed**; built `intelx-2.0.0-py3-none-any.whl` (290,052 bytes; SHA-256 `563450af5feceda74ce2df4b2c6222ab31a9ed465c10a118d75324acca143174`).
- A separate mypy/pyright/basedpyright check remains unavailable because no executable or configuration was found previously.

## Unresolved work and exact next coding action

No known blocker. The current implementation and boundary regression are green. Continue the product implementation rather than repeating citation identity, report freshness, horizon propagation, or cutoff-boundary research.

**Next coding action:** inspect the current FRIDAY research/report path and add a focused regression for an invalid or missing source publication timestamp representation at the report boundary, ensuring it is surfaced as unknown freshness rather than crashing or being interpreted as current. Follow existing timestamp parsing conventions; only change production code if the test demonstrates a defect. Keep all claim statuses and source provenance explicit.


## Runner-enforced checkpoint (2026-10-20T23:13:16Z)

Pass 10 ended: failed with exit code 1. The coding engine did not revise this checkpoint; the next pass must inspect the source diff and test output.


## Scheduled run summary (2026-10-20T23:13:16Z)

- Result: failed
- Active coding seconds: 1806
- Coding passes: 10
- Changed source paths: 13
- Failures: Pass 10 failed with exit 1. See log pass-10.log.


## Runner-enforced checkpoint (2026-10-21T01:01:34Z)

Pass 1 ended: failed with exit code 1. The coding engine did not revise this checkpoint; the next pass must inspect the source diff and test output.


## Scheduled run summary (2026-10-21T01:01:34Z)

- Result: failed
- Active coding seconds: 5
- Coding passes: 1
- Changed source paths: 14
- Failures: Pass 1 failed with exit 1. See log pass-1.log.
