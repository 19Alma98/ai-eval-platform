"""Clean-install smoke test: exercise OpenGrade the way a new user does after `pip install`.

Run it with the Python of a fresh virtual environment where only the published (or freshly
built) packages are installed, from a directory outside this repository:

    python -m venv /tmp/og && /tmp/og/bin/pip install 'opengrade-ai[ui]'
    cd /tmp && /tmp/og/bin/python /path/to/scripts/smoke_install.py

What it checks, in order:

1. `import opengrade` works and the `opengrade` console script is on the venv's PATH.
2. `opengrade ui` starts on a free port with a new SQLite file (schema migrations shipped in
   the wheel), `/ready` answers and `/` serves the packaged UI.
3. The SDK sends a trace over OTLP and the API lists it.
4. `opengrade.evaluate` runs an offline experiment (deterministic + local metric) and the
   server scores it.
5. `opengrade evaluate --config` (the CI gate) passes on a good run, promotes a baseline,
   and fails with exit code 1 on a regressed run.

With `--sdk-only` it checks a plain `pip install opengrade-ai` (no `[ui]` extra) instead:
the import works and `opengrade` exits 1 with an install hint.

Only the standard library and the installed `opengrade` package are used. Exit code 0 means
every check passed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT = "install-smoke"

GOLD: list[dict[str, Any]] = [
    {
        "input": "How many PTO days do full-time employees get?",
        "expected_output": "Full-time employees receive 20 days of PTO per calendar year.",
        "expected_doc_ids": ["pto"],
        "must_contain": ["20 days"],
    },
    {
        "input": "How often must passwords be rotated?",
        "expected_output": "Passwords must be rotated every 90 days.",
        "expected_doc_ids": ["password"],
        "must_contain": ["90 days"],
    },
    {
        "input": "When is payroll processed?",
        "expected_output": "Payroll is processed on the last business day of each month.",
        "expected_doc_ids": ["payroll"],
        "must_contain": ["last business day"],
    },
]

TASK_MODULE = """
import os

ANSWERS = {
    "How many PTO days do full-time employees get?":
        "Full-time employees receive 20 days of PTO per calendar year.",
    "How often must passwords be rotated?": "Passwords must be rotated every 90 days.",
    "When is payroll processed?": "Payroll is processed on the last business day of each month.",
}


def task(item):
    if os.getenv("SMOKE_BROKEN") == "1":
        return "I don't know."
    return ANSWERS[str(item.input)]
"""

POLICY = """
project: {project}

evaluate:
  task: smoke_task:task
  dataset: gold.jsonl
  metrics: [must_contain]
  name: smoke-gate
  task_type: rag_qa
  baseline: alias:main

must_contain:
  min: 1.0

# 3 items are too few for the statistical mean check, which fails closed by default;
# the item-level check (no test case that passed on main may fail) still applies.
regression:
  max_new_failures: 0
  allow_insufficient_n: true
