#!/usr/bin/env python3
"""System One decision client: typed boolean/choice/score decisions from local open engines or hosted Jev.

Canonical wire (Jev-compatible): {"states": [{"id": str, "state": str|dict|list,
"questions": {qid: {"type": "boolean"|"noul"|"choice"|"score", "instructions": str, "criteria": ...}}}]}
"noul" is accepted as an alias for "boolean" and translated at engine boundaries.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import math
import os
import sys
import time
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_DIR / "config" / "engines.json"

CONFIG: dict = {}
ENGINES: dict = {}
PROFILES: dict = {}
_ACTIVE_CFG_PATH: str = str(DEFAULT_CONFIG)
_ENGINE_CACHE: dict = {}


def _resolve_paths(cfg: dict) -> dict:
    root = Path(os.environ.get("SYSTEMONE_MODELS_DIR") or cfg.get("models_dir") or "models")
    for eng in cfg.get("engines", {}).values():
        for key in ("repo_scripts", "checkpoint", "model_dir", "modeling", "repo", "backbone"):
            if key in eng:
                p = Path(eng[key])
                eng[key] = str(p if p.is_absolute() else root / p)
    return cfg


def load_config(path: str | os.PathLike | None = None) -> None:
    global CONFIG, ENGINES, PROFILES, _ACTIVE_CFG_PATH
    if path is None:
        path = os.environ.get("SYSTEMONE_CONFIG") or DEFAULT_CONFIG
    CONFIG = _resolve_paths(json.loads(Path(path).read_text(encoding="utf-8")))
    ENGINES = CONFIG["engines"]
    PROFILES = CONFIG["profiles"]
    _ACTIVE_CFG_PATH = str(Path(path).resolve())


@contextlib.contextmanager
def _scoped_config(path: str | os.PathLike):
    global CONFIG, ENGINES, PROFILES, _ACTIVE_CFG_PATH
    saved = (CONFIG, ENGINES, PROFILES, _ACTIVE_CFG_PATH)
    try:
        load_config(path)
        yield
    finally:
        CONFIG, ENGINES, PROFILES, _ACTIVE_CFG_PATH = saved


def clear_engine_cache() -> None:
    _ENGINE_CACHE.clear()


def validate_payload(payload: dict) -> list[dict]:
    if not isinstance(payload, dict) or set(payload) != {"states"}:
        raise ValueError('payload must be exactly {"states": [...]}')
    states = payload["states"]
    if not isinstance(states, list) or not states:
        raise ValueError("states must be a non-empty array")
    seen = set()
    for s in states:
        if not isinstance(s, dict) or set(s) != {"id", "state", "questions"}:
            raise ValueError("each state needs exactly id, state, questions")
        if not isinstance(s["id"], str) or not s["id"] or s["id"] in seen:
            raise ValueError("state ids must be unique non-empty strings")
        seen.add(s["id"])
        if not isinstance(s["state"], (str, dict, list)) or not s["state"]:
            raise ValueError("state must be non-empty string, object, or array")
        qs = s["questions"]
        if not isinstance(qs, dict) or not qs:
            raise ValueError("questions must be a non-empty object")
        for qid, q in qs.items():
            if not isinstance(qid, str) or not qid or not isinstance(q, dict):
                raise ValueError(f"question {qid!r} must map to an object")
            t = q.get("type")
            if t not in {"boolean", "noul", "choice", "score"} or not isinstance(q.get("instructions"), str) or not q["instructions"].strip():
                raise ValueError(f"{s['id']}:{qid} invalid type or instructions")
            c = q.get("criteria")
            if t in ("boolean", "noul"):
                if "criteria" in q and (not isinstance(c, dict) or set(c) - {"false", "true"}
                                        or not all(isinstance(v, str) and v for v in c.values())):
                    raise ValueError(f"{s['id']}:{qid} boolean criteria must be non-empty false/true entries")
            elif t == "choice":
                if not isinstance(c, dict) or not (2 <= len(c) <= 255) or not all(
                    isinstance(k, str) and k and isinstance(v, str) and v for k, v in c.items()
                ):
                    raise ValueError(f"{s['id']}:{qid} choice criteria must be 2-255 id->description pairs")
            else:
                if not isinstance(c, list) or not (2 <= len(c) <= 10) or not all(
                    isinstance(v, str) and v for v in c
                ):
                    raise ValueError(f"{s['id']}:{qid} score criteria must be 2-10 ordered strings")
    return states


def _normalize_types(payload: dict) -> dict:
    changed = False
    out_states = []
    for s in payload["states"]:
        qs = {}
        for qid, q in s["questions"].items():
            if q.get("type") == "noul":
                qs[qid] = {**q, "type": "boolean"}
                changed = True
            else:
                qs[qid] = q
        out_states.append({**s, "questions": qs})
    return {"states": out_states} if changed else payload


def _enforce_limits(limits: dict | None, states: list[dict], candidate_paths: int | None = None) -> None:
    if not limits:
        return
    if len(states) > limits.get("states", len(states)):
        raise ValueError(f"too many states: {len(states)} > {limits['states']}; split the batch")
    nq = sum(len(s["questions"]) for s in states)
    if nq > limits.get("questions", nq):
        raise ValueError(f"too many questions: {nq} > {limits['questions']}; split the batch")
    if candidate_paths is not None and candidate_paths > limits.get("candidate_paths", candidate_paths):
        raise ValueError(f"candidate paths {candidate_paths} exceed limit {limits['candidate_paths']}")
    for s in states:
        for qid, q in s["questions"].items():
            if q["type"] == "choice":
                n = len(q["criteria"])
                if n > limits.get("options", n):
                    raise ValueError(f"{s['id']}:{qid} has {n} options > limit {limits['options']}")


def boolean_fields(p_true: float) -> dict:
    p = min(max(float(p_true), 0.0), 1.0)
    return {"p_true": p, "value": p >= 0.5, "confidence": round(max(p, 1.0 - p), 4)}


def _check_temperature(t) -> float:
    if not isinstance(t, (int, float)) or isinstance(t, bool) or not math.isfinite(t) or t <= 0:
        raise ValueError("temperature must be a finite positive number")
    return float(t)


def non_latin_script_ratio(text: str) -> float:
    if not text:
        return 0.0
    sample = text[:4000]
    hits = 0
    for ch in sample:
        o = ord(ch)
        if (0x0400 <= o <= 0x04FF or 0x0500 <= o <= 0x052F or 0x0370 <= o <= 0x03FF
                or 0x0600 <= o <= 0x06FF or 0x0590 <= o <= 0x05FF
                or 0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF
                or 0x4E00 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF
                or 0x0900 <= o <= 0x097F or 0x0E00 <= o <= 0x0E7F):
            hits += 1
    return hits / len(sample)


def detect_cuda() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def resolve_profile(profile: str, state_text: str = "") -> dict:
    if profile == "auto":
        if non_latin_script_ratio(state_text) > 0.2:
            profile = "multilingual"
        else:
            profile = "gpu-en" if detect_cuda() else "cpu-en"
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; known: {sorted(PROFILES)}")
    spec = dict(PROFILES[profile])
    spec["profile"] = profile
    return spec


def route(confidence: float, act_gate: float, floor: float) -> str:
    if confidence >= act_gate:
        return "act"
    if confidence >= floor:
        return "review"
    return "default"


class NanoJevEngine:
    name = "nanojev"

    def __init__(self, device: str = "cpu", precision: str = "fp32"):
        cfg = ENGINES["nanojev"]
        repo = Path(cfg["repo_scripts"])
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from predict_toy_decisions import (  # type: ignore
            answer_from_probabilities,
            complete_question_batches,
            prepare_examples,
        )

        self._prepare = prepare_examples
        self._batches = complete_question_batches
        self._answer = answer_from_probabilities
        root = Path(cfg["checkpoint"])
        for need in ("config.json", "best.safetensors", "backbone_config", "tokenizer"):
            if not (root / need).exists():
                raise FileNotFoundError(f"nanojev checkpoint missing {need} in {root}")
        for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
            os.environ.setdefault(var, "1")
        import torch
        from safetensors.torch import load_file
        from transformers import AutoConfig, AutoModel, AutoTokenizer

        if device not in {"cpu", "cuda"} or (device == "cuda" and not torch.cuda.is_available()):
            raise ValueError(f"nanojev device {device!r} unavailable")
        if precision not in {"fp32", "bf16"}:
            raise ValueError("precision must be fp32 or bf16")
        if device == "cpu" and precision == "bf16":
            precision = "fp32"
        run_config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        if run_config.get("set_head") not in {"none", "attention"}:
            raise ValueError("checkpoint config lacks a valid set_head")
        tokenizer = AutoTokenizer.from_pretrained(str(root / "tokenizer"), local_files_only=True, trust_remote_code=False)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        body_config = AutoConfig.from_pretrained(str(root / "backbone_config"), local_files_only=True, trust_remote_code=False)
        body_config.use_cache = False
        self.limit = int(run_config.get("max_length", 512))
        body = AutoModel.from_config(body_config, attn_implementation="sdpa", trust_remote_code=False).float()
        spec = importlib.util.spec_from_file_location("nanojev_trainer_for_inference", repo / "train_toy_decisions.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        model = module.DecisionModel(body, run_config["set_head"])
        model.load_state_dict(load_file(str(root / "best.safetensors"), device="cpu"), strict=True)
        self._torch = torch
        self.device = torch.device(device)
        model.to(device=self.device, dtype=torch.float32)
        model.eval()
        self.model = model
        self.tokenizer = tokenizer
        self.precision = precision
        self.limits = cfg["limits"]
        self.calibrated = cfg["calibrated"]
        self.order_sensitive = cfg.get("order_sensitive", True)

    def predict(self, payload: dict, temperature: float = 1.0) -> dict:
        torch = self._torch
        temperature = _check_temperature(temperature)
        states = validate_payload(payload)
        payload = _normalize_types(payload)
        _enforce_limits(self.limits, states)
        examples = self._prepare(payload, self.tokenizer, self.limit)
        paths = sum(len(ex["leaf_tokens"]) for ex in examples)
        _enforce_limits(self.limits, states, candidate_paths=paths)
        batches = self._batches(examples, 0)
        outputs = {s["id"]: {"id": s["id"], "answers": {}} for s in states}
        with torch.inference_mode():
            for batch in batches:
                with torch.autocast("cuda", dtype=torch.bfloat16, enabled=self.precision == "bf16"):
                    logits, _ = self.model(batch, self.tokenizer.pad_token_id)
                for example, values in zip(batch, logits):
                    k = len(example["candidate_ids"])
                    scores = values[:k].float()
                    if not torch.isfinite(scores).all():
                        raise ValueError("non-finite logits")
                    probabilities = (scores / temperature).softmax(-1).cpu().tolist()
                    outputs[example["state_id"]]["answers"][example["qid"]] = self._answer(example, probabilities)
        return {
            "schema_version": "openjev-toy-inference-v1",
            "engine": self.name,
            "states": list(outputs.values()),
            "execution": {"device": str(self.device), "precision": self.precision, "forward_passes": len(batches)},
        }


class OpenJevNLIEngine:
    name = "openjev-nli"

    def __init__(self, device: str = "cpu"):
        import torch

        cfg = ENGINES["openjev-nli"]
        model_dir = Path(cfg["model_dir"])
        modeling = Path(cfg["modeling"])
        if not model_dir.exists() or not modeling.exists():
            raise FileNotFoundError(f"openjev model files missing under {model_dir.parent}")
        if str(modeling.parent) not in sys.path:
            sys.path.insert(0, str(modeling.parent))
        from modeling_openjev import OpenJevCrossEncoder  # type: ignore
        from transformers import AutoConfig, AutoModelForSequenceClassification, AutoTokenizer

        dev = device if device in {"cpu", "cuda"} else "cpu"
        if dev == "cuda" and not torch.cuda.is_available():
            dev = "cpu"
        self._torch = torch
        dtype = torch.float32 if dev == "cpu" else torch.bfloat16
        cfgx = AutoConfig.from_pretrained(str(model_dir))
        head = AutoModelForSequenceClassification.from_pretrained(
            str(model_dir), config=cfgx, dtype=dtype, ignore_mismatched_sizes=True
        )
        from safetensors import safe_open

        score_w = score_b = None
        for shard in sorted(model_dir.glob("model*.safetensors")):
            with safe_open(str(shard), framework="pt") as f:
                for k in f.keys():
                    if k == "score.weight" or k.endswith(".score.weight"):
                        score_w = f.get_tensor(k)
                    elif k == "score.bias" or k.endswith(".score.bias"):
                        score_b = f.get_tensor(k)
        if score_w is None:
            raise FileNotFoundError(f"checkpoint lacks score.weight in {model_dir}")
        hidden = head.config.get_text_config().hidden_size
        new_score = torch.nn.Linear(hidden, score_w.shape[0], bias=score_b is not None, dtype=dtype)
        with torch.no_grad():
            new_score.weight.copy_(score_w.to(dtype))
            if score_b is not None:
                new_score.bias.copy_(score_b.to(dtype))
        head.score = new_score
        head.to(dev).eval()

        enc = OpenJevCrossEncoder.__new__(OpenJevCrossEncoder)
        enc.tok = AutoTokenizer.from_pretrained(str(model_dir))
        if enc.tok.pad_token is None:
            enc.tok.pad_token = enc.tok.eos_token
        enc.tok.padding_side = "right"
        htc = head.config.get_text_config()
        if htc.pad_token_id is None:
            htc.pad_token_id = enc.tok.pad_token_id
        enc.device = dev
        enc.model = head
        enc.backbone = getattr(head, head.base_model_prefix)
        enc.template = getattr(head.config, "nli_template", None) or "Premise: {premise}\nHypothesis: {hypothesis}"
        enc.bs = 32
        enc.max_len = int(cfg["limits"].get("max_length", 4096))
        self.enc = enc
        self._fast_path = True
        self.limits = cfg["limits"]
        self.calibrated = cfg["calibrated"]
        self.order_sensitive = cfg.get("order_sensitive", False)

    def _score_hypotheses(self, premise: str, texts: list[str]):
        enc = self.enc
        if self._fast_path and getattr(enc, "predict_hypotheses", None) is not None:
            try:
                return enc.predict_hypotheses(premise, texts)
            except Exception:
                self._fast_path = False
        return enc.predict([(premise, t) for t in texts])

    def _normalize(self, q: dict) -> tuple[list[str], list[str]]:
        t = q["type"]
        if t == "boolean":
            labels = ["false", "true"]
            texts = [q.get("criteria", {}).get("false", "The proposition is false."),
                     q.get("criteria", {}).get("true", "The proposition is true.")]
        elif t == "choice":
            labels = list(q["criteria"])
            texts = [f"{k}: {q['criteria'][k]}" for k in labels]
        else:
            labels = [str(i) for i in range(len(q["criteria"]))]
            texts = list(q["criteria"])
        return labels, texts

    def predict(self, payload: dict, temperature: float = 1.0) -> dict:
        temperature = _check_temperature(temperature)
        states = validate_payload(payload)
        payload = _normalize_types(payload)
        _enforce_limits(self.limits, states)
        outputs = []
        for s in payload["states"]:
            premise = s["state"] if isinstance(s["state"], str) else json.dumps(s["state"], ensure_ascii=False)
            answers = {}
            for qid, q in s["questions"].items():
                labels, texts = self._normalize(q)
                probs = self._score_hypotheses(premise, texts)
                ent = [max(float(p[1]), 1e-12) for p in probs]
                if temperature != 1.0:
                    ent = [e ** (1.0 / temperature) for e in ent]
                total = math.fsum(ent) or 1.0
                dist = {lab: e / total for lab, e in zip(labels, ent)}
                best = max(dist, key=dist.get)
                out = {"type": q["type"], "probabilities": dist}
                if q["type"] == "boolean":
                    out.update(boolean_fields(dist["true"]))
                elif q["type"] == "choice":
                    out.update(choice=best, value=best, confidence=round(dist[best], 4))
                else:
                    score = math.fsum(i * p for i, p in enumerate(dist.values()))
                    out.update(score=score, level=int(best), value=score, confidence=round(max(dist.values()), 4))
                answers[qid] = out
            outputs.append({"id": s["id"], "answers": answers})
        return {"schema_version": "openjev-nli-v1", "engine": self.name, "states": outputs,
                "execution": {"device": str(self.enc.device)}}


class TypesafeHostedEngine:
    name = "typesafe"
    order_sensitive = False

    def __init__(self):
        endpoint = ENGINES["typesafe"]["endpoint"]
        base = os.environ.get("TYPESAFE_BASE_URL") or endpoint
        if base.endswith("/systemone"):
            self.url = base
        elif base.rstrip("/").endswith("/v1"):
            self.url = base.rstrip("/") + "/systemone"
        else:
            self.url = base.rstrip("/") + "/v1/systemone"
        self.model = ENGINES["typesafe"]["model"]
        self.api_key = os.environ.get("TYPESAFE_API_KEY")
        if not self.api_key:
            raise RuntimeError("TYPESAFE_API_KEY not set; hosted/multilingual profiles require it")
        self.limits = ENGINES["typesafe"]["limits"]
        self.calibrated = ENGINES["typesafe"]["calibrated"]

    def predict(self, payload: dict, temperature: float = 1.0) -> dict:
        _check_temperature(temperature)
        states = validate_payload(payload)
        payload = _normalize_types(payload)
        outputs = []
        for s in payload["states"]:
            questions = {}
            for qid, q in s["questions"].items():
                qq = dict(q)
                if qq["type"] == "boolean":
                    qq["type"] = "noul"
                questions[qid] = qq
            body = json.dumps({
                "model": self.model,
                "state": s["state"],
                "questions": questions,
            }).encode("utf-8")
            req = urllib.request.Request(
                self.url,
                data=body,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=CONFIG["options"]["timeout_seconds"]) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            answers = {}
            for qid, a in data.get("answers", {}).items():
                q = s["questions"].get(qid)
                if q is None:
                    continue
                qtype = q["type"]
                if qtype == "boolean":
                    p = float(a.get("noul", 0.0))
                    answers[qid] = {"type": qtype, "probabilities": {"false": 1.0 - p, "true": p}, **boolean_fields(p)}
                elif qtype == "choice":
                    conf = float(a.get("confidence", 0.0))
                    answers[qid] = {"type": qtype, "choice": a.get("choice"), "value": a.get("choice"),
                                    "probabilities": a.get("probabilities", {}), "confidence": conf}
                else:
                    answers[qid] = {"type": qtype, "score": a.get("score"), "value": a.get("score"),
                                    "probabilities": a.get("probabilities", {}), "confidence": a.get("confidence", 0.0)}
            outputs.append({"id": s["id"], "answers": answers})
        return {"schema_version": "typesafe-systemone-v1", "engine": self.name, "states": outputs,
                "execution": {"device": "remote"}}


def _make_engine(profile_spec: dict):
    name = profile_spec["engine"]
    if name == "nanojev":
        return NanoJevEngine(device=profile_spec.get("device", "cpu"), precision=profile_spec.get("precision", "fp32"))
    if name == "openjev-nli":
        return OpenJevNLIEngine(device=profile_spec.get("device", "cpu"))
    if name == "typesafe":
        return TypesafeHostedEngine()
    wire = ENGINES.get(name, {}).get("wire", "use its own CLI")
    raise ValueError(f"no in-process adapter for engine {name!r}; {wire}")


def build_engine(profile_spec: dict):
    key = (_ACTIVE_CFG_PATH, profile_spec["engine"], profile_spec.get("device", "cpu"), profile_spec.get("precision", "fp32"))
    if key not in _ENGINE_CACHE:
        _ENGINE_CACHE[key] = _make_engine(profile_spec)
    return _ENGINE_CACHE[key]


def _order_average_pass(engine, payload: dict, temperature: float) -> dict:
    min_opts = CONFIG["options"]["order_average_choice_min"]
    sub_states = []
    for s in payload["states"]:
        revs = {}
        for qid, q in s["questions"].items():
            if q["type"] == "choice" and len(q["criteria"]) >= min_opts:
                revs[qid] = {**q, "criteria": dict(reversed(list(q["criteria"].items())))}
        if revs:
            sub_states.append({"id": s["id"], "state": s["state"], "questions": revs})
    if not sub_states:
        return {}
    raw_rev = engine.predict({"states": sub_states}, temperature=temperature)
    out = {}
    for s in raw_rev["states"]:
        for qid, a in s["answers"].items():
            if a.get("probabilities"):
                out[(s["id"], qid)] = a["probabilities"]
    return out


def _finalize(raw: dict, payload: dict, spec: dict, engine, *, temperature: float) -> dict:
    rev_probs: dict = {}
    if getattr(engine, "order_sensitive", False):
        rev_probs = _order_average_pass(engine, payload, temperature)
    gate, floor = spec["act_gate"], CONFIG["routing"]["floor"]
    for s in raw["states"]:
        qmap = next(p["questions"] for p in payload["states"] if p["id"] == s["id"])
        for qid, a in s["answers"].items():
            a["order_averaged"] = False
            if a["type"] == "choice" and (s["id"], qid) in rev_probs and a.get("probabilities"):
                orig, rev = a["probabilities"], rev_probs[(s["id"], qid)]
                avg = {k: (orig.get(k, 0.0) + rev.get(k, 0.0)) / 2.0 for k in orig}
                a["probabilities"] = avg
                a["choice"] = a["value"] = max(avg, key=avg.get)
                a["confidence"] = round(max(avg.values()), 4)
                a["order_averaged"] = True
            if a["type"] == "boolean" and a.get("probabilities"):
                a.setdefault("p_true", a["probabilities"].get("true", 0.0))
                a.setdefault("value", a["p_true"] >= 0.5)
            conf = a.get("confidence")
            if conf is None and a.get("probabilities"):
                conf = max(a["probabilities"].values())
            if conf is None and a["type"] == "boolean" and "p_true" in a:
                conf = max(a["p_true"], 1.0 - a["p_true"])
            a["confidence"] = round(float(conf), 4) if conf is not None else None
            a["routing"] = route(a["confidence"], gate, floor) if a["confidence"] is not None else "review"
            _ = qmap[qid]
    return raw


def _decide_payload(payload: dict, profile: str, *, temperature: float | None = None) -> dict:
    states = validate_payload(payload)
    payload = _normalize_types(payload)
    first = states[0]["state"]
    text = first if isinstance(first, str) else json.dumps(first, ensure_ascii=False)
    spec = resolve_profile(profile, text)
    temp = 1.0 if temperature is None else _check_temperature(temperature)
    t0 = time.perf_counter()
    engine = build_engine(spec)
    load_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    raw = engine.predict(payload, temperature=temp)
    t2 = time.perf_counter()
    raw = _finalize(raw, payload, spec, engine, temperature=temp)
    t3 = time.perf_counter()
    predict_s = t2 - t1
    finalize_s = t3 - t2
    latency = predict_s + finalize_s
    return {
        "profile": spec["profile"],
        "engine": engine.name,
        "calibrated": getattr(engine, "calibrated", False),
        "load_seconds": round(load_s, 3),
        "predict_seconds": round(predict_s, 3),
        "finalize_seconds": round(finalize_s, 3),
        "latency_seconds": round(latency, 3),
        "total_seconds": round(load_s + latency, 3),
        "answers": raw["states"][0]["answers"],
        "states": raw["states"],
        "execution": raw.get("execution", {}),
    }


def decide(state, questions: dict, *, profile: str = "auto", config_path=None,
           state_id: str = "s1", temperature: float | None = None) -> dict:
    payload = {"states": [{"id": state_id, "state": state, "questions": questions}]}
    if config_path:
        with _scoped_config(config_path):
            return _decide_payload(payload, profile, temperature=temperature)
    return _decide_payload(payload, profile, temperature=temperature)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--payload", required=True, help="JSON file with a states array")
    p.add_argument("--profile", default="auto")
    p.add_argument("--config", default=None)
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--output", default=None)
    args = p.parse_args()
    try:
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        if args.config:
            load_config(args.config)
        result = _decide_payload(payload, args.profile, temperature=args.temperature)
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            Path(args.output).write_text(text + "\n", encoding="utf-8")
            print(json.dumps({"output": args.output, "engine": result["engine"],
                              "latency_seconds": result["latency_seconds"]}))
        else:
            print(text)
        return 0
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


load_config()

if __name__ == "__main__":
    raise SystemExit(main())
