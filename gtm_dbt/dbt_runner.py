"""Runs dbt as a subprocess and collects its artifacts. The agent never imports dbt internals.

Two invocations, because the dbt docs say `dbt build` does not run source freshness checks:
  1. dbt source freshness   -> <run>/dbt_freshness/sources.json
  2. dbt build              -> <run>/dbt_build/run_results.json and manifest.json
A missing dbt binary, a crash or unreadable artifacts are reported as dbt_invocation_failed; the
triage layer then fails closed (no releasable changes, publication held).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = ROOT / "dbt"


def dbt_executable() -> str | None:
    local = Path(sys.executable).parent / "dbt"
    if local.exists():
        return str(local)
    return shutil.which("dbt")


def _run(cmd: list[str], env: dict, cwd: Path, log_file: Path, timeout: int) -> int:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "w") as fh:
        try:
            p = subprocess.run(cmd, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
            return p.returncode
        except subprocess.TimeoutExpired:
            fh.write(f"\nTIMEOUT after {timeout}s\n")
            return 124
        except OSError as exc:
            fh.write(f"\nOSError: {exc}\n")
            return 127


def run_dbt(run_dir, db_path, project_dir=None, as_of: str | None = None, timeout: int = 600,
            dbt_bin: str | None = None) -> dict:
    run_dir, db_path = Path(run_dir), Path(db_path).resolve()
    project_dir = Path(project_dir or DBT_DIR)
    exe = dbt_bin or dbt_executable()
    result = {"dbt_bin": Path(exe).name if exe else None, "freshness_exit": None, "build_exit": None, "ok": False, "error": None}
    if not exe:
        result["error"] = "dbt executable not found (pip install -r requirements.txt)"
        return result
    env = {**os.environ, "GTM_DUCKDB_PATH": str(db_path), "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
           "DO_NOT_TRACK": "1"}
    common = ["--profiles-dir", str(project_dir), "--project-dir", str(project_dir), "--no-use-colors"]
    vars_arg = ["--vars", f"{{as_of_date: '{as_of}'}}"] if as_of else []
    fr_dir, bd_dir = run_dir / "dbt_freshness", run_dir / "dbt_build"
    result["freshness_exit"] = _run([exe, "source", "freshness", *common, "--target-path", str(fr_dir),
                                     "--log-path", str(fr_dir / "logs")], env, project_dir, fr_dir / "stdout.log", timeout)
    result["build_exit"] = _run([exe, "build", *common, *vars_arg, "--target-path", str(bd_dir),
                                 "--log-path", str(bd_dir / "logs")], env, project_dir, bd_dir / "stdout.log", timeout)
    missing = [p for p in (bd_dir / "run_results.json", bd_dir / "manifest.json") if not p.exists()]
    if result["build_exit"] in (124, 127) or missing:
        result["error"] = f"dbt build did not produce artifacts (exit {result['build_exit']}; missing {[m.name for m in missing]})"
        return result
    result["ok"] = True
    return result