"""


class SmokeError(Exception):
    pass


def step(title: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        def run(*args: Any, **kwargs: Any) -> Any:
            print(f"\n=== {title}", flush=True)
            started = time.monotonic()
            result = fn(*args, **kwargs)
            print(f"--- ok ({time.monotonic() - started:.1f}s)", flush=True)
            return result

        return run

    return wrap


def console_script(name: str) -> str:
    """The console script installed next to this interpreter (the venv under test)."""
    bindir = Path(sys.executable).parent
    for candidate in (bindir / name, bindir / f"{name}.exe"):
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    if found is None:
        raise SmokeError(f"console script {name!r} not found next to {sys.executable}")
    return found


def clean_env(**extra: str) -> dict[str, str]:
    """Environment without OpenGrade/LLM settings leaking from the developer's shell."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("OPENGRADE_", "LLM_", "DATABASE_URL"))
    }
    env["PYTHONUTF8"] = "1"
    env.update(extra)
    return env


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def http(method: str, url: str, body: Any = None, timeout: float = 10.0) -> tuple[int, bytes]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def wait_for(predicate: Callable[[], bool], what: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    raise SmokeError(f"timed out after {timeout:.0f}s waiting for {what}")


@step("import opengrade")
def check_import() -> None:
    import opengrade

    print(f"opengrade from {opengrade.__file__}")
    for name in ("init", "trace", "span", "evaluate", "flush", "set_project", "Client"):
        if not hasattr(opengrade, name):
            raise SmokeError(f"opengrade.{name} is missing")
    if "site-packages" not in (opengrade.__file__ or ""):
        print("warning: opengrade is not imported from site-packages (editable install?)")


@step("opengrade without the [ui] extra prints an install hint")
def check_sdk_only_cli() -> None:
    from importlib.util import find_spec

    if find_spec("opengrade_server") is not None:
        raise SmokeError("opengrade_server is installed: --sdk-only needs a venv without [ui]")
    proc = subprocess.run(
        [console_script("opengrade"), "ui"],
        capture_output=True,
        text=True,
        env=clean_env(),
        timeout=60,
    )
    print(proc.stderr.strip())
    if proc.returncode != 1 or "opengrade-ai[ui]" not in proc.stderr:
        raise SmokeError(f"expected exit 1 with an install hint, got {proc.returncode}")


@step("opengrade ui starts and serves API + UI")
def start_ui(workdir: Path, port: int, log_path: Path) -> subprocess.Popen[bytes]:
    log = log_path.open("wb")
    proc = subprocess.Popen(
        [console_script("opengrade"), "ui", "--port", str(port), "--no-open"],
        cwd=workdir,
        stdout=log,
        stderr=subprocess.STDOUT,
        env=clean_env(),
    )
    base = f"http://127.0.0.1:{port}"

    def ready() -> bool:
        if proc.poll() is not None:
            raise SmokeError(f"opengrade ui exited with code {proc.returncode}")
        return http("GET", f"{base}/ready", timeout=2)[0] == 200

    wait_for(ready, "/ready", timeout=120)
    status, html = http("GET", f"{base}/")
    if status != 200 or b"<html" not in html.lower():
        raise SmokeError(f"GET / did not return the packaged UI (status {status})")
    if not (workdir / "opengrade.db").exists():
        raise SmokeError("opengrade ui did not create ./opengrade.db")
    print(f"UI and API on {base}, database {workdir / 'opengrade.db'}")
    return proc


@step("SDK trace reaches the server")
def check_trace(base: str) -> str:
    import opengrade

    opengrade.set_tracking_uri(base)
    project = opengrade.set_project(PROJECT)
    if project is None:
        raise SmokeError("set_project returned None (platform unreachable?)")
    opengrade.init(service_name="install-smoke", instrument=False)

    @opengrade.trace
    def answer(question: str) -> str:
        with opengrade.span("retrieve", kind="RETRIEVER", input=question) as s:
            s.set_output(["pto"])
        return "20 days"

    answer("How many PTO days?")
    trace_id = opengrade.current_trace_id()  # None outside the span; only for the log
    opengrade.flush()

    url = f"{base}/api/v1/projects/{project.id}/traces?limit=10"

    def listed() -> bool:
        status, body = http("GET", url)
        return status == 200 and any(
            str(t.get("name", "")).endswith("answer") for t in json.loads(body).get("items", [])
        )

    wait_for(listed, "the trace in GET /traces", timeout=60)
    print(f"trace listed in project {project.id} {trace_id or ''}".rstrip())
    return str(project.id)


@step("opengrade.evaluate runs and scores an experiment")
def check_evaluate() -> None:
    import opengrade

    answers = {str(row["input"]): str(row["expected_output"]) for row in GOLD}

    def task(item: Any) -> str:
        return answers[str(item.input)]

    def short(item: Any, output: str) -> bool:
        return len(output) < 200

    result = opengrade.evaluate(
        dataset=GOLD,
        task=task,
        metrics=["must_contain", "exact_match", short],
        name="install-smoke",
        git=False,
        timeout=180,
    )
    print(result.summary())
    if result.errors:
        raise SmokeError(f"{len(result.errors)} task errors")
    if result.server_summary is None:
        raise SmokeError("the server did not return a summary for the experiment")
    scores = {ev.evaluator_name: ev.mean_score for ev in result.server_summary.evaluators}
    if scores.get("must_contain") != 1.0:
        raise SmokeError(f"must_contain should be 1.0, got {scores}")


@step("opengrade evaluate --config: gate passes, promotes, then blocks a regression")
def check_cli_gate(workdir: Path, base: str) -> None:
    (workdir / "smoke_task.py").write_text(textwrap.dedent(TASK_MODULE), encoding="utf-8")
    (workdir / "gold.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in GOLD), encoding="utf-8"
    )
    (workdir / "opengrade.yaml").write_text(POLICY.format(project=PROJECT), encoding="utf-8")
    cmd = [
        console_script("opengrade"),
        "evaluate",
        "--config",
        "opengrade.yaml",
        "--base-url",
        base,
    ]

    def run(label: str, expected: int, *args: str, broken: bool = False) -> None:
        env = clean_env(PYTHONPATH=str(workdir), SMOKE_BROKEN="1" if broken else "0")
        proc = subprocess.run(
            [*cmd, *args], cwd=workdir, capture_output=True, text=True, env=env, timeout=300
        )
        print(f"[{label}] exit {proc.returncode} (expected {expected})")
        if proc.returncode != expected:
            print(proc.stdout[-4000:], proc.stderr[-4000:], sep="\n")
            raise SmokeError(f"{label}: exit {proc.returncode}, expected {expected}")

    run("main: bootstrap baseline", 0, "--promote", "main")
    run("PR: same quality", 0, "--require-baseline")
    run("PR: regressed", 1, "--require-baseline", broken=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--sdk-only", action="store_true", help="check `pip install opengrade-ai` (no [ui])"
    )
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    args = parser.parse_args()

    print(f"Python {sys.version.split()[0]} on {sys.platform}: {sys.executable}")
    check_import()
    if args.sdk_only:
        check_sdk_only_cli()
        print("\nSMOKE OK (sdk only)")
        return 0

    workdir = Path(tempfile.mkdtemp(prefix="opengrade-smoke-"))
    log_path = workdir / "opengrade-ui.log"
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc: subprocess.Popen[bytes] | None = None
    ok = False
    try:
        proc = start_ui(workdir, port, log_path)
        check_trace(base)
        check_evaluate()
        check_cli_gate(workdir, base)
        ok = True
    except SmokeError as exc:
        print(f"\nSMOKE FAILED: {exc}", file=sys.stderr)
    except Exception:
        traceback.print_exc()
        print("\nSMOKE FAILED: unexpected error", file=sys.stderr)
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
        if not ok and log_path.exists():
            print("\n--- opengrade ui log (tail) ---", file=sys.stderr)
            print(log_path.read_text(errors="replace")[-6000:], file=sys.stderr)
        if args.keep or not ok:
            print(f"work dir kept: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)
    if ok:
        print("\nSMOKE OK")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
