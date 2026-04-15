import ast
import io
import json
import queue
import re
import threading
import time
import traceback

from django.db import transaction, connection, reset_queries
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from playground import models as playground_models
from playground.models import (
    Category, Product, Customer, Order, OrderItem, Review, Tag,
)

QUERY_TIMEOUT = 5

# ── Example queries ────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    {
        "label": "All customers",
        "code": "Customer.objects.all()",
    },
    {
        "label": "Products under $50",
        "code": "Product.objects.filter(price__lt=50).values('name', 'price', 'stock')",
    },
    {
        "label": "Orders with customer name (select_related)",
        "code": (
            "result = (\n"
            "    Order.objects\n"
            "    .select_related('customer')\n"
            "    .values('id', 'customer__name', 'status', 'total_amount')\n"
            ")"
        ),
    },
    {
        "label": "Product count per category",
        "code": (
            "from django.db.models import Count\n"
            "result = (\n"
            "    Category.objects\n"
            "    .annotate(product_count=Count('products'))\n"
            "    .values('name', 'product_count')\n"
            ")"
        ),
    },
    {
        "label": "Average rating per product",
        "code": (
            "from django.db.models import Avg, Count\n"
            "result = (\n"
            "    Product.objects\n"
            "    .annotate(avg_rating=Avg('reviews__rating'), review_count=Count('reviews'))\n"
            "    .filter(review_count__gt=0)\n"
            "    .values('name', 'avg_rating', 'review_count')\n"
            "    .order_by('-avg_rating')\n"
            ")"
        ),
    },
    {
        "label": "Top spending customers",
        "code": (
            "from django.db.models import Sum\n"
            "result = (\n"
            "    Customer.objects\n"
            "    .annotate(total_spent=Sum('orders__total_amount'))\n"
            "    .filter(total_spent__isnull=False)\n"
            "    .values('name', 'city', 'total_spent')\n"
            "    .order_by('-total_spent')\n"
            ")"
        ),
    },
    {
        "label": "Products tagged 'bestseller'",
        "code": (
            "result = (\n"
            "    Product.objects\n"
            "    .filter(tags__name='bestseller')\n"
            "    .values('name', 'price', 'category__name')\n"
            ")"
        ),
    },
    {
        "label": "N+1 problem (BAD — try it!)",
        "code": (
            "# This triggers N+1: one query per order to fetch the customer.\n"
            "# Watch the SQL tab — you'll see 12+ queries instead of 1.\n"
            "orders = list(Order.objects.all())\n"
            "result = [{'order': o.id, 'customer': o.customer.name} for o in orders]"
        ),
    },
    {
        "label": "N+1 fixed (select_related)",
        "code": (
            "# Fixed: select_related fetches everything in ONE JOIN query.\n"
            "# Compare the SQL tab with the N+1 example above.\n"
            "orders = list(Order.objects.select_related('customer').all())\n"
            "result = [{'order': o.id, 'customer': o.customer.name} for o in orders]"
        ),
    },
    {
        "label": "Orders with items (prefetch_related)",
        "code": (
            "orders = Order.objects.prefetch_related('items__product', 'customer').all()[:5]\n"
            "result = []\n"
            "for order in orders:\n"
            "    result.append({\n"
            "        'order_id': order.id,\n"
            "        'customer': order.customer.name,\n"
            "        'status': order.status,\n"
            "        'items': [{\n"
            "            'product': item.product.name,\n"
            "            'qty': item.quantity,\n"
            "            'unit_price': str(item.unit_price),\n"
            "        } for item in order.items.all()]\n"
            "    })\n"
            "result"
        ),
    },
    {
        "label": "Delivered orders total revenue",
        "code": (
            "from django.db.models import Sum\n"
            "result = (\n"
            "    Order.objects\n"
            "    .filter(status='delivered')\n"
            "    .aggregate(revenue=Sum('total_amount'))\n"
            ")"
        ),
    },
    {
        "label": "Customers with no orders (exclude)",
        "code": (
            "result = (\n"
            "    Customer.objects\n"
            "    .exclude(orders__isnull=False)\n"
            "    .values('name', 'email', 'city')\n"
            ")"
        ),
    },
    {
        "label": "Raw SQL via connection.cursor()",
        "code": (
            "from django.db import connection\n"
            "with connection.cursor() as cursor:\n"
            "    cursor.execute(\n"
            "        'SELECT name, city, email FROM playground_customer ORDER BY name'\n"
            "    )\n"
            "    cols = [c.name for c in cursor.description]\n"
            "    result = [dict(zip(cols, row)) for row in cursor.fetchall()]"
        ),
    },
    {
        "label": "Window function — price rank",
        "code": (
            "from django.db.models import F, Window\n"
            "from django.db.models.functions import Rank\n"
            "result = (\n"
            "    Product.objects\n"
            "    .annotate(price_rank=Window(\n"
            "        expression=Rank(),\n"
            "        order_by=F('price').desc()\n"
            "    ))\n"
            "    .values('name', 'price', 'price_rank')\n"
            "    .order_by('price_rank')\n"
            ")"
        ),
    },
    {
        "label": "F() — discounted price",
        "code": (
            "from django.db.models import F, ExpressionWrapper, DecimalField\n"
            "result = (\n"
            "    Product.objects\n"
            "    .annotate(discounted=ExpressionWrapper(\n"
            "        F('price') * 0.9,\n"
            "        output_field=DecimalField()\n"
            "    ))\n"
            "    .values('name', 'price', 'discounted')\n"
            "    .order_by('price')[:6]\n"
            ")"
        ),
    },
    {
        "label": "Q() — OR filter",
        "code": (
            "from django.db.models import Q\n"
            "result = (\n"
            "    Product.objects\n"
            "    .filter(Q(price__lt=20) | Q(stock__gt=150))\n"
            "    .values('name', 'price', 'stock')\n"
            ")"
        ),
    },
    {
        "label": "Subquery — latest review rating",
        "code": (
            "from django.db.models import OuterRef, Subquery\n"
            "latest_rating = (\n"
            "    Review.objects\n"
            "    .filter(product=OuterRef('pk'))\n"
            "    .order_by('-created_at')\n"
            "    .values('rating')[:1]\n"
            ")\n"
            "result = (\n"
            "    Product.objects\n"
            "    .annotate(latest_rating=Subquery(latest_rating))\n"
            "    .filter(latest_rating__isnull=False)\n"
            "    .values('name', 'latest_rating')\n"
            ")"
        ),
    },
]

