# Contributing to otb-legacy

Thanks for your interest in contributing! Please read this before opening a PR or issue.

## Reporting Issues

Found a bug or have a suggestion? Please open an issue in the [Issues tab](../../issues) and include:

- What you expected to happen
- What actually happened
- Steps to reproduce
- Your Python version and OS
- Any relevant log output from the `logs/` folder

## Getting Started

1. Fork the repo and clone it locally
2. Install dependencies: `pip install -r requirements.txt`
3. Run `python otb-legacy-source/tradingbot.py` once then open  `config.ini` and fill in your credentials
4. Rerun and it will start to trade
5. Edit changes in your fork
6. Request a PR and explain what you changed/added

## Code Style

We use [ruff](https://docs.astral.sh/ruff/) for linting and formatting. Please run the following If your code editor isn't using ruff before submitting the PR:

```bash
pip install ruff
ruff check . --fix
ruff format .
```

## Project Conventions

### File & Module Layout

- All source files live in `otb-legacy-source/`
- Configuration is handled entirely through `config.ini` (auto-generated from defaults in `settings.py`)
- Persistent state files (`.blocklist`, `.cooldowns`, `.tradequeue`, etc.) are written to the working directory and are gitignored don't commit them

### Logging

Use the `log()` function from `log.py` for all output: don't use `print()` directly (except for debugging). Pass a color from `mycolors.py` as the second argument where appropriate:

```python
from log import log
import mycolors

log("Something went wrong.", mycolors.FAIL)
log("Trade sent successfully.", mycolors.OKGREEN)
```

### Settings

All configurable values should be read from `settings.py`. Don't hardcode values that belong in `config.ini`. If you add a new setting, add a sensible default to the `contents` string in `settings.py` with a comment explaining what it does.

### Error Handling

- Wrap long-running loops in `try/except Exception` and log the exception rather than crashing
- Use `logging.exception(...)` alongside `log(...)` so errors are captured in the log file
- Avoid bare `except:` always catch `Exception` at minimum

### Threading

New background tasks should be run as daemon threads so they don't block shutdown:

```python
import threading

my_thread = threading.Thread(target=my_function)
my_thread.daemon = True
my_thread.start()
```

## Submitting a PR
- Describe what you changed and why in the PR description
- Link any related issues (e.g. `Closes #42`)
