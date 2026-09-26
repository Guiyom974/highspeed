"""Warm-singleton access to the System One decision engine (backend/systemone_vendor).

The engine costs ~10-30 s to load, so it is loaded once per process and reused for every run.
GPU profiles fall back to CPU when CUDA is unavailable. Adapted from the proven FastKYC wrapper.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

log = logging.getLogger("showcase.engine")

_STATE: dict = {
    "status": "idle",
    "engine": None,
    "profile": None,
    "device": None,
    "precision": None,
    "calibrated": False,
    "error": None,
    "load_seconds": None,
    "loaded_at": None,
}
_LOCK = threading.RLock()
_sc = None
_POST_WARM = None

GPU_TO_CPU = {"gpu-nli": "cpu-nli", "gpu-en": "cpu-en"}


def _client():
    global _sc
    if _sc is not None:
        return _sc
    from django.conf import settings

    cfg = settings.SYSTEMONE
    scripts = cfg["SCRIPTS_DIR"]
    if not os.path.isdir(scripts):
        raise RuntimeError(f"system-one-triage scripts not found at {scripts}")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    os.environ.setdefault("SYSTEMONE_MODELS_DIR", cfg["MODELS_DIR"])
    import systemone_client as sc

    _sc = sc
    return sc


def set_post_warm_hook(fn) -> None:
    """Register a callable invoked once after a successful warm-up (used for auto-runs)."""
    global _POST_WARM
    _POST_WARM = fn


def requested_profile() -> str:
    from django.conf import settings

    return settings.SYSTEMONE["PROFILE"]


def resolved_profile() -> str:
    from django.conf import settings

    profile = requested_profile()
    cfg = settings.SYSTEMONE
    if profile in GPU_TO_CPU and cfg.get("CPU_FALLBACK", True):
        sc = _client()
        if not sc.detect_cuda():
            fallback = GPU_TO_CPU[profile]
            log.warning("CUDA unavailable; profile %s -> %s", profile, fallback)
            return fallback
    return profile


def warm(force: bool = False) -> dict:
    with _LOCK:
        if _STATE["status"] == "ready" and not force:
            return status()
        _STATE.update(status="loading", error=None)
    try:
        sc = _client()
        profile = resolved_profile()
        spec = sc.resolve_profile(profile)
        t0 = time.perf_counter()
        engine = sc.build_engine(spec)
        elapsed = time.perf_counter() - t0
        with _LOCK:
            _STATE.update(
                status="ready",
                engine=getattr(engine, "name", spec["engine"]),
                profile=profile,
                device=spec.get("device", "cpu"),
                precision=spec.get("precision"),
                calibrated=bool(getattr(engine, "calibrated", False)),
                load_seconds=round(elapsed, 2),
                loaded_at=time.time(),
                error=None,
            )
        log.info("engine ready: %s profile=%s device=%s load=%.1fs",
                 _STATE["engine"], profile, _STATE["device"], elapsed)
        hook = _POST_WARM
        if hook is not None:
            try:
                hook()
            except Exception:
                log.exception("post-warm hook failed")
    except Exception as exc:
        with _LOCK:
            _STATE.update(status="error", error=f"{type(exc).__name__}: {exc}")
        log.exception("engine warm-up failed")
    return status()


def warm_async() -> threading.Thread:
    t = threading.Thread(target=warm, name="systemone-warm", daemon=True)
    t.start()
    return t


def status() -> dict:
    with _LOCK:
        snap = dict(_STATE)
    snap["engine_ready"] = bool(snap.get("engine"))
    snap["requested_profile"] = requested_profile()
    return snap


def decide_many(states: list[dict], questions: dict, chunk: int = 8) -> list[dict]:
    """Batch multiple states per engine request, respecting caps (32 states / 96 questions).

    `states` items: {"id": str, "state": str}. Returns one dict per state:
    {"id", "answers", "wall_seconds" (batch wall time), "batch_size", "engine", "profile"}.
    """
    sc = _client()
    profile = resolved_profile()
    per_request = max(1, min(chunk, 32, 96 // max(1, len(questions))))
    spec = sc.resolve_profile(profile)
    engine = sc.build_engine(spec)
    out: list[dict] = []
    for i in range(0, len(states), per_request):
        batch = states[i:i + per_request]
        payload = {"states": [
            {"id": b["id"], "state": b["state"], "questions": questions} for b in batch
        ]}
        t0 = time.perf_counter()
        raw = engine.predict(payload)
        raw = sc._finalize(raw, payload, spec, engine, temperature=1.0)
        wall = time.perf_counter() - t0
        for st in raw["states"]:
            out.append({"id": st["id"], "answers": st["answers"], "wall_seconds": round(wall, 3),
                        "batch_size": len(batch), "engine": engine.name, "profile": profile})
    return out
