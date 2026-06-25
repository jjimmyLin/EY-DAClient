# EY-DAClient User Guide

EY-DAClient is a desktop data-analysis assistant for spreadsheet work.
It is designed for importing one or more datasets, asking a question in
natural language, reviewing generated Python, and then running the analysis
locally.

## 1. What this app is for

Use this app when you want to:

- inspect a spreadsheet quickly;
- ask a data-analysis question in plain language;
- combine multiple spreadsheets or sheets;
- review the generated Python before execution;
- run the final analysis locally on your machine;
- see structured results such as summary text, metrics, tables, charts, and
  insights.

## 2. What happens when you use it

The normal flow is:

1. Start the app.
2. Add or drag one or more spreadsheet files into the data portal.
3. Wait for the first dataset to become ready.
4. Choose `Analyze` or `Clean` when the operation cards unlock.
5. After entering a feature, use the title-bar `Mode` menu to switch between
   Data Analysis and Data Cleaning.
6. For analysis, select up to three datasets from the library.
7. Type an analysis request or choose a suggestion.
8. Click `Analyse`.
9. Review the generated Python code if needed.
10. Click `Apply` to run the code locally.
11. Read the final result in the main result panel.

The app may also show:

- a dataset overview popover;
- suggestions for follow-up analysis;
- a code editor for the generated Python;
- loading indicators while Dify is responding;
- a clarification choice dialog when the analysis request is ambiguous.

## 3. Main screen behavior

The app is intentionally results-first.

You should expect:

- a sparse start screen before a task begins;
- the left side to manage datasets and navigation;
- the center to focus on analysis output;
- the code editor to appear when analysis code is ready;
- the result area to show the most important output first.

## 4. Dataset import

You can import multiple datasets. Imported datasets belong to the application
workspace, not to one analysis task.

Important notes:

- the same Dataset Library is available to analysis and data cleaning;
- the Dataset Library button appears in the title bar only after entering a
  feature;
- dataset rows are selected by highlighting the whole row rather than using
  checkboxes;
- Data Analysis allows up to three highlighted datasets;
- Data Cleaning allows exactly one highlighted target and does not repeat the
  dataset selector inside the cleaning page;
- starting a new analysis does not remove imported datasets;
- analysis checkboxes define an analysis scope of up to three datasets;
- data cleaning chooses one target independently from the same library;
- a dataset is removed only when the user explicitly deletes it;
- same-name files are treated as separate datasets internally;
- each imported file gets its own dataset identity;
- the app will generate a dataset overview for each file;
- large files are cached locally so they can be reused efficiently;
- the app can analyze data from more than one file in a single task.

If a file is very large, the app may spend more time profiling it before the
analysis prompt is sent.

## 5. Overview

The overview is a quick summary of a dataset.

It is meant to help you answer questions like:

- what kind of dataset is this;
- how many rows and columns does it have;
- what is this data about;
- what kinds of next questions make sense.

The overview is lightweight and does not replace the main analysis result.

## 6. Suggestions

Suggestions are short follow-up analysis ideas.

They are intended to help when you do not know what to ask next.

Typical behavior:

- suggestions appear after the dataset overview is ready;
- suggestions should not appear if the overview failed;
- suggestions can be clicked to fill or guide the analysis prompt;
- the app keeps the suggestions visually small so they do not dominate the
  screen.

## 7. Analysis and code review

The app does not hide the code from you.

After analysis generation:

- the code is shown in an editable Python pane;
- you can adjust the code before execution;
- `Reset` restores the generated code;
- `Apply` runs the approved code locally.

The code review stage exists because the input question may be complex, and the
generated code may need minor adjustment before execution.

## 8. Results

The result panel is the main output area.

It can show:

- an executive summary;
- key metrics;
- tables;
- charts;
- insight cards;
- execution details if needed.

The result view is designed to be dense, readable, and suitable for repeated
analysis tasks.

## 9. Multi-file analysis

The app supports combining several datasets in one task.

Examples:

- compare values between dataset A and dataset B;
- join files on a shared business key;
- calculate formulas that use columns from A, B, and C together;
- analyze one dataset and use another dataset as reference or filter source.

When asking a multi-file question, be as specific as possible about:

- which datasets are involved;
- which columns are relevant;
- how the datasets should be matched;
- what output you expect.

## 10. Large files

Large workbooks are supported, but the app uses caching and sampling to stay
responsive.

You may notice:

- more time spent during import;
- a short preflight phase before full execution;
- slower analysis when the task is genuinely heavy;
- better reliability because the app does not rely on loading everything at
  once.

## 11. Dify and DevOps mode

By default, the app uses Dify.

DevOps mode exists only for approved local debugging.

What you should know:

- Dify is the normal production path;
- DevOps mode is machine-restricted;
- the UI should not expose debugging models to ordinary users;
- if your machine is not authorized, DevOps mode will be unavailable.

## 12. Common outcomes

You may see these types of outcomes:

- `Dataset overview is ready`
- `Code is ready for preflight`
- `Code passed sample preflight`
- `Full analysis completed`
- a clarification dialog
- a repair attempt after an execution error

This is normal. The app is built to keep going instead of failing silently.

## 13. Troubleshooting

If something looks wrong:

1. Check the log panel.
2. Re-import the dataset if the file changed.
3. Use a more explicit query if the analysis is ambiguous.
4. Click `Reset` if you edited the generated Python and want to return to the
   generated version.
5. If a task fails, inspect whether the error came from Dify, from local code
   execution, or from an ambiguous multi-file request.

Common causes of failure include:

- missing API settings;
- an incorrect Dify workflow;
- a query that is too vague for multi-file alignment;
- an unsupported workbook format;
- a runtime error in the generated Python code.

## 14. Best usage habits

To get the best results:

- keep questions specific;
- mention the datasets you want to combine;
- state the desired metric or transformation clearly;
- review the generated code before applying it;
- use the suggestions only as a starting point, not as a final answer.