# ── Allowed imports ────────────────────────────────────────────────────────────

import django.db.models as _djmodels
import django.db.models.functions as _djfuncs
import django.db.models.aggregates as _djaggs
import django.db as _djdb

# Only expose the specific sub-modules users legitimately need.
# Do NOT expose the top-level `django` package — it has utils/dispatch/etc
# that can be used to reach os/subprocess.
_ALLOWED_MODULES = {
    "django.db.models":            _djmodels,
    "django.db.models.functions":  _djfuncs,
    "django.db.models.aggregates": _djaggs,
    "django.db":                   _djdb,
}

# Safe builtins: explicit allowlist — nothing that can reach the file system,
# introspect __subclasses__, or escape the sandbox.
# Removed: type(), vars(), dir(), getattr(), hasattr() — all can be used to
# walk the object graph and reach os/subprocess via __subclasses__ chains.
_SAFE_BUILTINS = {
    "len": len, "range": range, "list": list, "dict": dict,
    "str": str, "int": int, "float": float, "bool": bool,
    "tuple": tuple, "set": set, "enumerate": enumerate,
    "zip": zip, "map": map, "filter": filter,
    "sorted": sorted, "reversed": reversed,
    "min": min, "max": max, "sum": sum,
    "abs": abs, "round": round,
    "isinstance": isinstance, "repr": repr,
    "Exception": Exception, "ValueError": ValueError,
    "TypeError": TypeError, "KeyError": KeyError,
    "IndexError": IndexError, "AttributeError": AttributeError,
    "NotImplementedError": NotImplementedError,
    "StopIteration": StopIteration,
}

_MODEL_GLOBALS = {
    "Category": Category, "Product": Product, "Customer": Customer,
    "Order": Order, "OrderItem": OrderItem, "Review": Review, "Tag": Tag,
    "models": playground_models,
    "connection": connection,
}

