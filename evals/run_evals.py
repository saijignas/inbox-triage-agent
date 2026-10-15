"""Run the triage agent over the labeled sample set and report accuracy per field.

    python evals/run_evals.py                  # FakeLLM (default; pipeline check only)
    python evals/run_evals.py --provider gemini  # needs GEMINI_API_KEY (and requirements-gemini.txt)
    python evals/run_evals.py --provider auto    # gemini if GEMINI_API_KEY is set, else fake

HONESTY NOTE: with FakeLLM the "model" is a handful of keyword rules written by the same author
as the dataset. The numbers below prove the *pipeline* (tool loop, validation, trace, scoring)
works end to end; they say NOTHING about real-model quality. Real numbers require a Gemini run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "backend"))

from app.agent import AgentConfig, EmailInput, FakeLLM, GeminiLLM, LLMProvider, ToolRegistry, run_agent  # noqa: E402
from app.agent.schemas import CATEGORIES, URGENCIES  # noqa: E402

DATASET = ROOT / "dataset.json"
RESULTS_DIR = ROOT / "results"
FIELDS = ("category", "urgency", "needs_reply")


def make_provider(name: str) -> tuple[LLMProvider, str]:
    if name == "auto":
        name = "gemini" if os.environ.get("GEMINI_API_KEY") else "fake"
    if name == "fake":
        return FakeLLM(), "fake"
    if name == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            sys.exit("GEMINI_API_KEY is not set; cannot run the gemini evaluation")
        return GeminiLLM(api_key=key, model=os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")), "gemini"
    sys.exit(f"unknown provider {name!r}")


def evaluate(provider_name: str = "fake", delay_s: float = 0.0) -> dict:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    correct = Counter()
    failed_runs = 0
    confusion: dict[str, dict[str, Counter]] = {f: defaultdict(Counter) for f in ("category", "urgency")}
    mismatches = []
    resolved = provider_name
    for item in data:
        provider, resolved = make_provider(provider_name)
        email = EmailInput(sender=item["sender"], subject=item["subject"], body=item["body"])
        registry = ToolRegistry(email, lambda q, n, ex: [])  # eval emails are independent: no history
        run = run_agent(email, provider, registry, AgentConfig(max_steps=8, timeout_s=60))
        exp = item["expected"]
        if run.ok:
            got = {"category": run.category, "urgency": run.urgency, "needs_reply": run.needs_reply}
        else:
            failed_runs += 1
            got = {"category": "FAILED", "urgency": "FAILED", "needs_reply": None}
        bad = {}
        for f in FIELDS:
            if got[f] == exp[f]:
                correct[f] += 1
            else:
                bad[f] = {"expected": exp[f], "got": got[f]}
        for f in ("category", "urgency"):
            confusion[f][exp[f]][got[f]] += 1
        if bad:
            mismatches.append({"id": item["id"], "subject": item["subject"], "diffs": bad, "error": run.error_code})
        if delay_s:
            time.sleep(delay_s)
    n = len(data)
    return {
        "provider": resolved,
        "n": n,
        "accuracy": {f: correct[f] / n for f in FIELDS},
        "failed_runs": failed_runs,
        "confusion": {f: {e: dict(c) for e, c in rows.items()} for f, rows in confusion.items()},
        "mismatches": mismatches,
    }


def _table(rows: dict[str, dict[str, int]], labels: tuple[str, ...]) -> str:
    cols = list(labels) + (["FAILED"] if any("FAILED" in r for r in rows.values()) else [])
    w = max(len(c) for c in cols + list(labels)) + 1
    out = [" " * w + " | " + " ".join(f"{c[:6]:>6}" for c in cols) + "   <- predicted"]
    for e in labels:
        r = rows.get(e, {})
        out.append(f"{e:<{w}} | " + " ".join(f"{r.get(c, 0):>6}" for c in cols))
    return "\n".join(out)


def render(report: dict) -> str:
    fake = report["provider"] == "fake"
    banner = (
        "PIPELINE CHECK ONLY (FakeLLM keyword rules). These numbers do NOT measure model quality."
        if fake
        else f"MODEL EVAL (provider={report['provider']}) on {report['n']} synthetic emails (small, author-labeled sample)."
    )
    lines = ["=" * 78, banner, "=" * 78, f"emails: {report['n']}   failed runs: {report['failed_runs']}", ""]
    for f in FIELDS:
        lines.append(f"accuracy[{f}] = {report['accuracy'][f]:.3f}")
    lines += ["", "category confusion (rows = expected):", _table(report["confusion"]["category"], CATEGORIES)]
    lines += ["", "urgency confusion (rows = expected):", _table(report["confusion"]["urgency"], URGENCIES)]
    if report["mismatches"]:
        lines += ["", f"mismatches ({len(report['mismatches'])} emails):"]
        for m in report["mismatches"]:
            d = ", ".join(f"{k}: expected {v['expected']} got {v['got']}" for k, v in m["diffs"].items())
            lines.append(f"  {m['id']} {m['subject'][:34]:<34} {d}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="fake", choices=["fake", "gemini", "auto"])
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between emails (API rate limits)")
    args = ap.parse_args()
    report = evaluate(args.provider, args.delay)
    print(render(report))
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"latest_{report['provider']}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
