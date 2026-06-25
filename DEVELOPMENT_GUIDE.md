# EY-DAClient Development Guide

This document summarizes the current architecture, design decisions, runtime
contracts, and the implementation rules that emerged during the previous
development sessions.

The project is a Windows desktop data-analysis client built with PySide6. Its
core workflow is intentionally fixed:

1. The user imports one or more spreadsheet datasets.
2. The client profiles and caches them locally.
3. The client sends a compact, structured request to Dify.
4. Dify returns Python code and, when needed, a structured analysis plan.
5. The client validates the code locally, runs a preflight sample execution,
   shows the code to the user, and then executes the approved code against the
   full cached data.
6. Runtime failures or semantic mismatches are sent back to Dify for repair.

## 1. Product direction

The product is not a general chat app. It is a data-analysis workstation whose
primary goals are:

- multi-file joint analysis;
- large-file handling;
- reliable execution of Dify-generated Python code locally;
- clear, dense, results-first UI;
- mature western desktop design language;
- Dify as the default provider, with DevOps-only Gemini debugging support.

The long-term product philosophy discussed in this thread is:

- keep Dify as the core brain for code generation;
- keep the local client responsible for data access, validation, execution, and
  UI;
- increase reliability by adding contracts, not by weakening the workflow;
- favor explicit data IDs, explicit joins, explicit grain, and explicit
  requirement completion;
- avoid ambiguous fallback behavior that hides errors or silently changes
  analysis intent.

## 2. Repository layout

Main modules:

- `app/` entry points and process bootstrap.
- `config/` runtime paths, settings, logging, DevOps gating.
- `core/` data profiling, contracts, result schema, prompt construction,
  execution, join resolution, session support.
- `dify/` API client and workflow wrapper.
- `llm/` provider abstraction and cancellation support.
- `services/` higher-level service glue.
- `ui/` PySide6 widgets, main window, popovers, result panels, settings dialog.
- `workers/` background workers for profiling and analysis.
- `tests/` behavior and packaging smoke tests.

## 3. Key runtime architecture

### 3.1 Startup

The desktop app starts through `app/main.py`.

Important behavior:

- logging is enabled before Qt imports;
- crash logging is persisted to a file, including unhandled exceptions;
- in frozen builds, worker mode is used to execute generated scripts without
  opening another GUI instance;
- `sys.excepthook`, `threading.excepthook`, and `faulthandler` are used for
  crash visibility.

### 3.2 Dataset preprocessing and caching

The dataset pipeline is built around `core/preprocessor.py`.

Current behavior:

- supports `.xlsx`, `.xls`, and `.xlsm`;
- computes a stable `dataset_id` from path, size, and mtime fingerprint;
- assigns stable `sheet_id` values per workbook sheet;
- caches each sheet to Parquet under the user cache directory;
- creates a representative sample cache for preflight and preview use;
- profiles rows, columns, dtypes, null counts, approximate unique counts, and
  sample rows;
- supports streaming large XLSX/XLSM workbooks into cached Parquet without
  materializing the whole workbook in memory.

Large-file policy:

- large XLSX/XLSM files are streamed sheet by sheet;
- large legacy `.xls` files are not streamed and should be converted to `.xlsx`;
- the threshold is controlled by `LARGE_EXCEL_MB` and `LARGE_DATASET_ROWS`.

### 3.3 Local data access layer

The local execution contract is implemented by `core/data_access.py`.

The generated code gets:

- `data.get(dataset_id, sheet_id, columns=[...])`
- `dfs["dataset_id"]["sheet_id"]`
- `data.merge(...)`
- `data.sql(..., sources={...})`

Important design points:

- `data.get()` should be the preferred path for ordinary loads;
- `data.sql()` is the preferred path for large joins and aggregations;
- cross-dataset arithmetic must not rely on row order or row index;
- all data access is backed by cached local files, not the original workbook;
- the runtime exposes auditing records for loads and joins.

### 3.4 Analysis contract

`core/analysis_contract.py` enforces a strict two-layer contract:

1. the analysis plan produced by Dify must be explicit and internally
   consistent;