# Tokens blocked before exec() is even called — fast first-pass rejection.
# Covers the most common escape patterns as plain text.
_BLOCKED_TOKENS = [
    # module imports — filesystem, network, shell, serialisation
    "import os", "import sys", "import subprocess", "import shutil",
    "import pathlib", "import glob", "import tempfile", "import socket",
    "import http", "import urllib", "import requests", "import ftplib",
    "import pickle", "import shelve", "import marshal", "import ctypes",
    "import cffi", "import mmap",
    # dangerous builtins
    "open(", "__import__", "exec(", "eval(", "compile(",
    "globals(", "locals(", "breakpoint(",
    # object-graph escape chains
    "__class__", "__bases__", "__subclasses__", "__mro__",
    "__builtins__", "__loader__", "__spec__", "__code__",
    "__globals__", "__closure__", "__wrapped__",
    # attribute access escape helpers
    "getattr(", "setattr(", "delattr(", "hasattr(",
    "vars(", "dir(", "type(",
    # off-limits tables via raw SQL
    "auth_user", "auth_group", "auth_permission",
    "django_session", "django_content_type", "django_migrations",
    "django_admin_log",
]


def _make_exec_globals(print_buffer: io.StringIO) -> dict:
    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        # Exact match — return the module directly
        if name in _ALLOWED_MODULES:
            return _ALLOWED_MODULES[name]
        # Prefix match: `import django` → return django.db.models (most specific allowed)
        # BUT only when there's no exact match above, so django.db stays django.db.
        for allowed in sorted(_ALLOWED_MODULES, key=len, reverse=True):
            if allowed.startswith(name + ".") or allowed == name:
                return _ALLOWED_MODULES[allowed]
        raise ImportError(
            f"import '{name}' is not allowed in the playground. "
            "Only django.db.models, django.db.models.functions, "
            "django.db.models.aggregates, and django.db are permitted."
        )

    builtins = dict(_SAFE_BUILTINS)
    builtins["print"] = lambda *a, **kw: print(*a, **{**kw, "file": print_buffer})
    builtins["__import__"] = safe_import
    return {"__builtins__": builtins, **_MODEL_GLOBALS}


# ── Serialiser ────────────────────────────────────────────────────────────────

def _serialise(obj):
    import decimal
    from django.db.models.query import QuerySet
    from django.db.models import Model
    from django.forms.models import model_to_dict

    if isinstance(obj, QuerySet):
        return [_serialise(item) for item in obj]
    if isinstance(obj, Model):
        d = model_to_dict(obj)
        # M2M fields come back as a list of model instances — convert to names
        for key, val in d.items():
            if isinstance(val, list):
                d[key] = ", ".join(str(item) for item in val) if val else ""
        return d
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialise(i) for i in obj]
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, (set, frozenset)):
        return [_serialise(i) for i in obj]
    return obj


# ── N+1 detector ──────────────────────────────────────────────────────────────

# Maps DB table name → model class (populated once at startup)
_TABLE_TO_MODEL: dict[str, type] = {}

def _build_table_model_map():
    global _TABLE_TO_MODEL
    if _TABLE_TO_MODEL:
        return
    for model in [Category, Product, Customer, Order, OrderItem, Review, Tag]:
        _TABLE_TO_MODEL[model._meta.db_table] = model

_build_table_model_map()


def _normalise_sql(sql: str) -> str:
    """Strip literal values to produce a query 'shape' for grouping."""
    sql = re.sub(r"'[^']*'", "?", sql)       # string literals
    sql = re.sub(r"\b\d+\b", "?", sql)        # integers
    sql = re.sub(r"\s+", " ", sql)             # collapse whitespace
    return sql.strip().lower()


