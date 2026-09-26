"""Governance policy: versioned, parametric search/match criteria + materiality + gates.

Leadership/compliance tune these through the Governance API without a redeploy; every run
stamps the version it used. Three layers, applied per record before routing is decided:

- `criteria`  — search/match scope: must-contain / must-not-contain terms (substring or
  fuzzy similarity) over the record's searchable text. Out-of-scope records are answered
  but routed `excluded` so they never enter a human queue.
- `materiality` — leadership's value floor/ceiling on a payload field: below `min_amount`
  the item is not material (routing `auto_dispose`); at/above `review_amount` a human must
  see it regardless of model confidence (routing forced to `review`).
- `gates`     — act/review confidence gates applied to *calibrated* confidence
  (see services/learning.py), not raw softmax.

Per-use-case overrides live under `params["use_cases"][key]` and deep-merge over the
global sections. Defaults preserve the original showcase behaviour exactly: criteria and
materiality disabled, gates at 0.90/0.50 (the engine's own defaults).
"""
from __future__ import annotations

import copy
import difflib
import re
import threading

from django.conf import settings

DEFAULT_POLICY_PARAMS: dict = {
    "gates": {"act_gate": 0.90, "floor": 0.50},
    "criteria": {
        "enabled": False,
        "match_mode": "any",          # "any" | "all" for must_contain terms
        "must_contain": [],
        "must_not_contain": [],
        "fuzzy": False,               # substring match when False, similarity when True
        "min_similarity": 0.85,       # 0..1, used when fuzzy
    },
    "materiality": {
        "enabled": False,
        "field": "",                  # numeric payload field
        "min_amount": 0.0,            # below -> not material (auto_dispose)
        "review_amount": 0.0,         # >= (when > 0) -> force human review
    },
    "learning": {
        "apply_calibration": True,
        "act_target_precision": 0.90,  # suggestion target for gates.act_gate
    },
    "use_cases": {},                  # {key: {gates?, criteria?, materiality?, enabled?}}
}

WRITE_ROLES = {"compliance", "admin"}
ANALYSIS_ROLES = {"analyst", "compliance", "admin"}
ALL_ROLES = {"viewer", "analyst", "compliance", "admin"}


def bootstrap_params() -> dict:
    """Defaults with env overrides (used to create version 1 and as a fallback)."""
    params = copy.deepcopy(DEFAULT_POLICY_PARAMS)
    env = getattr(settings, "SYSTEMONE", {})
    if "ACT_GATE" in env:
        params["gates"]["act_gate"] = float(env["ACT_GATE"])
    if "FLOOR" in env:
        params["gates"]["floor"] = float(env["FLOOR"])
    return params


_CACHE: dict = {"version": None, "params": None}
_LOCK = threading.Lock()


def invalidate() -> None:
    with _LOCK:
        _CACHE.update(version=None, params=None)


def active() -> tuple[int, dict]:
    """(version, params) of the active policy config, cached per process."""
    with _LOCK:
        if _CACHE["params"] is not None:
            return _CACHE["version"], _CACHE["params"]
    from showcase.models import PolicyConfig

    cfg = PolicyConfig.objects.filter(is_active=True).order_by("-version").first()
    if cfg is None:
        cfg = ensure_v1()
    params = merge_params(cfg.params)
    with _LOCK:
        _CACHE.update(version=cfg.version, params=params)
    return cfg.version, params


def ensure_v1(created_by: str = "") -> "PolicyConfig":  # noqa: F821
    """Idempotently create and activate version 1 from bootstrap defaults."""
    from showcase.models import PolicyConfig

    with _LOCK:
        _CACHE.update(version=None, params=None)
    cfg = PolicyConfig.objects.filter(version=1).first()
    if cfg is None:
        cfg = PolicyConfig.objects.create(version=1, params=bootstrap_params(),
                                          note="bootstrap defaults", created_by=created_by)
    if not PolicyConfig.objects.filter(is_active=True).exists():
        PolicyConfig.objects.all().update(is_active=False)
        cfg.is_active = True
        cfg.save(update_fields=["is_active"])
    return cfg


def next_version() -> int:
    from showcase.models import PolicyConfig

    latest = PolicyConfig.objects.order_by("-version").values_list("version", flat=True).first()
    return (latest or 0) + 1


def merge_params(incoming: dict | None) -> dict:
    """Deep-merge incoming params over the defaults so missing keys always resolve."""
    merged = copy.deepcopy(DEFAULT_POLICY_PARAMS)
    if not incoming:
        return merged
    for section, value in incoming.items():
        if section == "use_cases" and isinstance(value, dict):
            for key, override in value.items():
                merged["use_cases"][key] = _merge_override(override)
            continue
        if section not in merged:
            continue
        if isinstance(merged[section], dict) and isinstance(value, dict):
            for k, v in value.items():
                if k in merged[section]:
                    merged[section][k] = v
        else:
            merged[section] = value
    return merged


