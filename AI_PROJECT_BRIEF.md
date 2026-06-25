# EY-DAClient AI Project Brief

This file is written for an AI model that needs to continue development on the
project without re-reading the full conversation history.

Current Dify baseline (validated 2026-06-25): the workflow exported as
`TRSZ - 数据分析助手 (2).yml` successfully interoperates with the desktop
application and produces executable analysis results. Preserve its current
input/output contract when changing the client.

## 1. Project identity

EY-DAClient is a Windows desktop spreadsheet-analysis assistant built with
PySide6.

Its core invariant is:

> Dify generates the analysis Python code, and the local client validates and
> executes it.

Do not replace that core loop with a direct local-only analytics engine unless
the user explicitly changes the product goal.

## 2. Core goals

The product must support:

1. multi-file joint analysis;
2. large-file handling;
3. local execution of Dify-generated Python with better reliability;
4. editable generated code before Apply;
5. a results-first desktop UI;
6. explicit Dify workflow control;
7. optional machine-gated DevOps mode for debugging only;
8. future extensibility without breaking the existing workflow.
9. an application-level Dataset Library shared by analysis and cleaning.

## 3. Current architecture summary

Important modules:

- `app/main.py` starts the app, enables logging, and supports worker mode.
- `config/settings.py` owns runtime configuration and provider validation.
- `config/devops_access.py` gates DevOps mode to a specific machine.
- `core/preprocessor.py` imports spreadsheets, profiles them, and caches them.
- `core/data_access.py` exposes the local dataset runtime API.
- `core/multi_file_resolver.py` suggests candidate joins between datasets.
- `core/analysis_contract.py` validates the Dify plan and generated code.
- `core/analysis_result.py` defines the structured result protocol.
- `core/executor.py` runs generated Python in a child process.
- `core/prompt_builder.py` constructs Dify prompts and compact context payloads.
- `dify/client.py` calls the Dify workflow API.
- `dify/workflow.py` coordinates generation, preflight, execution, and repair.
- `ui/main_window.py` is the main desktop UI.
- `ui/result_panel.py` renders result cards, charts, tables, and summaries.
- `ui/decision_panel.py` renders option cards for clarifications.

## 4. Request contract

The client-side Dify workflow request must keep exactly these top-level inputs:

- `task_type`
- `context`
- `query`

Do not add `system` back into the client request shape.

The client may transport extra data inside the JSON `context` payload, but the
top-level input contract must remain stable.

## 5. Task types

The workflow currently uses at least these task types:

- `overview`
- `analysis`
- `repair`

The analysis path is the most important one.

## 6. Local data runtime contract

Generated code should be able to use:

- `data.get(dataset_id, sheet_id, columns=[...])`
- `dfs["dataset_id"]["sheet_id"]`
- `data.merge(...)`
- `data.sql(..., sources={...})`

Rules:

- prefer `data.get()` for ordinary loads;
- prefer `data.sql()` for large joins and aggregations;
- do not rely on dataset row order across files;
- do not use `read_excel`, `read_csv`, or filesystem access inside generated
  code;
- use dataset IDs and sheet IDs, not display names;
- if multiple datasets are used, joins/alignment must be explicit.

## 7. Result protocol

Generated code must use the result collector API:

- `result.set_summary(text)`
- `result.add_metric(...)`
- `result.add_table(...)`
- `result.add_chart(...)`
- `result.add_insight(...)`
- `result.add_warning(...)`
- `result.mark_requirement(requirement_id)`

The result object is the contract between the generated Python and the UI.

## 8. Analysis plan protocol

For non-trivial analysis, Dify should return or help construct an
`analysis_plan`.

Each requirement should have:

- `id`
- `objective`
- `sources`
- `joins`
- `grain`
- `formula`
- `output_type`

The planner must also support clarification when the request is ambiguous.

## 9. Multi-file analysis

This project now explicitly supports multi-file joint analysis.

The AI must assume the user can ask for tasks like:

- compare dataset A against dataset B;
- compute formulas using A, B, and C simultaneously;
- join different workbooks on a business key;
- analyze one dataset while enriching from another;
- ask for a summary over several sheets/files at once.

The generated code must:

- identify the correct source dataset IDs;
- resolve joins explicitly;
- mark requirement completion for every planned requirement;
- publish data quality or alignment warnings when needed;
- avoid silent assumptions about row alignment.

## 10. Large-file support

The local client already caches sheets as Parquet and can stream large XLSX
workbooks.

The AI should optimize for:

- column projection;
- aggregation before visualization;
- DuckDB-backed SQL for large joins;
- compact result tables;
- explicit handling of nulls and division by zero;
- preflight sample execution followed by full execution.

Do not generate code that assumes all data fits comfortably into a single
Pandas DataFrame unless the request is obviously small.

## 11. Error handling philosophy

The project does not want generic failure messages.

If analysis fails:

- classify whether it is a Dify/API error, a validation error, a runtime error,
  or a semantic mismatch;
- preserve the original analysis intent;
- let the repair branch fix the issue instead of starting over blindly;
- keep error text clear enough for the UI to present a stable summary.

## 12. UI philosophy

The UI should be:

- results-first;
- dense but readable;
- modern and mature;
- consistent with western desktop products such as Codex, ChatGPT, Apple, and
  Google;
- not overloaded with decorative explanations;
- not crowded on the start screen;
- not full of model-switch labels or debugging terms in ordinary mode.

Useful UI behaviors:

- data-first animated start screen with click and drag-and-drop import;
- analysis and cleaning choices unlock only after a dataset is ready;
- global floating Dataset Library available from every feature;
- analysis workspace only after a task starts;
- code editor shown when code is ready;
- `Reset` should restore generated code;
- `Apply` should be the final confirmation to execute;
- suggestions should be small and not block the main result;
- overview should be lightweight;
- loading states should be visible and smooth.

## 13. DevOps mode

DevOps mode exists only for machine-approved debugging.

Requirements:

- Dify remains the default provider;
- Gemini should not be shown to normal users;
- the machine gate must remain in place;
- do not weaken the access control by replacing it with a simple UI toggle;
- if the user is not on the approved machine, DevOps mode should be hidden or
  denied.

## 14. Dify workflow expectations

The Dify workflow should support:

- overview branch;
- analysis planner branch;
- clarification branch;
- Python generation branch;
- repair branch;
- explicit output of both generated code and the structured analysis plan.

The workflow should not rely on text matching inside `system`.

The current design assumes:

1. Dify receives a compact context with dataset metadata and relationship
   evidence.
2. The planner turns the request into explicit requirements.
3. The generator writes code from the plan.
4. The local client validates and executes the code.
5. Repair uses the exact failure context.

## 15. Things the AI should not accidentally break

Be careful not to:

- remove the analysis plan contract;
- remove requirement marking;
- reduce multi-file support back to single-file assumptions;
- remove local caching or Parquet caching;
- remove the repair loop;
- add hidden row-order dependencies;
- expose debugging models to normal users;
- make the UI noisier instead of clearer.
- treat imported datasets as children of an individual analysis task;
- clear the Dataset Library when starting a new analysis;
- make cleaning depend on the analysis checkbox selection.

## 16. Good next-step instincts

When asked to modify this project, the AI should usually:

1. inspect the current local contract first;
2. inspect the Dify workflow expectations second;
3. update tests before large UI refactors;
4. keep the result panel as the main surface;
5. keep the code editor and result viewer coordinated;
6. avoid inventing new top-level interaction concepts unless the user
   specifically asks for them.