2. the generated Python code must contain the required structure and dataset
   references.

Required ideas:

- every requirement must have an ID;
- multi-dataset requests must have explicit source lists and join/alignment
  rules;
- a result grain is required when multiple datasets are used;
- many-to-many joins require explicit confirmation;
- generated code must define `ANALYSIS_SPEC`;
- generated code must call `result.mark_requirement(...)` for every completed
  requirement;
- multi-dataset code must use audited alignment via `data.merge()` or
  `data.sql()`.

### 3.5 Execution model

`core/executor.py` runs generated code in a child process.

Current guarantees:

- code is executed in isolation;
- memory and timeout limits are enforced;
- local cached data is injected into the runtime;
- the result collector writes a JSON result file;
- the executor records runtime audits, peak memory, and sample/full mode;
- semantic validation is run after execution, not just syntax/security checks.

The execution flow is:

1. build a manifest from all loaded files;
2. generate a bootstrap script that loads the local data catalog;
3. run a child Python process;
4. capture stdout/stderr;
5. deserialize structured result data;
6. run semantic audits;
7. if needed, trigger a repair round through Dify.

### 3.6 Result schema

`core/analysis_result.py` defines the result contract exposed to generated code.

Available APIs:

- `result.set_summary(text)`
- `result.add_metric(label, value, unit="", detail="")`
- `result.add_table(title, dataframe=...)`
- `result.add_chart(title, matplotlib_figure=..., caption="")`
- `result.add_insight(title, detail)`
- `result.add_warning(title, detail)`
- `result.mark_requirement(requirement_id)`
- `result.add_audit(record)`
- `result.extend_audit(records)`

The result object supports:

- summary;
- metrics;
- tables;
- charts;
- insights;
- audit trail;
- completed requirement IDs;
- raw output fallback.

### 3.7 Dify workflow layer

`dify/client.py` handles the HTTP contract and streaming parsing.
`dify/workflow.py` coordinates generation, validation, sample preflight, full
execution, and repair.

Important design points:

- the client only sends `task_type`, `context`, and `query`;
- `system` is deliberately removed from the client-side request contract;
- Dify can branch by `task_type`;
- long user queries are transported via `context.user_query_full`;
- if the query exceeds the Dify limit, the full query is preserved in context;
- clarification results are supported as a first-class workflow outcome;
- analysis errors can trigger a repair branch instead of a hard stop.

## 4. Dify contract

The current Dify setup is documented in `DIFY_WORKFLOW_SETUP.md`.

The client expects the workflow to expose:

- overview branch;
- analysis planner branch;
- clarification branch;
- Python generator branch;
- repair branch.

The most important rules:

- keep exactly three start inputs: `task_type`, `context`, `query`;
- do not reintroduce a `system` input on the client;
- use a structured planner that returns analysis requirements;
- use explicit dataset IDs and sheet IDs;
- use the repair branch for runtime and semantic failures;
- publish the workflow after every Dify change before testing.

## 5. Multi-file analysis design

The current architecture supports multi-file analysis on purpose.

What changed from earlier single-file thinking:

- every imported file gets a stable `dataset_id`;
- same-named files are not forced to overwrite each other;
- candidate joins are profiled by `core/multi_file_resolver.py`;
- the prompt context includes candidate relationships;
- the planner must describe explicit alignment rules for any multi-dataset task;
- generated code must not assume same row order across files;
- cross-file formulas must either join explicitly or aggregate before combining.

Examples the system is expected to handle:

- compare a column from dataset A with a metric from dataset B;
- calculate `A.col1 + B.col2 - C.col3`;
- join A and B on a business key, then aggregate by a grain defined in the
  request;
- analyze one dataset and use another only for filtering or enrichment;
- handle multiple sheets inside the same workbook as distinct logical sources
  when needed.

## 6. Large-file design

The project intentionally separates profiling, preview, and execution:

- profiling can use representative samples;
- cached Parquet enables repeated reads without re-opening the workbook;
- DuckDB is used so large joins and aggregations can happen without loading the
  full workbook into Pandas first;
- the preflight execution uses sampled data to catch obvious code problems
  earlier and cheaper than a full run.

