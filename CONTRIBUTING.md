# Contributing to English Coach

Thanks for your interest in contributing! This document covers setting up a
development environment and the process for submitting changes.

## Prerequisites

- Python 3.12 or newer
- Git

## Development setup

```sh
python3.12 -m venv .venv
source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\activate           # Windows PowerShell

pip install -e ".[dev]"
```

## Running tests

```sh
pytest
```

On Windows, if you see a `PermissionError` on the Temp directory (caused by an
antivirus or locked temp folder), use a local base temp directory:

```sh
pytest --basetemp=.pytest_tmp
```

On Windows the test suite runs a live SQLite database, so each test uses a
temporary directory automatically.

## Submitting changes

1. Fork the repository and create a feature branch.
2. Write or update tests for your change.
3. Ensure all tests pass locally before pushing.
4. Open a pull request using the [PR template](.github/pull_request_template.md).

## Scope

This project values simplicity and correctness. Before starting work on a
feature, consider opening an issue first to discuss the design.
