did # CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

Requires a local Redis server (`redis-server`, default port 6379) and Python deps from `requirements.txt`.

- Flask web app: `python run.py` (binds `0.0.0.0:6060`, `debug=True`). `run.py` is the entry point; running `python app.py` still works but loads app.py as `__main__` (see the self-registration note below).
- Celery worker (separate terminal, required for async metric calculation): `celery -A app.celery worker --loglevel=info`
- Standalone DB migration: `python migrate_db.py` (migrations also run automatically on app startup via `check_and_migrate_db()`)

There is no test suite. Files like `test_*.py` in the repo root are ad-hoc debug scripts, not unit tests.

## Runtime State Layout

Data lives **outside the repo** under `~/.dtofbenchmarking/`:
- `~/.dtofbenchmarking/database.db` — SQLite database (WAL mode, 60s busy timeout)
- `~/.dtofbenchmarking/uploads/` — extracted dataset and submission contents (`uploads/submissions/<submission_id>/...`)

The empty `database.db` in the repo root is unused; `app.py` always reads from `~/.dtofbenchmarking/`.

`local_config.py` (gitignored, per-machine) exports `GIT_REPO_PATH` — the path to the *source* git repo whose commits get inspected for author/branch metadata when datasets/submissions are uploaded. If missing, the app falls back to `None` (CWD).

## Architecture

Single-file Flask monolith. `app.py` (~6300 lines) holds the Flask app, SQLAlchemy models, every route, ZIP ingestion, schema migration, and Celery setup. Two extracted modules:

> `app.py` starts with `sys.modules['app'] = sys.modules['__main__']` when run as `__main__`. Don't remove it: `app.py` imports `tasks`, `tasks` does `from app import ...`, and without the alias `python app.py` loads `app.py` twice — a duplicate Flask app + duplicate `SQLAlchemy()` not bound to the running app, which fails at request time with *"The current Flask app is not registered with this 'SQLAlchemy' instance"*. Anything importing `app` at module scope from a module that `app.py` itself imports must be defined above the `import tasks` line.

- `metric_engine.py` — dynamic metric evaluation. `evaluate_dynamic_metric()` `exec`s user-supplied Python code from `GlobalMetric.python_code` (compiled form cached by source text), injects `np`, and finds the first callable. `MetricContextBuilder(samples, sub, submission_folder)` builds per-sample dicts mixing ground-truth fields (`gt_*`), submission custom fields (`sub_*`), and computed entropies from submission histogram folders — **construct one per calculation pass and call `context_for(sample)`/`contexts_for_all()`**; its indexes are built once, which is what keeps metric calculation linear in dataset size instead of quadratic. `get_metric_context(sample, ...)` is the single-sample wrapper (it re-queries per call). `GtSourceContextBuilder` / `build_gt_source_context()` are the same pair for GT-source overrides. `sort_metrics_by_dependency()` topologically sorts `LeaderboardMetric`s so a metric can reference another metric's output by `target_name` or `global_metric.name`.
- `tasks.py` — Celery task `process_submission`. Loads samples (with optional `sample_filters`: search, include/exclude/prefix tags), builds context per sample, walks metrics in dependency order, applies per-metric `tag_filter` (`!tag` excludes), and aggregates per-sample results via `pooling_type` (mean/median/percentile). Per-sample metric values are persisted as `CustomField` rows keyed by `lm_<id>` so the Comparison view can render them.

### Hierarchy
`Project` → `Leaderboard` (M:N with global `Dataset`s via `leaderboard_datasets`) → `Submission`. `Dataset`s are **global** — not scoped to a project — and reused across leaderboards. Each `Dataset` has many `Sample`s; each `Sample` has `CustomField` rows (images / scalars / JSON / histograms / depth maps). `Sample` model also has `@property` shims (`histogram_data`, `signal_shape`) that fall back from legacy dedicated tables to the unified `CustomField` table — old data still lives in `HistogramData` / `SignalShape` and was partially migrated to `CustomField`.

