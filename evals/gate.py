"""Regression gate: exit non-zero if eval accuracy drops below evals/thresholds.json.

    python evals/gate.py                    # FakeLLM; this is what CI runs
    python evals/gate.py --provider gemini  # only gates if a "gemini" entry exists in thresholds.json

With the fake provider this guards the *pipeline and the rule-based stand-in* against accidental
regressions (broken tool loop, schema drift, scoring bugs). It is not a model-quality gate.
Set thresholds slightly below the currently measured values so noise does not flake CI but a real
regression does. Thresholds for a real model must be measured with a key, then added by a human.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_evals import FIELDS, evaluate, render  # noqa: E402

THRESHOLDS = Path(__file__).resolve().parent / "thresholds.json"


def check(report: dict, thresholds: dict) -> list[str]:
    """Return a list of human-readable violations (empty list == pass)."""
    problems = []
    for f in FIELDS:
        floor = thresholds["min_accuracy"][f]
        got = report["accuracy"][f]
        if got < floor:
            problems.append(f"accuracy[{f}] {got:.3f} < threshold {floor:.3f}")
    max_failed = thresholds.get("max_failed_runs", 0)
    if report["failed_runs"] > max_failed:
        problems.append(f"failed runs {report['failed_runs']} > allowed {max_failed}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="fake", choices=["fake", "gemini", "auto"])
    args = ap.parse_args()
    all_thresholds = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    report = evaluate(args.provider)
    print(render(report))
    thresholds = all_thresholds.get(report["provider"])
    if thresholds is None:
        print(f"\nGATE ERROR: no thresholds for provider '{report['provider']}' in thresholds.json. "
              "Measure first, then add them by hand.")
        return 2
    problems = check(report, thresholds)
    print()
    if problems:
        print("GATE FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"GATE PASSED for provider '{report['provider']}' (floors: {thresholds['min_accuracy']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