def _merge_override(override: dict | None) -> dict:
    out: dict = {}
    if not isinstance(override, dict):
        return out
    for section in ("gates", "criteria", "materiality"):
        if isinstance(override.get(section), dict):
            base = copy.deepcopy(DEFAULT_POLICY_PARAMS[section])
            for k, v in override[section].items():
                if k in base:
                    base[k] = v
            out[section] = base
    return out


def params_for(use_case: str, params: dict | None = None) -> dict:
    """Global params with the per-use-case override deep-merged on top."""
    p = copy.deepcopy(params if params is not None else active()[1])
    override = (p.get("use_cases") or {}).get(use_case)
    if not override:
        return p
    for section in ("gates", "criteria", "materiality"):
        if section in override and isinstance(override[section], dict):
            p[section].update(override[section])
    return p


def validate_params(params: dict) -> dict:
    """Validate + normalise a submitted params dict. Raises ValueError with a readable message."""
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    merged = merge_params(params)

    def num(section: str, key: str, lo: float, hi: float, integer: bool = False):
        raw = merged[section][key]
        try:
            value = int(raw) if integer else float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{section}.{key} must be a number, got {raw!r}")
        if not (lo <= value <= hi):
            raise ValueError(f"{section}.{key} must be between {lo} and {hi}, got {value}")
        merged[section][key] = value

    num("gates", "act_gate", 0.0, 1.0)
    num("gates", "floor", 0.0, 1.0)
    if merged["gates"]["floor"] > merged["gates"]["act_gate"]:
        raise ValueError("gates.floor must not exceed gates.act_gate")

    crit = merged["criteria"]
    if crit["match_mode"] not in ("any", "all"):
        raise ValueError("criteria.match_mode must be 'any' or 'all'")
    for key in ("must_contain", "must_not_contain"):
        raw = crit[key]
        if not isinstance(raw, list) or any(not isinstance(t, str) for t in raw):
            raise ValueError(f"criteria.{key} must be a list of strings")
        if len(raw) > 50:
            raise ValueError(f"criteria.{key} accepts at most 50 terms")
        crit[key] = [t.strip()[:64] for t in raw if t.strip()]
    crit["enabled"] = bool(crit["enabled"])
    crit["fuzzy"] = bool(crit["fuzzy"])
    num("criteria", "min_similarity", 0.0, 1.0)

    mat = merged["materiality"]
    mat["enabled"] = bool(mat["enabled"])
    if not isinstance(mat["field"], str):
        raise ValueError("materiality.field must be a string")
    mat["field"] = mat["field"].strip()[:48]
    num("materiality", "min_amount", 0.0, 1e12)
    num("materiality", "review_amount", 0.0, 1e12)
    if mat["review_amount"] and mat["review_amount"] < mat["min_amount"]:
        raise ValueError("materiality.review_amount must be >= min_amount (or 0 to disable)")

    learn = merged["learning"]
    learn["apply_calibration"] = bool(learn["apply_calibration"])
    num("learning", "act_target_precision", 0.5, 1.0)

    if not isinstance(merged["use_cases"], dict):
        raise ValueError("use_cases must be an object keyed by use-case key")
    for key, override in merged["use_cases"].items():
        if not isinstance(override, dict):
            raise ValueError(f"use_cases.{key} must be an object")
        if "gates" in override:
            g = override["gates"]
            for gk in ("act_gate", "floor"):
                if gk in g:
                    try:
                        g[gk] = float(g[gk])
                    except (TypeError, ValueError):
                        raise ValueError(f"use_cases.{key}.gates.{gk} must be a number")
                    if not 0.0 <= g[gk] <= 1.0:
                        raise ValueError(f"use_cases.{key}.gates.{gk} must be between 0 and 1")
            if "floor" in g and "act_gate" in g and g["floor"] > g["act_gate"]:
                raise ValueError(f"use_cases.{key}: gates.floor must not exceed act_gate")
        if "criteria" in override:
            sub = copy.deepcopy(DEFAULT_POLICY_PARAMS["criteria"])
            sub.update({k: v for k, v in override["criteria"].items() if k in sub})
            if sub["match_mode"] not in ("any", "all"):
                raise ValueError(f"use_cases.{key}.criteria.match_mode must be 'any' or 'all'")
            for ck in ("must_contain", "must_not_contain"):
                if not isinstance(sub[ck], list) or any(not isinstance(t, str) for t in sub[ck]):
                    raise ValueError(f"use_cases.{key}.criteria.{ck} must be a list of strings")
                if len(sub[ck]) > 50:
                    raise ValueError(f"use_cases.{key}.criteria.{ck} accepts at most 50 terms")
                sub[ck] = [t.strip()[:64] for t in sub[ck] if t.strip()]
            if not 0.0 <= float(sub["min_similarity"]) <= 1.0:
                raise ValueError(f"use_cases.{key}.criteria.min_similarity must be 0..1")
            override["criteria"] = sub
        if "materiality" in override:
            m = override["materiality"]
            for mk in ("min_amount", "review_amount"):
                if mk in m:
                    try:
                        m[mk] = float(m[mk])
                    except (TypeError, ValueError):
                        raise ValueError(f"use_cases.{key}.materiality.{mk} must be a number")
                    if m[mk] < 0:
                        raise ValueError(f"use_cases.{key}.materiality.{mk} must be >= 0")
    return merged


