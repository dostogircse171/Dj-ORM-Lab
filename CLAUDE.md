# CLAUDE.md

This file tells Claude Code how this project is structured and how to work on it effectively.

## Project overview

Django ORM Playground is a self-contained Django 5.2 web app that lets users write and run Django ORM queries against a pre-seeded SQLite database, and see results in a table or JSON view. It is intended as an educational tool and open-source reference project.

## Stack

- **Backend:** Django 5.2 (LTS), Python 3.10+, SQLite
- **Frontend:** Vanilla JS, CodeMirror 5 (CDN), no build step
- **Execution:** sandboxed `exec()` inside `playground/views.py`

## Repository layout

```
config/          Django project settings, URLs, WSGI/ASGI
playground/
  models.py      All 7 domain models (Category, Product, Customer, Order, OrderItem, Review, Tag)
  views.py       index view + execute endpoint + SAFE_GLOBALS sandbox
  urls.py        Two routes: / and /execute/
  management/
    commands/
      seed.py    `python manage.py seed` — clears and re-seeds all dummy data
  migrations/    Standard Django migrations
templates/
  playground/
    index.html   Single-page UI: CodeMirror editor, schema sidebar, output panel
```

## Common commands

```bash
# First-time setup
pip install django
python manage.py migrate
python manage.py seed

# Run dev server
python manage.py runserver

# Re-seed data (safe to run repeatedly — clears first)
python manage.py seed

# Run Django system checks
python manage.py check
```

## Key design decisions

### SQL query display and timing
Every execute request captures `connection.queries` (Django's built-in query log, enabled via `DEBUG=True`). The SQL tab shows each generated SQL statement with its individual execution time in milliseconds. The tab badge shows the total query count; it turns amber when ≥3 queries run (potential inefficiency signal).

### N+1 detector (`_detect_n1` in `views.py`)
After each execution, the captured SQL list is normalised: all literal values and integers are replaced with `?` to produce a "shape". If any shape appears ≥3 times the query is flagged as a likely N+1. The warning includes the repeated query shape, the count, and a fix hint pointing to `select_related()` or `prefetch_related()`. The Explain tab badge turns red when N+1 is detected.

### Plain-English query explanation (`_explain_code` in `views.py`)
An AST visitor (`ast.NodeVisitor`) walks the parsed user code to collect method chain calls (`.filter`, `.annotate`, `.select_related`, etc.) and imports from `django.db.models`. Each detected operation maps to a one-sentence description. The Explain tab renders these bullets after each run.

### Compare mode
The frontend has a **Compare** toggle that reveals a second CodeMirror pane (pane B). When compare mode is active the run button posts both `code` and `code_b` plus `mode: "compare"` to `/execute/`. The view runs both through the same sandbox in sequence and returns a `{mode: "compare", a: {...}, b: {...}}` response. The frontend renders A and B results side by side with a diff summary: which is faster, which uses fewer SQL queries, whether each triggered N+1.

### Keyboard shortcuts modal
Triggered by pressing `?` anywhere in the app (except inside the editor) or clicking the `⌨` button in the header. Shortcut: `Esc` to close. The modal is pure CSS/JS (no dependencies). Registered shortcuts: `Ctrl+Enter` run, `Ctrl+L` clear, `Alt+1–4` switch output tabs, `Ctrl+Shift+C` toggle compare mode, `?` open shortcuts.

### Sandboxed execution (`playground/views.py`)
- User code runs inside `exec()` in a **daemon thread** via `_run_in_thread()`. The main request thread joins with a `QUERY_TIMEOUT` second deadline; if the worker is still alive after that the thread is abandoned and a timeout error is returned. This is the only thread-safe way to impose a timeout without `signal.alarm` (which only works on the main thread).
- `__builtins__` is replaced with an explicit allowlist of safe builtins.
- A custom `safe_import` replaces `__import__` and only allows imports from `django.db.models`, `django.db.models.functions`, `django.db.models.aggregates`, and `django.db` (for `connection`).
- A string blocklist (`import os`, `import sys`, `open(`, `eval(`, etc.) provides a fast first-pass rejection before `exec` is called.
- `print()` is replaced per-request with a version that writes to a `StringIO` buffer. The buffer is returned alongside the result and displayed in a yellow `stdout` banner above the output.
- `connection` (Django's DB connection) is pre-injected and also importable via `from django.db import connection`. It is safe because all writes roll back.

### Write protection via always-rollback transaction
Every query runs inside `transaction.atomic()`. After the user's code executes and the result is fully serialised (querysets are lazy so they must be evaluated *inside* the transaction), a sentinel exception `_AlwaysRollback` is raised unconditionally. Django rolls back the savepoint, meaning `.delete()`, `.update()`, `.create()`, `.save()`, and `.bulk_create()` all appear to work (the user sees the affected row count or created object) but nothing is ever written to disk. The seed data is always preserved across requests.

### Query history
Stored in `localStorage` under the key `djorm_history` (max 50 entries). Each entry records: the code, status (`ok`/`error`/`timeout`), row count, and timestamp. The History tab in the left sidebar renders entries; clicking one loads it into the editor. Deduplication: re-running the same code moves it to the top rather than creating a duplicate.

### Database configuration (`config/settings.py`)
Reads from environment variables with safe defaults. Supports:
- SQLite (default, no env vars needed)
- `DATABASE_URL=postgres://user:pass@host:port/db` (single URL)
- Individual `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` vars

### Result surfacing
The execute view resolves the output in this priority order:
1. A local variable named `result`
2. The last local variable assigned in the user's code
3. `eval()` of the entire code as a single expression (fallback for one-liners)

### Multi-line ORM chains
Python requires chained method calls spanning multiple lines to be inside parentheses. All example queries use the `result = (...)` pattern. This is documented in the editor's default placeholder text.

### Example queries
Defined as a Python list of dicts in `EXAMPLE_QUERIES` at the top of `views.py`. The code strings are passed to the template as a `json.dumps` array (`examples_json`) and read by JS as `EXAMPLE_CODES[index]`. Do **not** use Django's `|escapejs` filter for code strings — it double-escapes backslashes and breaks newlines in the editor.

### Schema panel
Built dynamically at request time by `_build_schema()` using `model._meta.get_fields()`. No hardcoding required when models change.

## Adding a new example query

Edit `EXAMPLE_QUERIES` in `playground/views.py`. Multi-line queries must use the `result = (\n    ...\n)` pattern so Python accepts them.

## Adding a new model

1. Define it in `playground/models.py`.
2. Add it to `SAFE_GLOBALS` in `playground/views.py` so it is available in the sandbox.
3. Run `python manage.py makemigrations && python manage.py migrate`.
4. Add seed data for it in `playground/management/commands/seed.py`.

## What to avoid

- Do not use `|escapejs` for multi-line code strings in templates — use `json.dumps` + `|safe`.
- Do not store secrets in `config/settings.py` — the `SECRET_KEY` is insecure by design for local dev.
- Do not add `DEBUG = False` or `ALLOWED_HOSTS` changes without also setting up proper static file serving.
- Do not remove the `SAFE_GLOBALS` restrictions without understanding the security implications of running arbitrary user code.