Large-file practical rules:

- prefer `data.sql()` for large joins and group-bys;
- prefer column projection in `data.get(..., columns=[...])`;
- keep result tables compact;
- do not return unbounded raw rows to the UI;
- if the workbook is very large, expect the preflight to sample before the full
  execution.

## 7. UI/UX rules that have been established

The UI was repeatedly refined to match a results-first, mature desktop style.

Important product rules:

- imported files live in a shared application-level Dataset Library;
- the initial user action is dataset import, not feature selection;
- feature choices appear only after at least one dataset is ready;
- the initial title bar does not expose dataset selection;
- feature switching uses one title-bar Mode menu, not separate mode buttons;
- the Dataset Library is a floating global surface rather than an analysis sidebar;
- dataset scope uses whole-row highlighting: one target in cleaning and up to
  three sources in analysis;
- cleaning must consume the highlighted library target instead of presenting a
  second dataset selector;
- analysis selects up to three datasets from that library;
- cleaning selects one dataset independently from the same library;
- starting or closing an analysis resets task state, not imported datasets;
- only explicit dataset deletion removes a file from the library;
- the app should open with a sparse start screen, not a crowded dashboard;
- the main workspace should prioritize analysis results;
- the editable Python pane should not fight with the result view;
- analysis suggestions should be small and unobtrusive;
- the dataset overview should be lightweight and not block the main flow;
- loading states should be visible and polite;
- the left rail, top bar, and result panel should feel visually aligned;
- no heavy marketing copy or redundant descriptions;
- no visible model-switch UI for non-DevOps users;
- DevOps mode is machine-gated;
- the main style target is a mature western desktop product, closer to Codex /
  ChatGPT / Apple / Google than to a toy demo.

## 8. DevOps mode

The project has a hard-gated DevOps path.

Behavior:

- Dify remains the default provider;
- Gemini is only for debugging and DevOps;
- the client checks the machine identity before allowing DevOps mode;
- `config/devops_access.py` holds the machine gate logic;
- the UI should not expose Gemini as a normal end-user model option.

The current policy is that DevOps features must not leak into ordinary company
usage. That includes labels, toggles, and fallback language.

## 9. Packaging and runtime files

Windows packaging uses PyInstaller with `main.spec`.

Runtime file locations:

- source mode: `.env`, `logs/app.log`, `logs/faulthandler.log`;
- frozen mode: config and logs are redirected into the user profile
  directories via `config/runtime_paths.py`.

Build expectations:

- `requirements.txt` must include runtime libraries plus the tools needed by the
  current build flow;
- PyInstaller hidden imports must include `duckdb`, `pyarrow`, `psutil`, and
  the local contract/data-access modules;
- the frozen binary must support `--run-script` for worker execution.

## 10. Test strategy

Current tests cover:

- Dify client behavior;
- cancellation;
- intent/workflow planning;
- multi-dataset workflow;
- analysis result compatibility;
- settings validation;
- UI behavior;
- worker logging;
- release smoke tests for frozen builds.

The most important test philosophy is:

- validate contracts, not just happy paths;
- cover both sample execution and full execution;
- cover duplicate file names;
- cover long query transport;
- cover clarification behavior;
- cover repair behavior;
- cover packaging smoke for frozen worker mode.

## 11. Things not to regress

When making changes, do not accidentally undo these decisions:

- do not reintroduce a `system` field into the client request contract;
- do not remove explicit `analysis_plan` support;
- do not weaken dataset IDs into display names;
- do not let the generated code depend on row order between datasets;
- do not hide runtime or semantic errors behind generic success states;
- do not remove sample preflight;
- do not remove repair loop support;
- do not expose Gemini to regular users;
- do not make the default UI cluttered.

## 12. Suggested developer workflow

When extending the app:

1. update the local contract first;
2. update the Dify workflow setup document if the request/response shape
   changes;
3. update tests before polishing UI;
4. verify packaged worker behavior when touching execution or dependencies;
5. check multi-dataset and large-file behavior separately from single-file
   happy paths;
6. keep the results panel as the primary surface.