def _classify_n1(shape: str, example_sql: str, user_code: str) -> dict:
    """
    Classify the N+1 pattern and produce a concrete fix suggestion.

    Returns dict with keys:
      pattern_type: "fk_access" | "reverse_fk" | "m2m" | "aggregate_loop" | "unknown"
      fix_method:   "select_related" | "prefetch_related" | "annotate" | None
      related_field: the field name to pass to select_related/prefetch_related
      suggested_fix: a rewritten code string (best-effort)
    """
    shape_lower = shape.lower()
    example_lower = example_sql.lower()

    # ── Detect which table is being queried repeatedly ─────────────────────────
    repeated_table = None
    for table in _TABLE_TO_MODEL:
        if f'from "{table}"' in example_lower or f"from {table}" in example_lower:
            repeated_table = table
            break

    repeated_model = _TABLE_TO_MODEL.get(repeated_table) if repeated_table else None

    # ── Classify the WHERE clause pattern ─────────────────────────────────────
    # COUNT pattern: SELECT COUNT(*) ... (aggregate in loop)
    is_count = "select count" in shape_lower
    # JOIN pattern: INNER JOIN or LEFT OUTER JOIN present
    has_join = "inner join" in shape_lower or "left outer join" in shape_lower
    # PK lookup: WHERE "table"."id" = ? — forward FK deferred load
    pk_lookup = re.search(r'where "[^"]+"\."id" = \?', shape_lower)
    # FK column lookup: WHERE "table"."something_id" = ? — reverse FK or explicit filter
    fk_col_lookup = re.search(r'where "[^"]+"\."([^"]+_id)" = \?', shape_lower)
    # IN clause: WHERE "table"."something_id" IN (...)
    in_lookup = re.search(r'where "[^"]+"\."([^"]+_id)" in \(', shape_lower)

    # ── Determine field name and fix method ───────────────────────────────────
    pattern_type = "unknown"
    fix_method = None
    related_field = None

    if is_count:
        # SELECT COUNT(*) run once per row → aggregate in loop
        pattern_type = "aggregate_loop"
        fix_method = "annotate"
        related_field = _guess_loop_attribute(user_code)

    elif pk_lookup and repeated_model:
        # WHERE "related_table"."id" = ? — deferred FK access (o.customer triggers this)
        # The field name is the lowercase model name (or find it from user code)
        pattern_type = "fk_access"
        fix_method = "select_related"
        # Derive field name: find which attribute in the loop resolves to this model
        related_field = _find_fk_field_for_model(repeated_model, user_code)
        if not related_field:
            related_field = repeated_model.__name__.lower()

    elif fk_col_lookup and not pk_lookup:
        # WHERE "table"."parent_id" = ? — reverse FK (orders fetched per customer)
        # The repeated table is the *related* model; find its reverse accessor name.
        pattern_type = "reverse_fk"
        fix_method = "prefetch_related"
        # Best: use the lowercase repeated model name as the accessor (e.g. "orders")
        if repeated_model:
            related_field = repeated_model.__name__.lower() + "s"
            # Verify the accessor actually exists on another model
            for m in _TABLE_TO_MODEL.values():
                for f in m._meta.get_fields():
                    if (
                        hasattr(f, "related_model")
                        and f.related_model is repeated_model
                        and hasattr(f, "get_accessor_name")
                    ):
                        related_field = f.get_accessor_name()
                        break
        if not related_field:
            related_field = _guess_loop_attribute(user_code)
        if not related_field:
            col = fk_col_lookup.group(1)
            related_field = col[:-3] if col.endswith("_id") else col

    elif in_lookup:
        # IN clause — M2M or prefetch_related intermediate table
        pattern_type = "m2m"
        fix_method = "prefetch_related"
        related_field = _guess_loop_attribute(user_code)

    elif has_join and repeated_model:
        pattern_type = "m2m"
        fix_method = "prefetch_related"
        related_field = _guess_loop_attribute(user_code)

    else:
        pattern_type = "reverse_fk"
        fix_method = "prefetch_related"
        related_field = _guess_loop_attribute(user_code)

    # ── Generate the suggested fix ────────────────────────────────────────────
    suggested_fix = _generate_fix(
        user_code, pattern_type, fix_method, related_field, repeated_model
    )

    return {
        "pattern_type": pattern_type,
        "fix_method": fix_method,
        "related_field": related_field,
        "suggested_fix": suggested_fix,
    }


_SKIP_ATTRS = frozenset({
    "id", "pk", "name", "title", "email", "status", "price", "stock",
    "all", "count", "filter", "objects", "values", "exists", "aggregate",
    "created_at", "updated_at", "quantity", "total_amount", "rating",
    "description", "is_active", "is_bestseller", "isbn", "published_date",
})


def _guess_loop_attribute(user_code: str) -> str | None:
    """
    Walk the AST and return the first non-trivial attribute accessed
    on a loop variable (likely a relation accessor).
    """
    try:
        tree = ast.parse(user_code)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.ListComp, ast.GeneratorExp)):
            # Get the loop variable name(s)
            loop_vars: set[str] = set()
            target = getattr(node, "target", None) or getattr(node, "generators", [None])[0]
            if hasattr(target, "target"):
                target = target.target  # GeneratorExp/ListComp .generators[0].target
            if isinstance(target, ast.Name):
                loop_vars.add(target.id)

            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id in loop_vars
                    and child.attr not in _SKIP_ATTRS
                ):
                    return child.attr
    return None


