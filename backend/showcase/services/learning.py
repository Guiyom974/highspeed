"""Closed learning loop: decisions + labels -> fitted calibrators -> calibrated routing.

Three label sources feed one reliability fit per (use_case, question):
- designed synthetic ground truth (bulk labels the moment a run completes);
- human-in-the-loop Feedback rows posted from the UI (they override ground truth for that
  record/question — the mistake-correction signal leadership asked for);
- the fit itself is a monotone reliability map (binned, Laplace-smoothed, cumulative-max)
  plus a learned value bias: boolean p-shift, score level offset, choice correction map.

Applied at decision time (runner.py) when policy.learning.apply_calibration is on:
calibrated confidence drives act/review/fallback gates and the learned bias corrects
values — so the system self-corrects from its own mistakes instead of replaying them.
`suggest_params()` turns measured miscalibration into a concrete gates.act_gate proposal
that leadership applies as a new policy version (learning -> parametric customization).
`export_dataset()` emits the JSONL SFT/LoRA dataset for fine-tuning the engine itself.

Honest-metrics doctrine: every number returned here is measured against designed or
human labels and labelled with its source; calibrators are identity below MIN_SAMPLES.
"""
from __future__ import annotations

import json
import logging
from collections import Counter

from django.utils import timezone as dj_timezone

from showcase.models import Calibration, Decision, Feedback, Record
from showcase.services import registry

log = logging.getLogger("showcase.learning")

MIN_SAMPLES = 10
BINS = [(0.0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 0.95), (0.95, 1.01)]
HISTORY_CAP = 20

_CACHE: dict[str, Calibration | None] = {}


def scope_key(use_case: str, question_id: str) -> str:
    return f"{use_case}:{question_id}"


def clear_cache(scope: str | None = None) -> None:
    if scope is None:
        _CACHE.clear()
    else:
        _CACHE.pop(scope, None)


def _matches(qtype: str, truth, answer: dict) -> bool | None:
    from showcase.services.runner import matches

    return matches(qtype, truth, answer)


def _p_true(answer: dict) -> float | None:
    p = answer.get("p_true")
    if isinstance(p, (int, float)):
        return float(p)
    value = answer.get("value")
    conf = answer.get("confidence")
    if isinstance(value, bool) and isinstance(conf, (int, float)):
        return float(conf) if value else 1.0 - float(conf)
    return None


def _level_of(answer: dict) -> int | None:
    level = answer.get("level")
    if level is None:
        try:
            level = int(round(float(answer.get("value", 0))))
        except (TypeError, ValueError):
            return None
    try:
        return int(level)
    except (TypeError, ValueError):
        return None


def training_rows(use_case: str, question_id: str) -> list[dict]:
    """Labelled pairs for one question: human feedback first, designed truth otherwise."""
    uc = registry.get(use_case)
    q = uc["questions"].get(question_id)
    if q is None:
        return []
    tkey = uc["truth_map"].get(question_id)
    rows: list[dict] = []
    records = Record.objects.filter(use_case=use_case).prefetch_related(
        "decisions", "feedback")
    feedback_by_record: dict[int, Feedback] = {}
    for fb in Feedback.objects.filter(question_id=question_id,
                                       record__use_case=use_case).order_by("-id"):
        feedback_by_record.setdefault(fb.record_id, fb)
    for rec in records:
        decisions = list(rec.decisions.all())
        if not decisions:
            continue
        answer = decisions[-1].answers.get(question_id)
        if not answer:
            continue
        fb = feedback_by_record.get(rec.pk)
        if fb is not None:
            label, source = fb.human_value, "manual"
        elif tkey and tkey in rec.ground_truth:
            label, source = rec.ground_truth[tkey], "ground_truth"
        else:
            continue
        if q["type"] == "boolean":
            label = bool(label)
        elif q["type"] == "score":
            try:
                label = int(label)
            except (TypeError, ValueError):
                continue
        correct = _matches(q["type"], label, answer)
        if correct is None:
            continue
        conf = answer.get("confidence")
        rows.append({
            "confidence": float(conf) if isinstance(conf, (int, float)) else 0.5,
            "correct": bool(correct),
            "label": label,
            "model_value": answer.get("value"),
            "p_true": _p_true(answer),
            "level": _level_of(answer),
            "source": source,
        })
    return rows


