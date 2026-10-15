"""The eval harness itself is tested: dataset sanity, scoring, and the gate logic."""
import json
import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parents[2] / "evals"
sys.path.insert(0, str(EVALS))

import gate  # noqa: E402
import run_evals  # noqa: E402

from app.agent.schemas import CATEGORIES, URGENCIES  # noqa: E402


def test_dataset_is_well_formed_and_fictional():
    data = json.loads(run_evals.DATASET.read_text(encoding="utf-8"))
    assert len(data) == 30 and len({d["id"] for d in data}) == 30
    for d in data:
        assert d["expected"]["category"] in CATEGORIES and d["expected"]["urgency"] in URGENCIES
        assert isinstance(d["expected"]["needs_reply"], bool)
        assert ".test" in d["sender"] or "example" in d["sender"]  # reserved/fictional domains only
    assert {d["expected"]["category"] for d in data} == set(CATEGORIES)  # every class covered


def test_fake_eval_runs_cleanly_and_meets_thresholds():
    report = run_evals.evaluate("fake")
    assert report["provider"] == "fake" and report["n"] == 30 and report["failed_runs"] == 0
    thresholds = json.loads(gate.THRESHOLDS.read_text(encoding="utf-8"))["fake"]
    assert gate.check(report, thresholds) == []
    assert "do NOT measure model quality" in run_evals.render(report)  # honesty label present


def test_gate_flags_regressions():
    thresholds = {"min_accuracy": {"category": 0.9, "urgency": 0.7, "needs_reply": 0.8}, "max_failed_runs": 0}
    ok = {"accuracy": {"category": 0.95, "urgency": 0.8, "needs_reply": 0.9}, "failed_runs": 0}
    assert gate.check(ok, thresholds) == []
    bad = {"accuracy": {"category": 0.5, "urgency": 0.8, "needs_reply": 0.9}, "failed_runs": 2}
    problems = gate.check(bad, thresholds)
    assert len(problems) == 2 and "category" in problems[0] and "failed runs" in problems[1]