### Metric/Visualization indirection
`GlobalMetric` / `GlobalVisualization` hold reusable Python code (functions). `LeaderboardMetric` / `LeaderboardVisualization` bind a global to a specific leaderboard with `arg_mappings` (JSON: function-arg-name → context-key), an optional `target_name` rename, `pooling_type`/`pooling_percentile`, `sort_direction`, and a per-metric `tag_filter`. `LeaderboardMetric.gt_source_submission_id` (nullable, default = the dataset's own GT) redirects every `gt_*` key of that metric to another submission of the same leaderboard — `metric_engine.build_gt_source_context()` / `apply_gt_source()` build the replacement, applied in `tasks.process_submission` and via `app.apply_metric_gt_source()` on the comparison paths. `MetricResult` caches computed aggregate values per (submission, leaderboard_metric).

### ZIP ingestion convention
Folder name inside a dataset/submission ZIP encodes the field type — see `process_dataset_zip()` and `detect_custom_fields()` in `app.py`:

| Folder prefix | Type | File pattern |
| :--- | :--- | :--- |
| `hist_*`, `raw_histogram`, `hist` | histogram | `<sample>.npz` (`bins`, `counts`) |
| `raw_*` | depth/map (2D) | `<sample>_<W>x<H>.npz` (dims mandatory) |
| `metric_*` (submissions only) | scalar metric | `<sample>.txt` containing a float |
| any other | auto-detect: `.png/.jpg/.bmp/.tiff` → image; `.txt` (float) → scalar; `.txt` (non-float) → text; `.json` → json |

`known_folders` (core dataset folders: `hist`, `pick`, `config`, `wave_shape`, `tags`, etc.) are skipped by `detect_custom_fields`. Sample alignment is by filename basename — submission files must share names with dataset samples.

### URL structure & routing
Most routes are nested under `/<project_name>/...`. `app.url_value_preprocessor` (`pull_project_name`) pops `project_name` into `g.project`, and `app.url_defaults` (`add_project_name`) auto-injects it into `url_for(...)`, so most templates can omit it. Legacy `/leaderboard/<id>` and `/comparison/<id>` routes 301-redirect to the project-scoped equivalents. `Dataset`-level routes (`/datasets`, `/dataset/<id>`) are **not** project-scoped because datasets are global.

### Schema migrations
`check_and_migrate_db()` runs on startup (and standalone via `migrate_db.py`). It uses `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` to incrementally add legacy columns (`tag_filter`, `git_author`, `project_id`, `pooling_type`, `scalar_width`, etc.) and creates a default `General` project to adopt orphaned leaderboards/datasets. When adding a new column to a model, also add a check+ALTER block here — there's no Alembic.

### DLP Safe Mode
For environments that block uploading Python source: the metric/visualization editor in the UI base64-encodes code client-side before POST; `handle_dlp_safe_code()` decodes server-side. The `scripts/obfuscator*.{html,py}` tools do the same out-of-band. Keep this round-trip working if you touch metric upload paths.

## Updating a deployment

`scripts/update.sh` fast-forwards the checkout to `origin/main`, runs `migrate_db.py`, and restarts the honcho stack. It refuses to act unless the checkout is clean, on `main`, and strictly behind the remote, so it can never discard local work. `./scripts/update.sh --check` reports status without changing anything.

The same is available in-app: **General Settings -> Version & Updates** has an "Update & restart" button (`POST /app-settings/update`), and the navbar shows an "N behind" badge on every page, fed by a 5-minute-cached `get_cached_update_status()` (uncached it would spawn ~6 git processes per request; `invalidate_update_status()` clears it after a check or update).

> **Security:** `update_application()` pulls code and restarts the stack, and this app has **no authentication**. Anyone who can reach port 6060 can deploy to the host, and there is no CSRF protection. This is enabled deliberately for trusted internal deployments — set `BENCHHUB_UPDATE_ENABLED=0` before exposing the app to any network you do not control. The endpoint refuses to act unless the checkout is clean, on `main`, and strictly behind the remote; those guards protect the checkout, not access.

## Conventions worth knowing

- `leaderboard_view` must not touch `sub.custom_fields` or issue per-(metric, submission) queries — with many submissions that is samples x fields x submissions ORM rows and metrics x submissions round trips. Custom-metric column names come from one `DISTINCT` query, the sample-name filter is derived once, and every custom-metric raw value is fetched in one batched query keyed by `(submission_id, name)`.
- Per-sample metric outputs are stored in two places: `MetricResult` (the aggregated leaderboard value) **and** a per-sample `CustomField` row named `lm_<leaderboard_metric_id>`. Both must stay in sync — `tasks.process_submission` deletes stale `CustomField`s before recompute.
- Metric python code is `exec`'d with `{'np': np}` only — `get_metric_context()` is the contract for what variable names are available (e.g., `gt_entropy`, `gt_<custom_field>`, `sub_<custom_field>`, `sub_entropy_<hist_folder>`, plus any prior metric's `target_name`).
- `SCALAR:<value>` in `arg_mappings` is a literal scalar binding (parsed as int/float/str), not a context key.
- The repo root contains many one-off scripts (`fix_*.py`, `migrate_*.py`, `debug_*.py`, `enable_*.py`). Most are historical and not invoked by the app; check git/timestamp before reusing one. Long-lived utility scripts live under `scripts/`.
- `app.py.bak`, `comparison_old.html`, and `leaderboard.html.bak*` are stale backups — don't edit them.