def _interp(conf: float, bins: list[dict]) -> float:
    """Piecewise-linear calibrated accuracy for a raw confidence."""
    usable = [b for b in bins if b["n"] > 0]
    if not usable:
        return conf
    points = [((b["lo"] + min(b["hi"], 1.0)) / 2.0, b["acc"]) for b in usable]
    points.sort()
    if conf <= points[0][0]:
        return points[0][1]
    if conf >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= conf <= x1:
            if x1 == x0:
                return y1
            t = (conf - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return points[-1][1]


def fit(use_case: str, question_id: str) -> Calibration | None:
    """Fit the reliability map + value bias for one (use_case, question)."""
    uc = registry.get(use_case)
    q = uc["questions"].get(question_id)
    if q is None:
        return None
    rows = training_rows(use_case, question_id)
    scope = scope_key(use_case, question_id)
    cal, _ = Calibration.objects.get_or_create(
        scope=scope, defaults={"use_case": use_case, "question_id": question_id,
                               "question_type": q["type"]})
    cal.question_type = q["type"]
    cal.n_samples = len(rows)
    cal.n_human = sum(1 for r in rows if r["source"] == "manual")

    if len(rows) < MIN_SAMPLES:
        cal.fitted = False
        cal.bins, cal.bias = [], {}
        cal.accuracy_raw = cal.accuracy_calibrated = None
        cal.ece_raw = cal.ece_calibrated = None
        cal.fitted_at = None
        cal.save(update_fields=["question_type", "n_samples", "n_human", "bins", "bias",
                                "accuracy_raw", "accuracy_calibrated", "ece_raw",
                                "ece_calibrated", "fitted", "fitted_at"])
        clear_cache(scope)
        return cal

    counts = [0] * len(BINS)
    corrects = [0] * len(BINS)
    conf_sums = [0.0] * len(BINS)

    def bin_index(conf: float) -> int:
        for i, (lo, hi) in enumerate(BINS):
            if lo <= conf < hi:
                return i
        return len(BINS) - 1

    for r in rows:
        i = bin_index(r["confidence"])
        counts[i] += 1
        corrects[i] += int(r["correct"])
        conf_sums[i] += r["confidence"]

    bins: list[dict] = []
    running_max = 0.0
    for (lo, hi), n, c in zip(BINS, counts, corrects):
        acc = (c + 1) / (n + 2) if n else None          # Laplace-smoothed
        if acc is not None:
            running_max = max(running_max, acc)          # monotone (cumulative max)
        bins.append({
            "lo": lo, "hi": hi, "n": n,
            "acc": round(running_max, 4) if n else None,
            "emp": round(c / n, 4) if n else None,
            "mean_conf": round(conf_sums[i] / n, 4) if n else None,
        })
    total = len(rows)
    ece_raw = sum(counts[i] / total * abs((bins[i]["emp"] or 0.0) - (bins[i]["mean_conf"] or 0.0))
                  for i in range(len(BINS)) if counts[i])
    ece_cal = sum(counts[i] / total * abs((bins[i]["emp"] or 0.0) - (bins[i]["acc"] or 0.0))
                  for i in range(len(BINS)) if counts[i])

    accuracy_raw = sum(1 for r in rows if r["correct"]) / total

    bias: dict = {}
    if q["type"] == "boolean":
        shifts = [((1.0 if r["label"] else 0.0) - r["p_true"])
                  for r in rows if r["p_true"] is not None]
        if shifts:
            bias["p_shift"] = round(sum(shifts) / len(shifts), 4)
    elif q["type"] == "score":
        offsets = [r["label"] - r["level"] for r in rows
                   if r["level"] is not None and isinstance(r["label"], int)]
        if offsets:
            bias["score_offset"] = round(sum(offsets) / len(offsets), 4)
    elif q["type"] == "choice":
        pairs = Counter()
        for r in rows:
            if str(r["model_value"]) != str(r["label"]):
                pairs[(str(r["model_value"]), str(r["label"]))] += 1
        choice_map: dict[str, str] = {}
        for (model_v, label_v), n in pairs.items():
            same_model = sum(c for (m, _l), c in pairs.items() if m == model_v)
            if n >= 5 and n / same_model >= 0.6:
                choice_map[model_v] = label_v
        if choice_map:
            bias["choice_map"] = choice_map

    now = dj_timezone.now()
    cal.bins = [{k: v for k, v in b.items() if k not in ("emp", "mean_conf")} for b in bins]
    cal.bias = bias
    cal.accuracy_raw = round(accuracy_raw, 4)
    cal.ece_raw = round(ece_raw, 4)
    cal.ece_calibrated = round(ece_cal, 4)
    cal.accuracy_calibrated = round(
        sum(b["acc"] * b["n"] for b in bins if b["acc"] is not None) / total, 4)
    cal.fitted = True
    cal.fitted_at = now
    history = list(cal.history or [])
    history.append({"at": now.isoformat(), "n": total,
                    "ece_raw": cal.ece_raw, "ece_calibrated": cal.ece_calibrated})
    cal.history = history[-HISTORY_CAP:]
    cal.save()
    clear_cache(scope)
    return cal


def fit_all(use_case: str | None = None) -> int:
    """(Re)fit every question that has decisions. Returns the number fitted."""
    keys = [use_case] if use_case else list(registry.USE_CASE_ORDER)
    fitted = 0
    for key in keys:
        uc = registry.get(key)
        for qid in uc["questions"]:
            cal = fit(key, qid)
            if cal is not None and cal.fitted:
                fitted += 1
    log.info("calibration refit complete: %d fitted scope(s)%s",
             fitted, f" for {use_case}" if use_case else "")
    return fitted


def _load(scope: str) -> Calibration | None:
    if scope in _CACHE:
        return _CACHE[scope]
    cal = Calibration.objects.filter(scope=scope).first()
    loaded = cal if (cal is not None and cal.fitted) else None
    _CACHE[scope] = loaded
    return loaded


def calibrate(use_case: str, question_id: str, answer: dict,
              apply_bias: bool = True) -> dict:
    """Return {'confidence_calibrated', 'p_true_calibrated', 'value', 'level', 'adjustment'}.

    Identity (empty dict) until a calibrator is fitted — raw engine output passes through
    untouched, so defaults preserve the original showcase numbers exactly.
    """
    cal = _load(scope_key(use_case, question_id))
    if cal is None or not apply_bias:
        return {}
    out: dict = {}
    conf = answer.get("confidence")
    if isinstance(conf, (int, float)) and cal.bins:
        out["confidence_calibrated"] = round(_interp(float(conf), cal.bins), 4)
    bias = cal.bias or {}
    qtype = cal.question_type

    if qtype == "boolean" and "p_shift" in bias:
        p = answer.get("p_true")
        if isinstance(p, (int, float)):
            p_new = min(0.99, max(0.01, float(p) + float(bias["p_shift"])))
            out["p_true_calibrated"] = round(p_new, 4)
            old_value = bool(answer.get("value"))
            new_value = p_new >= 0.5
            if new_value != old_value:
                out["value"] = new_value
                out["adjustment"] = (f"boolean corrected {old_value}->{new_value} "
                                     f"(p {float(p):.2f}->{p_new:.2f}, "
                                     f"learned shift {bias['p_shift']:+.2f}, n={cal.n_samples})")
    elif qtype == "score" and "score_offset" in bias:
        level = _level_of(answer)
        if level is not None:
            levels = len(registry.get(use_case)["questions"][question_id]["criteria"])
            new_level = min(levels - 1, max(0, int(round(level + float(bias["score_offset"])))))
            if new_level != level:
                out["level"] = new_level
                out["value"] = float(new_level)
                out["score"] = float(new_level)
                out["adjustment"] = (f"score corrected {level}->{new_level} "
                                     f"(learned offset {bias['score_offset']:+.2f}, "
                                     f"n={cal.n_samples})")
    elif qtype == "choice" and bias.get("choice_map"):
        value = str(answer.get("value"))
        mapped = bias["choice_map"].get(value)
        if mapped and mapped != value:
            out["value"] = mapped
            out["choice"] = mapped
            out["adjustment"] = (f"choice corrected '{value}'->'{mapped}' "
                                 f"(n={cal.n_samples})")
    return out


def metrics(use_case: str | None = None) -> dict:
    """Calibration + feedback state for the Governance learning panel."""
    cals = Calibration.objects.all()
    feedback_count = Feedback.objects.count()
    if use_case:
        cals = cals.filter(use_case=use_case)
        feedback_count = Feedback.objects.filter(record__use_case=use_case).count()
    per_scope = []
    for cal in cals:
        per_scope.append({
            "scope": cal.scope, "use_case": cal.use_case,
            "question_id": cal.question_id, "question_type": cal.question_type,
            "n_samples": cal.n_samples, "n_human": cal.n_human,
            "fitted": cal.fitted, "bins": cal.bins, "bias": cal.bias,
            "accuracy_raw": cal.accuracy_raw,
            "accuracy_calibrated": cal.accuracy_calibrated,
            "ece_raw": cal.ece_raw, "ece_calibrated": cal.ece_calibrated,
            "fitted_at": cal.fitted_at.isoformat() if cal.fitted_at else None,
            "history": cal.history,
        })
    by_use_case: dict[str, dict] = {}
    for row in per_scope:
        agg = by_use_case.setdefault(row["use_case"], {"use_case": row["use_case"],
                                                       "questions": 0, "fitted": 0,
                                                       "n_samples": 0, "n_human": 0,
                                                       "ece_raw": [], "ece_calibrated": []})
        agg["questions"] += 1
        agg["fitted"] += int(row["fitted"])
        agg["n_samples"] += row["n_samples"]
        agg["n_human"] += row["n_human"]
        if row["ece_raw"] is not None:
            agg["ece_raw"].append(row["ece_raw"])
        if row["ece_calibrated"] is not None:
            agg["ece_calibrated"].append(row["ece_calibrated"])
    for agg in by_use_case.values():
        agg["ece_raw"] = round(sum(agg["ece_raw"]) / len(agg["ece_raw"]), 4) if agg["ece_raw"] else None
        agg["ece_calibrated"] = (round(sum(agg["ece_calibrated"]) / len(agg["ece_calibrated"]), 4)
                                 if agg["ece_calibrated"] else None)
    recent = Feedback.objects.order_by("-id")[:20]
    return {
        "min_samples": MIN_SAMPLES,
        "feedback_count": feedback_count,
        "scopes": per_scope,
        "by_use_case": list(by_use_case.values()),
        "recent_feedback": [_feedback_row(f) for f in recent],
    }


def _feedback_row(f: Feedback) -> dict:
    return {"id": f.id, "record": f.record_id, "use_case": f.record.use_case,
            "ref": f.record.ref, "question_id": f.question_id,
            "model_value": f.model_value, "model_confidence": f.model_confidence,
            "human_value": f.human_value, "source": f.source, "actor": f.actor,
            "note": f.note, "created_at": f.created_at.isoformat()}


def record_feedback(record: Record, question_id: str, human_value, actor: str = "",
                    note: str = "", model_answer: dict | None = None) -> Feedback:
    """Store a human label for one (record, question) and refit its calibrator."""
    answer = model_answer
    if answer is None:
        decisions = list(record.decisions.all())
        answer = (decisions[-1].answers.get(question_id) if decisions else None) or {}
    fb = Feedback.objects.create(
        record=record, question_id=question_id,
        model_value=answer.get("value"),
        model_confidence=(float(answer["confidence"])
                          if isinstance(answer.get("confidence"), (int, float)) else None),
        human_value=human_value, source="manual", actor=actor[:64], note=note[:255],
    )
    clear_cache(scope_key(record.use_case, question_id))
    fit(record.use_case, question_id)
    return fb


def suggest_params(target: float | None = None) -> dict:
    """Turn measured reliability into a concrete gates.act_gate proposal.

    Pooled accuracy over bins at/above a candidate boundary must reach `target`
    (policy learning.act_target_precision, default 0.90) with n >= 15 across fitted
    scopes; the smallest such boundary above the current gate is proposed. When even
    the top band misses the target, no gate raise is proposed and the reason is stated —
    that scope stays review-only, honestly reported.
    """
    from showcase.services import policy as policy_service

    _version, params = policy_service.active()
    current = float(params["gates"]["act_gate"])
    target = float(target if target is not None
                    else params.get("learning", {}).get("act_target_precision", 0.90))
    fitted = [c for c in Calibration.objects.filter(fitted=True)]
    if not fitted:
        return {"suggestions": [], "basis": {"fitted_scopes": 0, "target": target,
                                             "current_act_gate": current}}

    boundaries = sorted({b["lo"] for c in fitted for b in c.bins
                         if b["n"] > 0 and b["lo"] >= current})
    suggestion = None
    basis: dict = {"target": target, "current_act_gate": current,
                   "fitted_scopes": len(fitted), "evaluated": []}
    best_with_data = None
    for b in boundaries:
        pooled_n = 0
        pooled_correct = 0.0
        for c in fitted:
            for bin_ in c.bins:
                if bin_["n"] and bin_["lo"] >= b and bin_["acc"] is not None:
                    pooled_n += bin_["n"]
                    pooled_correct += bin_["acc"] * bin_["n"]
        acc = (pooled_correct / pooled_n) if pooled_n else None
        entry = {"boundary": b, "n": pooled_n,
                 "pooled_accuracy": round(acc, 4) if acc is not None else None}
        basis["evaluated"].append(entry)
        if pooled_n:
            best_with_data = entry
        if pooled_n >= 15 and acc is not None and acc >= target and b > current:
            suggestion = round(b, 2)
            break
    if suggestion is not None:
        last = basis["evaluated"][-1]
        return {"suggestions": [{
            "param": "gates.act_gate", "current": current, "suggested": suggestion,
            "rationale": (f"pooled accuracy at/above {suggestion:.2f} is >= target "
                          f"{target:.2f} over {last['n']} labelled pairs "
                          f"({len(fitted)} fitted scope(s))"),
            "n": last["n"],
        }], "basis": basis}
    if best_with_data is None:
        reason = "not enough labelled pairs at/above the current gate"
    else:
        reason = (f"no boundary reaches target {target:.2f} — the highest-confidence band "
                  f"pooled at {best_with_data['pooled_accuracy']} over "
                  f"n={best_with_data['n']}")
    return {"suggestions": [], "basis": {**basis, "reason": reason}}


def export_dataset() -> list[dict]:
    """JSONL-able rows: the SFT/LoRA fine-tuning dataset for the System One engine."""
    out: list[dict] = []
    for fb in Feedback.objects.select_related("record").order_by("id"):
        out.append({
            "use_case": fb.record.use_case, "record_ref": fb.record.ref,
            "question_id": fb.question_id, "model_value": fb.model_value,
            "model_confidence": fb.model_confidence, "label": fb.human_value,
            "label_source": fb.source, "actor": fb.actor, "created_at": fb.created_at.isoformat(),
        })
    for rec in Record.objects.prefetch_related("decisions").order_by("id"):
        decisions = list(rec.decisions.all())
        if not decisions:
            continue
        answers = decisions[-1].answers
        for qid, answer in answers.items():
            try:
                uc = registry.get(rec.use_case)
            except KeyError:
                continue
            tkey = uc["truth_map"].get(qid)
            if not tkey or tkey not in rec.ground_truth:
                continue
            out.append({
                "use_case": rec.use_case, "record_ref": rec.ref, "question_id": qid,
                "model_value": answer.get("value"),
                "model_confidence": answer.get("confidence"),
                "label": rec.ground_truth[tkey], "label_source": "ground_truth",
                "actor": "", "created_at": decisions[-1].created_at.isoformat(),
            })
    return out


def export_jsonl() -> str:
    return "\n".join(json.dumps(row, default=str) for row in export_dataset()) + "\n"