def searchable_text(payload: dict, display_fields: list | None = None,
                    primary_field: str = "") -> str:
    """Lowercased text the match criteria run against (primary + display field values)."""
    parts: list[str] = []
    if primary_field and isinstance(payload.get(primary_field), str):
        parts.append(payload[primary_field])
    for field, _label in display_fields or []:
        value = payload.get(field)
        if isinstance(value, str):
            parts.append(value)
    for value in payload.values():
        if isinstance(value, str) and value not in parts:
            parts.append(value)
    return " ".join(parts).lower()


def _similarity(term: str, text: str) -> float:
    if not term:
        return 0.0
    if term in text:
        return 1.0
    return difflib.SequenceMatcher(None, term, text).ratio()


def evaluate_criteria(payload: dict, text: str, criteria: dict) -> dict:
    """Decide whether a record is in scope. Returns {in_scope, reason, detail}."""
    if not criteria.get("enabled"):
        return {"in_scope": True, "reason": "", "detail": ""}
    hay = text or searchable_text(payload)
    fuzzy = bool(criteria.get("fuzzy"))
    threshold = float(criteria.get("min_similarity", 0.85))

    for term in criteria.get("must_not_contain") or []:
        t = term.lower()
        hit = (_similarity(t, hay) >= threshold) if fuzzy else (t in hay)
        if hit:
            return {"in_scope": False, "reason": "excluded",
                    "detail": f"must_not_contain matched '{term}'"}

    must = [t.lower() for t in (criteria.get("must_contain") or [])]
    if must:
        if fuzzy:
            hits = [t for t in must if _similarity(t, hay) >= threshold]
        else:
            hits = [t for t in must if t in hay]
        mode = criteria.get("match_mode", "any")
        ok = bool(hits) if mode == "any" else len(hits) == len(must)
        if not ok:
            matched = ", ".join(f"'{h}'" for h in hits) or "none"
            return {"in_scope": False, "reason": "excluded",
                    "detail": f"must_contain ({mode}) matched {matched}"}
    return {"in_scope": True, "reason": "", "detail": ""}


def evaluate_materiality(payload: dict, materiality: dict) -> dict:
    """Classify a record against leadership's materiality band.

    Returns {material: bool, amount: float|None, force_review: bool, reason, detail}.
    Non-numeric or missing fields are materiality-neutral (never auto-disposed).
    """
    if not materiality.get("enabled") or not materiality.get("field"):
        return {"material": True, "amount": None, "force_review": False,
                "reason": "", "detail": ""}
    raw = payload.get(materiality["field"])
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return {"material": True, "amount": None, "force_review": False,
                "reason": "", "detail": f"field '{materiality['field']}' not numeric"}
    min_amount = float(materiality.get("min_amount") or 0.0)
    review_amount = float(materiality.get("review_amount") or 0.0)
    if amount < min_amount:
        return {"material": False, "amount": amount, "force_review": False,
                "reason": "below_materiality",
                "detail": f"{materiality['field']} {amount:g} < min {min_amount:g}"}
    if review_amount and amount >= review_amount:
        return {"material": True, "amount": amount, "force_review": True,
                "reason": "review_amount",
                "detail": f"{materiality['field']} {amount:g} >= review {review_amount:g}"}
    return {"material": True, "amount": amount, "force_review": False,
            "reason": "", "detail": ""}


def routing_for(calibrated_confidence: float | None, gates: dict,
                scope: dict, materiality: dict) -> str:
    """Final routing label for one answer: scope -> materiality -> confidence gates."""
    if scope.get("in_scope") is False:
        return "excluded"
    if materiality.get("material") is False:
        return "auto_dispose"
    if materiality.get("force_review"):
        return "review"
    conf = calibrated_confidence
    if conf is None:
        return "review"
    if conf >= float(gates["act_gate"]):
        return "act"
    if conf >= float(gates["floor"]):
        return "review"
    return "fallback"


def describe(params: dict) -> dict:
    """Compact policy summary for stats/UI."""
    crit = params["criteria"]
    mat = params["materiality"]
    return {
        "gates": params["gates"],
        "criteria_enabled": bool(crit["enabled"]),
        "materiality_enabled": bool(mat["enabled"]),
        "use_case_overrides": len(params.get("use_cases") or {}),
        "apply_calibration": bool(params["learning"]["apply_calibration"]),
    }