def _find_fk_field_for_model(model, user_code: str) -> str | None:
    """
    Given a model class that is being fetched repeatedly (e.g. Customer),
    find which attribute name on the loop object maps to it by checking
    the actual FK fields of all models in scope.
    """
    target_name = model.__name__  # e.g. "Customer"
    for src_model in _TABLE_TO_MODEL.values():
        for field in src_model._meta.get_fields():
            # ForeignKey or OneToOneField pointing at target_name
            if (
                hasattr(field, "related_model")
                and field.related_model is not None
                and field.related_model.__name__ == target_name
                and hasattr(field, "attname")  # concrete FK, not reverse
            ):
                return field.name  # e.g. "customer"
    # Fallback: scan the user code for the attribute name
    return _guess_loop_attribute(user_code)


def _generate_fix(code: str, pattern_type: str, fix_method: str | None,
                  related_field: str | None, repeated_model) -> str | None:
    """
    Attempt to rewrite the user's queryset call to include the fix.
    Works by AST-locating the primary .objects.all()/.filter() call and
    injecting .select_related() / .prefetch_related() / .annotate().
    Falls back to a template comment if the code is too complex to rewrite.
    """
    if not fix_method or not related_field:
        return None

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    # Find the primary model being queried from the source
    primary_model_name = _find_primary_model(tree, code)

    if pattern_type == "aggregate_loop" and fix_method == "annotate":
        # Suggest annotate(Count/Sum) instead of loop + .count()/.aggregate()
        agg_func = _detect_loop_aggregate(tree)
        if primary_model_name and agg_func:
            return (
                f"from django.db.models import {agg_func}\n"
                f"result = (\n"
                f"    {primary_model_name}.objects\n"
                f"    .annotate({related_field}_count={agg_func}('{related_field}'))\n"
                f"    .values('name', '{related_field}_count')\n"
                f")"
            )

    if fix_method in ("select_related", "prefetch_related"):
        # Try to inject into the existing queryset call
        rewritten = _inject_relation_method(code, primary_model_name, fix_method, related_field)
        if rewritten:
            return rewritten

        # Fallback: generic template
        if primary_model_name:
            return (
                f"# Add {fix_method}('{related_field}') to avoid N+1\n"
                f"qs = {primary_model_name}.objects.{fix_method}('{related_field}').all()\n"
                f"# then loop over qs instead"
            )

    return None


def _find_primary_model(tree: ast.AST, code: str) -> str | None:
    """Find the first Model.objects.* call in the AST and return the model name."""
    known = {"Category", "Product", "Customer", "Order", "OrderItem", "Review", "Tag"}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "objects"
            and isinstance(node.value, ast.Name)
            and node.value.id in known
        ):
            return node.value.id
    return None


