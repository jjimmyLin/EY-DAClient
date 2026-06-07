# EY-DAClient

Desktop data-analysis assistant built with PySide6. The app loads spreadsheet
files, asks an LLM to understand and validate the user's analysis intent,
generates Python analysis code, and runs that code in an isolated worker
process.

## Features

- Spreadsheet preprocessing with sheet metadata and sample values.
- Intent validation before code generation, including clarification prompts when
  the requested analysis is not supported by the uploaded data.
- Multi-provider LLM configuration for Gemini, DeepSeek, and Dify.
- Worker-mode execution for PyInstaller builds so generated code can run without
  opening another GUI instance.
- File-backed app and crash logging for packaged Windows builds.

## Setup

Use Python 3.12.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with the provider and API key you want to use. The default provider
is Gemini.

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
```

Supported `LLM_PROVIDER` values are `gemini`, `deepseek`, and `dify`.

## Run

```bash
python app/main.py
```

The app also supports worker mode, which is used by packaged builds:

```bash
python app/main.py --run-script path/to/script.py
```

## Test

```bash
python -m compileall -q app config core dify llm services ui workers tests
pytest -q
```

If you use the local virtual environment in this repo:

```bash
./.venv/bin/pytest -q
```

## Build Windows Package

The GitHub Actions workflow builds a Windows onedir package with PyInstaller:

```powershell
$env:PYINSTALLER_CONSOLE = "0"
python -m PyInstaller main.spec --clean --noconfirm
```

The expected executable is:

```text
dist/EY-DAClient/EY-DAClient.exe
```

The workflow includes a smoke test for `EY-DAClient.exe --run-script` to verify
that worker failures return a non-zero exit code and persist crash logs.

## Runtime Files

In source mode, runtime files are written under the project root:

- `.env`
- `logs/app.log`
- `logs/faulthandler.log`

In frozen Windows builds, writable runtime files are kept outside the packaged
app directory:

- Config: `%APPDATA%\EY-DAClient\.env`
- Logs: `%LOCALAPPDATA%\EY-DAClient\logs\app.log`
- Crash log: `%LOCALAPPDATA%\EY-DAClient\logs\faulthandler.log`

## Repository Notes

- `.env`, build output, logs, and generated output are intentionally ignored.
- `requirements.txt` contains both runtime dependencies and developer tools used
  by the current workflow.
