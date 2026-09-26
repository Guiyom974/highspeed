"""Batched decision runner: states -> warm engine -> persisted Decisions + agreement metrics.

Honest-metrics doctrine (inherited from FastKYC):
- per-record latency is the *amortized* batch wall time (batch_size states share one predict call);
- agreement is measured against the *designed* synthetic ground truth — indicative, not a benchmark;
- local engines are uncalibrated: confidence is raw softmax; the act gate is 0.90.
After the engine answers, the active governance policy is applied per record: match criteria
(scope), materiality band, and fitted calibration from services/learning.py (calibrated
confidence drives routing; learned bias corrects values). With default policy and no fitted
calibrators this is an identity pass — original numbers reproduce exactly.
"""
from __future__ import annotations

import logging
import statistics
import time

from django.utils import timezone

from showcase.models import Decision, Record, ShowcaseRun
from showcase.services import engine, learning, policy, registry

log = logging.getLogger("showcase.runner")


def _batch_size(n_questions: int) -> int:
    """States per engine request: respect 32-state / 96-question caps, keep progress granular."""
    return max(1, min(16, 32, 96 // max(1, n_questions)))


def matches(qtype: str, truth, answer: dict, strict: bool = False) -> bool | None:
    """Per-question agreement between the typed answer and the designed ground truth.

    Scores use ±1-level tolerance by default (standard for ordinal scales); `strict=True`
    demands the exact level. Strict matters: with 3 levels, a constant mid-level predictor
    scores 100% under tolerance and 0% strict — both numbers are reported everywhere.
    """
    if truth is None:
        return None
    if qtype == "boolean":
        return bool(answer.get("value")) == bool(truth)
    if qtype == "choice":
        return str(answer.get("value")) == str(truth)
    if qtype == "score":
        level = answer.get("level")
        if level is None:
            try:
                level = int(round(float(answer.get("value", 0))))
            except (TypeError, ValueError):
                return None
        try:
            diff = abs(int(level) - int(truth))
        except (TypeError, ValueError):
            return None
        return diff == 0 if strict else diff <= 1
    return None


def compute_agreement(questions: dict, truth_map: dict, pairs: list[tuple[dict, dict]]) -> dict:
    """pairs = [(ground_truth, answers)]; returns per-question tolerant AND strict agreement."""
    out: dict[str, dict] = {}
    for qid, q in questions.items():
        tkey = truth_map.get(qid)
        if tkey is None:
            continue
        matched = matched_strict = total = 0
        levels_used: set = set()
        for truth, answers in pairs:
            if tkey not in truth or qid not in answers:
                continue
            answer = answers[qid]
            if q["type"] == "score":
                levels_used.add(answer.get("level"))
            result = matches(q["type"], truth[tkey], answer)
            result_strict = matches(q["type"], truth[tkey], answer, strict=True)
            if result is None:
                continue
            total += 1
            matched += int(result)
            matched_strict += int(result_strict or 0)
        if total:
            entry = {"type": q["type"], "matched": matched, "total": total,
                     "agree": round(matched / total, 4),
                     "agree_strict": round(matched_strict / total, 4)}
            if q["type"] == "score":
                entry["levels_used"] = len(levels_used)
            out[qid] = entry
    return out


def apply_governance(key: str, params: dict, record: Record, answers: dict,
                     counters: dict) -> None:
    """Apply match criteria, materiality and fitted calibration to one record's answers.

    Mutates `answers` in place: calibrated confidence/value, final routing label, and
    (only when something fired) a `scope_note` explaining the routing to a human reader.
    """
    uc = registry.get(key)
    text = policy.searchable_text(record.payload, uc["display_fields"], uc["primary_field"])
    scope = policy.evaluate_criteria(record.payload, text, params["criteria"])
    mat = policy.evaluate_materiality(record.payload, params["materiality"])
    apply_calibration = bool(params.get("learning", {}).get("apply_calibration", True))

    if scope["in_scope"] is False:
        counters["excluded"] += 1
    elif mat["material"] is False:
        counters["below_materiality"] += 1
    elif mat["force_review"]:
        counters["forced_review"] += 1

    note = ""
    if scope["in_scope"] is False:
        note = f"excluded: {scope['detail']}"
    elif mat["material"] is False:
        note = f"below materiality: {mat['detail']}"
    elif mat["force_review"]:
        note = f"materiality forces review: {mat['detail']}"

    for qid, answer in answers.items():
        cal = learning.calibrate(key, qid, answer,
                                 apply_bias=apply_calibration) if apply_calibration else {}
        if cal:
            counters["calibrated"] += 1
            for field in ("confidence_calibrated", "p_true_calibrated", "value",
                          "level", "score", "choice", "adjustment"):
                if field in cal:
                    answer[field] = cal[field]
            if "adjustment" in cal:
                counters["adjusted"] += 1
        conf = answer.get("confidence_calibrated")
        if not isinstance(conf, (int, float)):
            conf = answer.get("confidence")
        answer["routing"] = policy.routing_for(
            float(conf) if isinstance(conf, (int, float)) else None,
            params["gates"], scope, mat)
        if note:
            answer["scope_note"] = note


def run_use_case(run: ShowcaseRun, key: str, limit: int | None = None) -> ShowcaseRun:
    """Execute one use case synchronously (called inside a worker thread). Mutates `run`."""
    uc = registry.get(key)
    questions = uc["questions"]
    state_text = uc["state_text"]

    records = list(Record.objects.filter(use_case=key).order_by("id"))
    if limit:
        records = records[:limit]
    run.total = len(records)
    run.message = f"warming engine" if engine.status()["status"] != "ready" else "queued"
    run.status = "running"
    run.save(update_fields=["total", "message", "status"])

    if not records:
        run.status = "error"
        run.error = f"no records for '{key}' — seed the demo data first"
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at"])
        return run

    warm = engine.warm()
    if warm["status"] != "ready":
        run.status = "error"
        run.error = f"engine unavailable: {warm.get('error') or warm.get('status')}"
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at"])
        return run

    # A fresh run replaces prior decisions for this use case (demo semantics).
    Decision.objects.filter(record__use_case=key).delete()

    batch = _batch_size(len(questions))
    latencies: list[float] = []
    pairs: list[tuple[dict, dict]] = []
    policy_version, base_params = policy.active()
    params = policy.params_for(key, base_params)
    counters = {"excluded": 0, "below_materiality": 0, "forced_review": 0,
                "calibrated": 0, "adjusted": 0}
    t_start = time.perf_counter()
    created: list[Decision] = []

    for i in range(0, len(records), batch):
        chunk = records[i:i + batch]
        states = [{"id": str(r.id), "state": state_text(r.payload)} for r in chunk]
        results = engine.decide_many(states, questions, chunk=len(chunk))
        by_id = {res["id"]: res for res in results}
        amortized_ms = None
        for r in chunk:
            res = by_id.get(str(r.id))
            if res is None:
                continue
            apply_governance(key, params, r, res["answers"], counters)
            wall = float(res.get("wall_seconds") or 0.0)
            amortized_ms = round(wall * 1000 / max(1, int(res.get("batch_size") or len(chunk))), 1)
            latencies.append(amortized_ms)
            created.append(Decision(
                record=r, run=run, answers=res["answers"], latency_ms=amortized_ms,
                engine=res.get("engine", ""), profile=res.get("profile", ""),
                device=engine.status().get("device") or "",
            ))
            pairs.append((r.ground_truth, res["answers"]))
        Decision.objects.bulk_create(created)
        created = []
        run.done = min(run.total, i + len(chunk))
        run.message = f"decided {run.done}/{run.total} ({uc['name']})"
        run.save(update_fields=["done", "message"])

    elapsed = time.perf_counter() - t_start
    snap = engine.status()
    run.status = "done"
    run.decisions_per_second = round(len(records) / elapsed, 3) if elapsed > 0 else None
    run.median_latency_ms = round(statistics.median(latencies), 1) if latencies else None
    run.agreement = compute_agreement(questions, uc["truth_map"], pairs)
    run.engine = snap.get("engine") or ""
    run.profile = snap.get("profile") or ""
    run.device = snap.get("device") or ""
    run.calibrated = bool(snap.get("calibrated"))
    run.policy_version = policy_version
    run.scope = counters
    scope_bits = [f"{counters[k]} {k.replace('_', ' ')}"
                  for k in ("excluded", "below_materiality", "forced_review", "adjusted")
                  if counters[k]]
    run.message = (f"{len(records)} records · {sum(len(q) for q in [questions]) * len(records)} typed answers "
                   f"in {elapsed:.1f}s ({run.decisions_per_second}/s)"
                   + (" · " + ", ".join(scope_bits) if scope_bits else ""))
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "decisions_per_second", "median_latency_ms", "agreement",
                            "engine", "profile", "device", "calibrated", "policy_version",
                            "scope", "message", "finished_at"])
    log.info("run %s (%s) done: %s", run.id, key, run.message)
    return run
