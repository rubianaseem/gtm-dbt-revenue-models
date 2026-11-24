"""Failure injection for evals, the demo and the failure suite. Mutates a COPY of the raw CSVs (and, for
code-change scenarios, a copy of the dbt project). Operations mirror real incidents: a connector that
stopped syncing, a renamed CRM field, a re-sync that duplicated rows, a new stage or currency, a date
format change, amounts entered in cents."""
from __future__ import annotations

import csv
import shutil
from datetime import datetime, timedelta
from pathlib import Path


def _read(path: Path):
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames), list(r)


def _write(path: Path, cols, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _pick(rows, op):
    if "ids" in op:
        return [r for r in rows if r.get("id") in set(op["ids"])]
    every = op.get("every", 10)
    start = op.get("start", 0)
    sel = rows[start::every]
    return sel[: op["limit"]] if "limit" in op else sel


def _transform(value: str, fn: str) -> str:
    if value in ("", None):
        return value
    if fn == "times_100":
        return str(int(float(value) * 100))
    if fn == "dmy_format":  # 2026-10-05T11:00:00Z -> 05/10/2026 11:00
        d = datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return d.strftime("%d/%m/%Y %H:%M")
    if fn == "plus_400_days":
        d = datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return (d + timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if fn == "minus_30_days":
        d = datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return (d - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if fn == "negate":
        return "-" + value
    if fn == "blank":
        return ""
    raise ValueError(fn)


def apply(raw_src, raw_dst, mutations: list, project_src=None, project_dst=None) -> dict:
    """Return {'sync_lag_hours': {...}, 'project_dir': path or None}."""
    raw_src, raw_dst = Path(raw_src), Path(raw_dst)
    if raw_dst.exists():
        shutil.rmtree(raw_dst)
    shutil.copytree(raw_src, raw_dst)
    lag, project_dir = {}, None
    for op in mutations:
        kind = op["op"]
        if kind == "sync_lag":
            lag[op["table"]] = op["hours"]
            continue
        if kind == "code_replace":
            if project_dir is None:
                project_dir = Path(project_dst)
                if project_dir.exists():
                    shutil.rmtree(project_dir)
                shutil.copytree(project_src, project_dir, ignore=shutil.ignore_patterns("target", "logs"))
            f = project_dir / op["file"]
            text = f.read_text()
            if op["old"] not in text:
                raise ValueError(f"code_replace: text not found in {op['file']}")
            f.write_text(text.replace(op["old"], op["new"]))
            continue
        path = raw_dst / f"{op['table']}.csv"
        cols, rows = _read(path)
        if kind == "rename_column":
            cols = [op["new"] if c == op["old"] else c for c in cols]
            rows = [{(op["new"] if k == op["old"] else k): v for k, v in r.items()} for r in rows]
        elif kind == "drop_column":
            cols = [c for c in cols if c != op["column"]]
            rows = [{k: v for k, v in r.items() if k != op["column"]} for r in rows]
        elif kind == "duplicate_rows":
            extra = [dict(r) for r in _pick(rows, op)]
            for r in extra:
                for k, v in (op.get("change") or {}).items():
                    r[k] = v
            rows += extra
        elif kind == "set_value":
            for r in _pick(rows, op):
                r[op["column"]] = op["value"]
        elif kind == "transform":
            for r in _pick(rows, op):
                r[op["column"]] = _transform(r[op["column"]], op["fn"])
        elif kind == "append_rows":
            rows += [{c: row.get(c, "") for c in cols} for row in op["rows"]]
        elif kind == "delete_rows":
            drop = {id(r) for r in _pick(rows, op)}
            rows = [r for r in rows if id(r) not in drop]
        else:
            raise ValueError(f"unknown mutation {kind}")
        _write(path, cols, rows)
    return {"sync_lag_hours": lag, "project_dir": project_dir}
