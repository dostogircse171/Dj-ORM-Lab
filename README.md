# Django ORM Playground

An interactive, browser-based playground for learning and experimenting with the Django ORM. Write queries against a realistic pre-seeded e-commerce database and see results instantly in a table or JSON view.

> **The only tool that lets you run Django ORM queries in a browser — against real relational data — with zero setup.**

![Django](https://img.shields.io/badge/Django-5.2%20LTS-092E20?logo=django&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-blue)

---

## Screenshot

```
┌─────────────────────────────────────────────────────────────────────┐
│  DjangoORM Playground  [SQLite]              Ctrl+Enter to run      │
├──────────┬──────────────────────────────────┬───────────────────────┤
│ Schema   │  Examples: [All customers] ...   │  Output   ● 10 rows  │
│          ├──────────────────────────────────┤                       │
│ Category │  query.py          [Clear] [Run] │  Table  JSON          │
│ Product  │                                  │                       │
│ Customer │  Customer.objects.all()          │  name      city       │
│ Order    │                                  │  Alice     New York   │
│ OrderItem│                                  │  Bob       LA         │
│ Review   │                                  │  ...                  │
│ Tag      │                                  │                       │
└──────────┴──────────────────────────────────┴───────────────────────┘
```

## Features

- **Live ORM execution** — write any Django ORM query and run it with `Ctrl+Enter`
- **17 built-in examples** — filtering, annotation, aggregation, `select_related`, `prefetch_related`, M2M, `F()`, `Q()`, `Window`, `Subquery`, raw SQL, N+1 demo pair, and more
- **SQL tab with timing** — every run shows the exact SQL sent to the database, per-query execution time, and a total query count badge
- **N+1 detector** — automatically flags when the same query shape runs ≥3 times (classic N+1 pattern), with a fix hint pointing to `select_related()` or `prefetch_related()`
- **Explain tab** — plain-English bullets describing what your query does: which ORM operations are used and what each one means
- **Compare mode** — run two queries side by side; see which is faster, which uses fewer SQL queries, and whether either triggers N+1
- **Execution timeout** — queries are killed after 5 seconds; no infinite loops can hang the server
- **print() captured** — `print()` output appears in a yellow banner above the result, not silently lost
- **Query history** — last 50 queries saved in `localStorage`; click any entry to restore it
- **Schema sidebar** — expand any model to see its fields and types at a glance
- **Table & JSON views** — toggle between a formatted table and syntax-highlighted JSON output
- **Write protection** — `.delete()`, `.update()`, `.create()` always roll back; seed data is never lost
- **Raw SQL support** — `from django.db import connection` and `Model.objects.raw()` both work
- **Keyboard shortcuts** — press `?` to open the shortcuts cheatsheet; `Alt+1–4` to switch tabs; `Ctrl+Shift+C` to toggle compare mode
- **Resizable output panel** — drag the divider to fit your workflow
- **Postgres-ready** — set `DATABASE_URL` or `DB_*` env vars to switch from SQLite to PostgreSQL with no code changes
- **Django 5.2 LTS** — covers all modern ORM features including `Window` functions, `JSONField`, async ORM, and `GeneratedField`

---

## Quickstart

### Requirements

- Python 3.10+
- pip

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/your-username/django-orm-playground.git
cd django-orm-playground

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install django

# 4. Run migrations
python manage.py migrate

# 5. Seed the database with dummy data
python manage.py seed

# 6. Start the dev server
python manage.py runserver
```

Open **http://127.0.0.1:8000** in your browser.

---

## Database schema

The playground comes with a pre-seeded e-commerce style database:

```
Category ──< Product >── Tag  (M2M)
                │
             OrderItem
                │
Order ──────────┘
  │
Customer ──< Review >── Product
```

| Model | Description | Seeded rows |
|---|---|---|
| `Category` | Product categories | 5 |
| `Product` | Items for sale, linked to a category | 18 |
| `Customer` | Shoppers with name, email, city | 10 |
| `Order` | Purchase orders with status | 12 |
| `OrderItem` | Line items linking orders to products | 31 |
| `Review` | Star ratings left by customers on products | 16 |
| `Tag` | Labels with M2M relation to products | 5 |

### Re-seeding

The seed command is idempotent — it clears all data and re-inserts it from scratch:

```bash
python manage.py seed
```

---

## Writing queries

All model classes are available directly by name — no imports needed for basic queries:

```python
# Simple filter
Product.objects.filter(price__lt=50).values('name', 'price')

# Traverse relations
Order.objects.select_related('customer').values('id', 'customer__name', 'status')

# Annotate + aggregate
from django.db.models import Avg, Count
result = (
    Product.objects
    .annotate(avg_rating=Avg('reviews__rating'), review_count=Count('reviews'))
    .filter(review_count__gt=0)
    .values('name', 'avg_rating', 'review_count')
    .order_by('-avg_rating')
)
```

### Available models

`Category`, `Product`, `Customer`, `Order`, `OrderItem`, `Review`, `Tag`

### Available imports

Only imports from `django.db.models` and its sub-modules are allowed:

```python
from django.db.models import Count, Sum, Avg, Max, Min, F, Q
from django.db.models.functions import Lower, Upper, TruncMonth
```

### Multi-line chains

Python requires chained method calls that span multiple lines to be wrapped in parentheses:

```python
# This will fail (SyntaxError: unexpected indent)
Product.objects
    .filter(is_active=True)
    .values('name')

# This works
result = (
    Product.objects
    .filter(is_active=True)
    .values('name')
)
```

### Surfacing output

The execute endpoint resolves your result in this order:

1. A variable named `result` — **recommended for multi-statement queries**
2. The last variable assigned in your code
3. A single-expression query (one-liner fallback)

---

## Sandbox security

The execution environment restricts what user code can do:

| Allowed | Blocked |
|---|---|
| All Django ORM operations | `import os`, `import sys`, `import subprocess` |
| `from django.db.models import ...` | `open()`, `eval()`, `exec()`, `compile()` |
| `from django.db import connection` (raw SQL) | `globals()`, `locals()`, `breakpoint()` |
| Safe Python builtins (`len`, `list`, `sorted`, etc.) | `__class__`, `__bases__`, `__subclasses__` |
| `print()` — output shown in browser | File system and network access |

### Write protection

Every query runs inside a database transaction that is **always rolled back** after execution. This means:

- `.delete()`, `.update()`, `.create()`, `.save()` all execute and return real results (row counts, created objects)
- **Nothing is ever committed** — the seed data survives every request
- No need to re-seed after accidental destructive queries

```python
# This runs, returns (10, {...}), but all 10 customers still exist afterward
Customer.objects.all().delete()

# This runs, returns 18, but all prices are unchanged afterward
Product.objects.all().update(price=0)
```

> **Note:** This sandbox is designed for local development and educational use. It is not hardened for running untrusted code from unknown users in a production environment.

---

## Project structure

```
django-orm-playground/
├── config/
│   ├── settings.py          Django settings (SQLite, DEBUG=True)
│   ├── urls.py              Root URL conf
│   └── wsgi.py
├── playground/
│   ├── models.py            All 7 domain models
│   ├── views.py             index view, /execute/ endpoint, sandbox
│   ├── urls.py              App-level URL conf
│   └── management/
│       └── commands/
│           └── seed.py      `manage.py seed` command
├── templates/
│   └── playground/
│       └── index.html       Single-page UI (CodeMirror + Vanilla JS)
├── manage.py
├── CLAUDE.md                Guide for AI assistants working on this repo
└── README.md
```

---

## Switching to PostgreSQL

The app ships with SQLite for zero-config local development. When you're ready to use PostgreSQL:

```bash
pip install psycopg2-binary

# Option A — single URL
export DATABASE_URL=postgres://user:password@localhost:5432/djorm

# Option B — individual vars
export DB_ENGINE=django.db.backends.postgresql
export DB_NAME=djorm
export DB_USER=postgres
export DB_PASSWORD=secret
export DB_HOST=localhost
export DB_PORT=5432

python manage.py migrate
python manage.py seed
python manage.py runserver
```

Copy `.env.example` to `.env` and fill in your values. No code changes required.

---

## Why this exists — vs. the alternatives

Every Django developer has hit the same wall: you want to quickly try an ORM query, but your options are all friction.

| Tool | ORM support | Browser UI | Pre-seeded data | Schema browser | Result table | Write-safe | SQL display | N+1 detector | Compare mode | Zero setup |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Django ORM Playground** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `manage.py shell` | ✅ | ❌ terminal | ❌ bring your own | ❌ | ❌ raw repr | ❌ | ❌ | ❌ | ❌ | ✅ |
| `shell_plus` (django-extensions) | ✅ | ❌ terminal | ❌ bring your own | ❌ | ❌ raw repr | ❌ | ❌ | ❌ | ❌ | ❌ install needed |
| Jupyter + Django | ✅ | ✅ notebook | ❌ bring your own | ❌ | partial | ❌ | ❌ | ❌ | ❌ | ❌ complex setup |
| DB Fiddle / SQLFiddle | ❌ raw SQL only | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| ChatGPT / AI assistants | ❌ explains only | ✅ | ❌ simulated | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |

### What makes this different

**1. ORM-first, not SQL-first.**
DB Fiddle is great for SQL but teaches you nothing about Django ORM syntax — `annotate`, `select_related`, `F()`, `Q()`, `Subquery`. This playground is built entirely around the ORM layer.

**2. Real relational data, pre-wired.**
You get 7 related models (Category → Product ← Tag, Customer → Order → OrderItem → Product, Review) with 90+ seeded rows. Joins, aggregations, and reverse lookups all work out of the box. No "INSERT INTO..." before you can test anything.

**3. Browser UI that shows structured output.**
`manage.py shell` prints raw Python repr — `<QuerySet [<Product: Laptop Pro 15>, ...]>`. This playground renders results as a sortable table or syntax-highlighted JSON, with column headers derived from your `values()` keys.

**4. Write-safe by design.**
Every query — including `delete()`, `update()`, `create()` — runs inside a transaction that is always rolled back. You can't accidentally destroy your data. No other Django shell tool does this by default.

**5. Zero setup, self-contained.**
One `pip install django`, two management commands, and you're running. No Docker, no Postgres required to start (Postgres is supported when you're ready), no Jupyter kernel, no `.env` required.

**6. Built for teaching.**
The schema, the seed data, and the 17 example queries are all designed to demonstrate real-world ORM patterns: spanning from basic filtering up to `Window` functions, `Subquery`, and raw SQL — all in one place with visible output.

**7. SQL transparency.**
Every run exposes the SQL that Django actually sent to the database, with per-query timing. You can see how `annotate(Count(...))` becomes a GROUP BY, how `select_related` collapses into a JOIN, and how a naive loop triggers 12 round-trips instead of 1.

**8. N+1 detection built in.**
The playground automatically detects when the same SQL shape runs ≥3 times and flags it with a red N+1 badge — the most common Django performance mistake, made visible without any profiling setup.

**9. Compare any two queries.**
Toggle Compare mode to run two queries side by side: see which is faster, which generates fewer SQL queries, and whether either hits the N+1 pattern. Built to compare `select_related` vs lazy loading, or raw SQL vs ORM, with actual numbers.

---

## Contributing

Contributions are welcome! Here are some good areas to work on:

- **More example queries** — `TruncMonth` + `Count` for time-series, `Exists()`, `Case()`/`When()`
- **More models** — add a `Supplier` or `Coupon` model to extend the schema
- **Share queries** — generate a shareable URL that pre-fills the editor
- **Error line highlighting** — jump to the offending line in CodeMirror on `SyntaxError`
- **Export results** — download table output as CSV
- **Dark/light theme toggle**
- **Richer N+1 detection** — catch `prefetch_related` misuse, detect missing `only()`/`defer()` patterns
- **Explain improvements** — detect `Exists()`, `Case()`/`When()`, `TruncMonth`, and index-unfriendly filters

### Adding a new example query

Edit `EXAMPLE_QUERIES` in [playground/views.py](playground/views.py). Use the `result = (...)` pattern for any multi-line chain.

### Adding a new model

1. Define it in [playground/models.py](playground/models.py)
2. Add it to `_MODEL_GLOBALS` in [playground/views.py](playground/views.py)
3. Run `python manage.py makemigrations && python manage.py migrate`
4. Add seed rows in [playground/management/commands/seed.py](playground/management/commands/seed.py)

---

## License

MIT — see [LICENSE](LICENSE) for details.