def _detect_loop_aggregate(tree: ast.AST) -> str | None:
    """Return the appropriate aggregate class name for a loop-based aggregate call."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.ListComp, ast.GeneratorExp)):
            for child in ast.walk(node):
                if isinstance(child, ast.Attribute):
                    if child.attr == "count":
                        return "Count"
                    if child.attr in ("sum", "aggregate"):
                        return "Sum"
                    if child.attr in ("average", "avg"):
                        return "Avg"
    return "Count"  # safe default


def _inject_relation_method(code: str, model_name: str | None,
                             method: str, field: str) -> str | None:
    """
    Rewrite code to add select_related/prefetch_related.
    Handles patterns:
      Model.objects.all()              → Model.objects.select_related('field').all()
      Model.objects.filter(...)        → Model.objects.select_related('field').filter(...)
      Model.objects.select_related(...).all()  → Model.objects.select_related(..., 'field').all()
      list(Model.objects.all())        → list(Model.objects.select_related('field').all())
    Uses regex on the source string — safe enough for suggestion display.
    """
    if not model_name:
        return None

    # Already has the fix method?
    if f".{method}(" in code:
        # Add the field to the existing call if missing
        existing = re.search(rf"\.{method}\(([^)]*)\)", code)
        if existing and field not in existing.group(1):
            old_call = existing.group(0)
            args = existing.group(1).strip()
            new_args = f"{args}, '{field}'" if args else f"'{field}'"
            return code.replace(old_call, f".{method}({new_args})", 1)
        return None  # already contains this field

    # Insert after .objects on the first occurrence
    pattern = rf"({re.escape(model_name)}\.objects)"
    replacement = rf"\1.{method}('{field}')"
    rewritten, n = re.subn(pattern, replacement, code, count=1)
    if n:
        return rewritten
    return None


def _detect_n1(queries: list, user_code: str = "") -> dict | None:
    """
    Analyse the captured SQL query list for N+1 patterns.
    Returns a warning dict (with suggested fix) if detected, else None.
    """
    if len(queries) < 3:
        return None

    shapes: dict[str, list] = {}
    for q in queries:
        shape = _normalise_sql(q["sql"])
        shapes.setdefault(shape, []).append(q["sql"])

    # Skip transaction control statements
    skip = {"begin", "savepoint", "release savepoint", "rollback to savepoint", "commit"}
    shapes = {
        s: examples for s, examples in shapes.items()
        if not any(s.startswith(k) for k in skip)
    }

    if not shapes:
        return None

    worst_shape, worst_examples = max(shapes.items(), key=lambda x: len(x[1]))
    count = len(worst_examples)

    if count < 3:
        return None

    example_sql = worst_examples[0]
    classification = _classify_n1(worst_shape, example_sql, user_code)

    fix_method = classification["fix_method"]
    related_field = classification["related_field"]

    # Build the tip message
    if fix_method == "select_related" and related_field:
        tip = (
            f"This query ran {count}× with the same shape — N+1 detected on "
            f"'{related_field}' (ForeignKey). "
            f"Add .select_related('{related_field}') to your queryset to fetch it in one JOIN."
        )
    elif fix_method == "prefetch_related" and related_field:
        tip = (
            f"This query ran {count}× — N+1 detected on '{related_field}' "
            f"(reverse FK / ManyToMany). "
            f"Add .prefetch_related('{related_field}') to fetch all related rows in one extra query."
        )
    elif fix_method == "annotate" and related_field:
        tip = (
            f"This query ran {count}× — you're calling .count() or .aggregate() inside a loop. "
            f"Replace the loop with .annotate({related_field}_count=Count('{related_field}')) "
            f"to compute it in a single SQL GROUP BY."
        )
    else:
        tip = (
            f"This query ran {count}× with the same shape — likely an N+1 problem. "
            "Use select_related() for ForeignKey/OneToOne fields, "
            "or prefetch_related() for ManyToMany/reverse FK."
        )

    return {
        "count": count,
        "example": example_sql,
        "pattern_type": classification["pattern_type"],
        "fix_method": fix_method,
        "related_field": related_field,
        "suggested_fix": classification["suggested_fix"],
        "tip": tip,
    }


# ── Query explainer ───────────────────────────────────────────────────────────

def _explain_code(code: str) -> list[str]:
    """
    Parse the user's code with AST and produce plain-English bullet points
    describing what ORM operations are being performed.
    """
    hints = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return hints

    # Walk all attribute-access chains and method calls
    calls_found = []

    class _Visitor(ast.NodeVisitor):
        def visit_Call(self, node):
            # Collect dotted call chains like Model.objects.filter(...).values(...)
            chain = []
            cur = node
            while isinstance(cur, ast.Call):
                if isinstance(cur.func, ast.Attribute):
                    chain.append(cur.func.attr)
                cur = cur.func.value if isinstance(cur.func, ast.Attribute) else None
                if cur is None:
                    break
            calls_found.append(list(reversed(chain)))
            self.generic_visit(node)

    _Visitor().visit(tree)

    seen = set()

    def add(msg):
        if msg not in seen:
            seen.add(msg)
            hints.append(msg)

    for chain in calls_found:
        chain_str = ".".join(chain)

        if "select_related" in chain:
            add("Uses select_related() — fetches related objects in a single SQL JOIN, preventing N+1 for ForeignKey/OneToOne fields.")
        if "prefetch_related" in chain:
            add("Uses prefetch_related() — runs a separate query per relation then joins in Python, efficient for ManyToMany and reverse FK.")
        if "annotate" in chain:
            add("Uses annotate() — adds a computed column to each row (e.g. Count, Sum, Avg) without loading related objects into memory.")
        if "aggregate" in chain:
            add("Uses aggregate() — collapses the entire queryset into a single summary value (e.g. total revenue, average rating).")
        if "filter" in chain and "exclude" not in chain:
            add("Uses filter() — adds a WHERE clause; only matching rows are returned.")
        if "exclude" in chain:
            add("Uses exclude() — adds a WHERE NOT clause; matching rows are omitted.")
        if "values" in chain and "values_list" not in chain:
            add("Uses values() — returns dicts instead of model instances, more efficient when you only need specific fields.")
        if "values_list" in chain:
            add("Uses values_list() — returns tuples instead of model instances.")
        if "order_by" in chain:
            add("Uses order_by() — sorts results. Prefix field with '-' for descending order.")
        if "distinct" in chain:
            add("Uses distinct() — removes duplicate rows from the result set.")
        if "raw" in chain:
            add("Uses raw() — executes a raw SQL query but returns model instances.")
        if "cursor" in chain:
            add("Uses connection.cursor() — raw SQL execution, returns plain tuples/dicts, bypasses the ORM entirely.")

    # Check for imports
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [a.name for a in node.names]
            else:
                names = [a.name for a in node.names]
            for name in names:
                if name == "Count":
                    add("Imports Count — counts related objects per row.")
                if name in ("Sum", "Avg", "Max", "Min"):
                    add(f"Imports {name} — computes {name.lower()} of a numeric field across related rows.")
                if name == "F":
                    add("Imports F() — references a model field value in an expression without loading it into Python.")
                if name == "Q":
                    add("Imports Q() — allows complex WHERE conditions with AND (&), OR (|), and NOT (~) logic.")
                if name == "Subquery":
                    add("Imports Subquery — embeds a queryset as a subquery inside another queryset's annotation or filter.")
                if name == "OuterRef":
                    add("Imports OuterRef — references a field from the outer queryset inside a Subquery.")
                if name == "Window":
                    add("Imports Window — applies a window function (Rank, RowNumber, Lead, Lag) across a partition of rows without collapsing them.")
                if name in ("Rank", "RowNumber", "Lead", "Lag", "DenseRank"):
                    add(f"Imports {name} — a window function that computes {name} position/offset within an ordered partition.")
                if name in ("TruncMonth", "TruncYear", "TruncDay", "TruncDate"):
                    add(f"Imports {name} — truncates a datetime field to {name.replace('Trunc','').lower()} precision, useful for time-series grouping.")

    # Detect loop-based access patterns (potential N+1 in user code)
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            # Check if loop body accesses attributes on loop variable
            loop_var = node.target.id if isinstance(node.target, ast.Name) else None
            if loop_var:
                for child in ast.walk(node):
                    if (
                        isinstance(child, ast.Attribute)
                        and isinstance(child.value, ast.Name)
                        and child.value.id == loop_var
                    ):
                        add(
                            f"Warning: accessing '{child.attr}' on '{loop_var}' inside a loop "
                            "may cause N+1 queries if it triggers a lazy DB lookup. "
                            "Use select_related() or prefetch_related() on the queryset before the loop."
                        )
                        break

    if not hints:
        hints.append("Basic queryset — no special ORM features detected.")

    return hints


# ── Worker ────────────────────────────────────────────────────────────────────

class _AlwaysRollback(Exception):
    pass


def _run_in_thread(code: str, exec_globals: dict, timeout: int):
    """
    Returns (status, data, print_output, sql_queries, duration_ms)
    status: "ok" | "error"
    """
    result_queue = queue.Queue()

    def worker():
        local_ns = {}
        print_buf = io.StringIO()
        exec_globals["__builtins__"]["print"] = (
            lambda *a, **kw: print(*a, **{**kw, "file": print_buf})
        )
        try:
            compiled = compile(code, "<playground>", "exec")

            # Enable Django query logging for this execution
            old_debug = settings.DEBUG
            settings.DEBUG = True
            reset_queries()

            t0 = time.monotonic()
            with transaction.atomic():
                exec(compiled, exec_globals, local_ns)

                if "result" in local_ns:
                    raw = local_ns["result"]
                elif local_ns:
                    raw = list(local_ns.values())[-1]
                else:
                    raw = eval(compile(code, "<playground>", "eval"), exec_globals)

                data = _serialise(raw)
                duration_ms = round((time.monotonic() - t0) * 1000, 2)

                # Capture SQL before rollback clears connection state
                sql_queries = [
                    {"sql": q["sql"], "time_ms": round(float(q["time"]) * 1000, 2)}
                    for q in connection.queries
                ]
                raise _AlwaysRollback

        except _AlwaysRollback:
            settings.DEBUG = old_debug
            result_queue.put(("ok", data, print_buf.getvalue(), sql_queries, duration_ms))
        except SyntaxError as e:
            settings.DEBUG = old_debug
            result_queue.put(("error", f"SyntaxError: {e}", print_buf.getvalue(), [], 0))
        except Exception:
            settings.DEBUG = old_debug
            result_queue.put(("error", traceback.format_exc(), print_buf.getvalue(), [], 0))

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        return "error", f"Execution timed out after {timeout}s. Check for infinite loops or very large result sets.", "", [], 0

    return result_queue.get()


# ── Views ─────────────────────────────────────────────────────────────────────

@ensure_csrf_cookie
def index(request):
    context = {
        "examples": EXAMPLE_QUERIES,
        "examples_json": json.dumps([ex["code"] for ex in EXAMPLE_QUERIES]),
        "schema": json.dumps(_build_schema()),
        "timeout": QUERY_TIMEOUT,
    }
    return render(request, "playground/index.html", context)


@require_POST
def execute(request):
    try:
        body = json.loads(request.body)
        code = body.get("code", "").strip()
        mode = body.get("mode", "single")   # "single" | "compare"
        code_b = body.get("code_b", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    if not code:
        return JsonResponse({"error": "No code provided."}, status=400)

    for token in _BLOCKED_TOKENS:
        if token in code or (code_b and token in code_b):
            return JsonResponse(
                {"error": f"Blocked: '{token}' is not allowed in the playground."},
                status=400,
            )

    def run(c):
        print_buf = io.StringIO()
        eg = _make_exec_globals(print_buf)
        status, data, stdout, sql_queries, duration_ms = _run_in_thread(c, eg, QUERY_TIMEOUT)
        n1 = _detect_n1(sql_queries, c) if status == "ok" else None
        explain = _explain_code(c)
        return status, data, stdout, sql_queries, duration_ms, n1, explain

    status, data, stdout, sql_queries, duration_ms, n1, explain = run(code)

    if mode == "compare" and code_b:
        status_b, data_b, stdout_b, sql_b, dur_b, n1_b, explain_b = run(code_b)
        return JsonResponse({
            "mode": "compare",
            "a": {
                "status": status,
                "result": data if status == "ok" else None,
                "error": data if status == "error" else None,
                "stdout": stdout or None,
                "sql": sql_queries,
                "duration_ms": duration_ms,
                "n1_warning": n1,
                "explain": explain,
            },
            "b": {
                "status": status_b,
                "result": data_b if status_b == "ok" else None,
                "error": data_b if status_b == "error" else None,
                "stdout": stdout_b or None,
                "sql": sql_b,
                "duration_ms": dur_b,
                "n1_warning": n1_b,
                "explain": explain_b,
            },
        })

    if status == "error":
        return JsonResponse({
            "error": data,
            "stdout": stdout or None,
            "sql": sql_queries,
            "duration_ms": duration_ms,
            "explain": explain,
        })

    return JsonResponse({
        "result": data,
        "stdout": stdout or None,
        "sql": sql_queries,
        "duration_ms": duration_ms,
        "n1_warning": n1,
        "explain": explain,
    })


def _build_schema():
    import decimal
    from django.apps import apps

    def _safe_val(v):
        """Convert a field value to a JSON-safe scalar."""
        if v is None:
            return None
        if isinstance(v, decimal.Decimal):
            return float(v)
        if hasattr(v, "isoformat"):          # date / datetime
            return v.isoformat()
        if isinstance(v, (list, tuple, set)):
            return [_safe_val(i) for i in v]
        return v

    schema = []
    for model in apps.get_app_config("playground").get_models():
        # ── Fields ────────────────────────────────────────────────────────────
        concrete_fields = []   # only concrete DB columns (for the preview table)
        all_fields = []        # everything including relations (for the field list)

        for field in model._meta.get_fields():
            try:
                ftype = (
                    field.get_internal_type()
                    if hasattr(field, "get_internal_type")
                    else type(field).__name__
                )
                entry = {"name": field.name, "type": ftype}

                # Annotate FK / M2M targets
                if hasattr(field, "related_model") and field.related_model:
                    entry["related_model"] = field.related_model.__name__

                all_fields.append(entry)

                # Track which fields are concrete DB columns
                if hasattr(field, "column") and field.column:
                    concrete_fields.append(field.name)
            except Exception:
                pass

        # ── Sample rows ───────────────────────────────────────────────────────
        # Fetch up to 5 rows using only concrete fields (no reverse relations)
        preview_rows = []
        preview_cols = concrete_fields[:8]   # cap columns to keep it readable
        try:
            qs = model.objects.values(*preview_cols)[:5]
            for row in qs:
                preview_rows.append({k: _safe_val(v) for k, v in row.items()})
        except Exception:
            pass

        # ── Row count ─────────────────────────────────────────────────────────
        try:
            row_count = model.objects.count()
        except Exception:
            row_count = None

        schema.append({
            "model": model.__name__,
            "table": model._meta.db_table,
            "row_count": row_count,
            "fields": all_fields,
            "preview_cols": preview_cols,
            "preview_rows": preview_rows,
        })
    return schema
