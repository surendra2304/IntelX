# INTELX Autonomous Quality Work — Progress

## Original goal
Improve agent usefulness on realistic, difficult, and dead-end research tasks. Evaluate actual application outputs, evidence, and citations—not only tests. Fix defects and keep regression coverage. Distinguish mock/local-fixture results from live external research. Do not report the project complete while material gaps remain.

## Checklist
- [x] Repository orientation, architecture/risk review, and verification caveats recorded in `REPO_ANALYSIS.md` and `notes/` (existing uncommitted artifacts preserved).
- [x] Strengthen evidence processing and API/report integrity from previously inspected review findings; regressions are in the test suite.
- [x] Fix benchmark synthesis selection so unit-bearing measures such as `160 Wh/kg` appear in the final report; preserve an application-level assertion.
- [x] Make evaluation verify report-body answer coverage and citation validity against the current run's claims; gate answer coverage at 100%.
- [x] Surface same-publisher/syndicated duplicate claims as non-independent when a task asks about corroboration.
- [x] Preserve explicit publication dates across ingestion and cached-source retrieval. Historical values are dated in reports; time-separated Wh/kg values are compared explicitly but caveated as not proven like-for-like.
- [x] Make injection-risk flags prominent in report prose and make mock critique abstain or disclose uncertainty rather than call unsupported, disputed, or unverified evidence “well-supported.”
- [x] Isolate golden-eval storage from the development app DB; verified all eight evals pass while the app server remained live and answered health checks.
- [x] Add explicit execution-mode provenance to both Markdown reports and machine-readable `report.json` metadata. It distinguishes mock fixtures, mock fallback, successful non-mock model calls, and configured-live/no-synthesis cases without overclaiming source retrieval; mock-mode banner is a required golden-eval coverage phrase.
- [x] Current code verification: Ruff check and format pass; **270 tests passed, 2 skipped**; all eight golden eval tasks passed all configured thresholds, including citation validity, answer coverage, and required provenance/report-specific caveats. Newly generated `report.json` artifacts record `meta.execution_mode=MOCK`; legacy artifacts from before this change may omit the field.
- [x] Current app verification: eight distinct tasks submitted through the HTTP API; **8/8 completed**, including no-evidence, disputed, poisoned-source, syndicated-source, and historical/current comparison cases. Each report met all required phrases and contained no forbidden phrases. After adding provenance to JSON metadata, a fresh HTTP task also confirmed `MOCK` in both the Markdown banner and `report_json.meta.execution_mode`.
- [~] Live-provider research remains blocked: no OpenAI/Anthropic/Tavily/search credentials are configured, `MOCK_MODE=True`, and the sandbox only permits outbound hosts `github.com`, `codeload.github.com`, `api.github.com`, `registry.npmjs.org`, `pypi.org`, and `files.pythonhosted.org`. Therefore no authentic external-search/provider result can be obtained here without misrepresenting the environment.
- [x] Final diff/secret-safe review and checkpoint commit/push to the fixed branch completed: `3ad7e44` (`Improve research answer quality and evaluation integrity`) pushed to `origin/arena/5808691e-intelx`.

## Current step
[~] Continue locally executable realism/pressure checks. Live-provider behavior itself remains unverified and cannot be exercised here (no provider/search credentials; outbound egress allowlist excludes provider/search hosts). Do not declare the real-world research objective complete.

## Key verification facts
- Branch: `arena/5808691e-intelx`; base HEAD at resume: `0921788bfd4c94bb93805493d43df2418495fb06`.
- `AGENT_PROGRESS.md` did not exist at resume; this file reconstructs status from prior notes, working changes, and tests.
- An eval attempt while the app and evaluator shared `data/intelx.db` raced the app worker and hit an invalid run-state transition. The evaluator now defaults to ignored `data/eval.db` (`INTELX_EVAL_DB_URL` can override it); a concurrent app+eval run passed, with 14 health checks returning successfully.
- The current app preview runs in mock mode on port 8000 (process `intelx-app-ae4ad342`). A fresh HTTP research request completed and marked both Markdown and JSON report provenance as `MOCK`; this is local-fixture validation only.
