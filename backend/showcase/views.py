"""HighSpeed REST API + static SPA serving (single port, open local showcase).

Governance note: write endpoints are gated by the `X-Role` advisory header (compliance/
admin for policy, analyst+ for human labels) and, when the `FASTHS_GOVERNANCE_KEY` env
var is set, a matching `X-Governance-Key` on policy writes. This is a local showcase
without user accounts — production deployments must put these routes behind real
authentication/RBAC (FastKYC ships the reference implementation).
"""
from __future__ import annotations

import csv
import mimetypes
import os
import random
import statistics
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Prefetch
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from rest_framework import status as http_status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from showcase.models import Decision, Feedback, PolicyConfig, Record, ShowcaseRun
from showcase.serializers import PolicyConfigSerializer, RecordWithDecisionSerializer, RunSerializer
from showcase.services import datasets, engine, jobs, learning, policy, registry

INDEX_HTML = settings.FRONTEND_DIST / "index.html"
ASSET_DIR = settings.FRONTEND_DIST / "assets"


def spa_index(_request):
    if not INDEX_HTML.exists():
        return HttpResponse(
            "<h1>HighSpeed</h1><p>Frontend bundle not built yet.</p>"
            "<p>Run <code>launcher.bat</code>, or build manually: "
            "<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code></p>"
            "<p>API is live at <a href='/api/stats'>/api/stats</a>.</p>",
            content_type="text/html; charset=utf-8",
        )
    return HttpResponse(INDEX_HTML.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")


def spa_asset(_request, path: str):
    target = (ASSET_DIR / path).resolve()
    if not target.is_relative_to(ASSET_DIR.resolve()) or not target.is_file():
        raise Http404("asset not found")
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target.open("rb"), content_type=content_type)


# ---------------------------------------------------------------------------
# Governance request helpers (advisory role header + optional shared key)
# ---------------------------------------------------------------------------

def _role(request) -> str:
    role = (request.headers.get("X-Role") or "viewer").strip().lower()
    return role if role in policy.ALL_ROLES else "viewer"


def _actor(request) -> str:
    return (request.headers.get("X-Actor") or "").strip()[:64]


def _write_denied(request) -> Response | None:
    if _role(request) not in policy.WRITE_ROLES:
        return Response({"error": "compliance or admin role required "
                                  "(send X-Role: compliance|admin)"},
                        status=http_status.HTTP_403_FORBIDDEN)
    gate_key = os.environ.get("FASTHS_GOVERNANCE_KEY", "")
    if gate_key and request.headers.get("X-Governance-Key", "") != gate_key:
        return Response({"error": "missing or invalid X-Governance-Key header"},
                        status=http_status.HTTP_403_FORBIDDEN)
    return None


def _analysis_denied(request) -> Response | None:
    if _role(request) not in policy.ANALYSIS_ROLES:
        return Response({"error": "analyst, compliance or admin role required "
                                  "(send X-Role: analyst|compliance|admin)"},
                        status=http_status.HTTP_403_FORBIDDEN)
    return None


@api_view(["GET"])
def health(_request):
    return Response({"status": "ok", "service": "HighSpeed", "time": timezone.now().isoformat(),
                     "engine": engine.status()["status"]})


@api_view(["GET"])
def engine_status(_request):
    return Response(engine.status())


def _use_case_summary(key: str) -> dict:
    uc = registry.get(key)
    record_count = Record.objects.filter(use_case=key).count()
    decision_count = Decision.objects.filter(record__use_case=key).count()
    last_run = ShowcaseRun.objects.filter(use_case=key).order_by("-id").first()
    agreement = (last_run.agreement if last_run and last_run.agreement else None)
    mean_agree = (round(statistics.mean(v["agree"] for v in agreement.values()), 4)
                  if agreement else None)
    return {
        "key": key,
        "name": uc["name"],
        "industry": uc["industry"],
        "monogram": uc["monogram"],
        "pattern": uc["pattern"],
        "blurb": uc["blurb"],
        "disclaimer": uc.get("disclaimer", ""),
        "question_count": len(uc["questions"]),
        "question_types": sorted({q["type"] for q in uc["questions"].values()}),
        "record_count": record_count,
        "decision_count": decision_count,
        "last_run": RunSerializer(last_run).data if last_run else None,
        "mean_agreement": mean_agree,
    }


class StatsView(APIView):
    def get(self, _request):
        summaries = [_use_case_summary(k) for k in registry.USE_CASE_ORDER]
        done_runs = ShowcaseRun.objects.filter(status="done")
        latencies = [v for v in Decision.objects.values_list("latency_ms", flat=True) if v]
        total_records = Record.objects.count()
        total_decisions = Decision.objects.count()
        questions_total = sum(len(registry.get(k)["questions"]) for k in registry.USE_CASE_ORDER)
        total_answers = sum(s["decision_count"] * len(registry.get(s["key"])["questions"])
                            for s in summaries)
        running = jobs.latest(kind_running_only=True)
        policy_version, policy_params = policy.active()
        return Response({
            "use_case_count": len(summaries),
            "total_records": total_records,
            "total_decisions": total_decisions,
            "total_answers": total_answers,
            "questions_per_record": round(questions_total / max(1, len(summaries)), 1),
            "median_latency_ms": round(statistics.median(latencies), 1) if latencies else None,
            "mean_latency_ms": round(statistics.mean(latencies), 1) if latencies else None,
            "best_throughput": round(max((r.decisions_per_second for r in done_runs
                                          if r.decisions_per_second), default=0), 3) or None,
            "runs_completed": done_runs.count(),
            "engine": engine.status(),
            "running": RunSerializer(running).data if running else None,
            "busy": jobs.is_busy(),
            "policy": {"version": policy_version, **policy.describe(policy_params)},
            "use_cases": summaries,
        })


class UseCaseListView(APIView):
    def get(self, _request):
        return Response([_use_case_summary(k) for k in registry.USE_CASE_ORDER])


class UseCaseDetailView(APIView):
    def get(self, _request, key: str):
        try:
            uc = registry.get(key)
        except KeyError:
            raise Http404("unknown use case")
        records = (Record.objects.filter(use_case=key)
                   .prefetch_related(Prefetch("decisions", queryset=Decision.objects.order_by("-id"),
                                              to_attr="prefetched_decisions"))
                   .order_by("id"))
        runs = ShowcaseRun.objects.filter(use_case=key).order_by("-id")[:10]
        return Response({
            "summary": _use_case_summary(key),
            "questions": uc["questions"],
            "truth_map": uc["truth_map"],
            "display_fields": uc["display_fields"],
            "primary_field": uc["primary_field"],
            "records": RecordWithDecisionSerializer(records, many=True).data,
            "runs": RunSerializer(runs, many=True).data,
        })


class RunUseCaseView(APIView):
    def post(self, request, key: str):
        try:
            registry.get(key)
        except KeyError:
            raise Http404("unknown use case")
        limit = request.data.get("limit")
        try:
            limit = int(limit) if limit else None
        except (TypeError, ValueError):
            return Response({"error": "limit must be an integer"},
                            status=http_status.HTTP_400_BAD_REQUEST)
        if jobs.is_busy():
            return Response({"error": "a run is already active — wait for it to finish"},
                            status=http_status.HTTP_409_CONFLICT)
        try:
            run = jobs.start_run(key, limit)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=http_status.HTTP_409_CONFLICT)
        return Response(RunSerializer(run).data, status=http_status.HTTP_202_ACCEPTED)


class RunAllView(APIView):
    def post(self, _request):
        if jobs.is_busy():
            return Response({"error": "a run is already active — wait for it to finish"},
                            status=http_status.HTTP_409_CONFLICT)
        try:
            runs = jobs.start_run_all()
        except ValueError as exc:
            return Response({"error": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=http_status.HTTP_409_CONFLICT)
        return Response({"started": len(runs), "runs": RunSerializer(runs, many=True).data},
                        status=http_status.HTTP_202_ACCEPTED)


class RunView(APIView):
    def get(self, _request, pk: int):
        run = ShowcaseRun.objects.filter(pk=pk).first()
        if not run:
            raise Http404("run not found")
        return Response(RunSerializer(run).data)


class LatestRunView(APIView):
    def get(self, request):
        key = request.query_params.get("use_case")
        running_only = request.query_params.get("running") == "1"
        run = jobs.latest(key, kind_running_only=running_only)
        if not run:
            return Response({})
        return Response(RunSerializer(run).data)


class ReseedView(APIView):
    """Regenerate all synthetic datasets (no engine needed). Wipes records/decisions/runs."""

    def post(self, request):
        try:
            seed = int(request.data.get("seed", 20260926))
        except (TypeError, ValueError):
            return Response({"error": "seed must be an integer"},
                            status=http_status.HTTP_400_BAD_REQUEST)
        if jobs.is_busy():
            return Response({"error": "a run is active — wait for it to finish before reseeding"},
                            status=http_status.HTTP_409_CONFLICT)
        Decision.objects.all().delete()
        ShowcaseRun.objects.all().delete()
        Record.objects.all().delete()
        rng = random.Random(seed)
        created = 0
        for key in registry.USE_CASE_ORDER:
            uc = registry.get(key)
            rows = uc["generate"](rng, uc["count"])
            Record.objects.bulk_create([
                Record(use_case=key, ref=r["ref"], payload=r["payload"],
                       ground_truth=r["ground_truth"]) for r in rows
            ])
            created += len(rows)
        return Response({"reseeded": True, "seed": seed, "records": created,
                         "use_cases": len(registry.USE_CASE_ORDER)},
                        status=http_status.HTTP_201_CREATED)


class ExportCsvView(APIView):
    """Decisions export for one use case: record fields, ground truth and typed answers."""

    def get(self, _request, key: str):
        try:
            uc = registry.get(key)
        except KeyError:
            raise Http404("unknown use case")
        qids = list(uc["questions"])
        display_fields = [(f, lbl) for f, lbl in uc["display_fields"]
                          if f != uc["primary_field"]]
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="highspeed-{key}.csv"'
        writer = csv.writer(response)
        header = ["ref"]
        for field, _label in display_fields:
            header.append(field)
        header.append(uc["primary_field"])
        for qid in qids:
            header += [f"{qid}_value", f"{qid}_confidence", f"{qid}_confidence_calibrated",
                       f"{qid}_routing", f"{qid}_truth", f"{qid}_match"]
        header += ["latency_ms", "engine", "profile", "device", "run_id"]
        writer.writerow(header)

        records = (Record.objects.filter(use_case=key)
                   .prefetch_related(Prefetch("decisions", queryset=Decision.objects.order_by("-id"),
                                              to_attr="prefetched_decisions"))
                   .order_by("id"))
        from showcase.services.runner import matches

        for rec in records:
            d = rec.prefetched_decisions[0] if rec.prefetched_decisions else None
            answers = d.answers if d else {}
            row = [rec.ref]
            for field, _label in display_fields:
                row.append(rec.payload.get(field, ""))
            row.append(str(rec.payload.get(uc["primary_field"], ""))[:400])
            for qid in qids:
                a = answers.get(qid) or {}
                truth_key = uc["truth_map"].get(qid)
                truth = rec.ground_truth.get(truth_key) if truth_key else None
                match = matches(uc["questions"][qid]["type"], truth, a) if a else None
                row += [a.get("value", ""), a.get("confidence", ""),
                        a.get("confidence_calibrated", ""),
                        a.get("routing", ""),
                        "" if truth is None else truth,
                        "" if match is None else ("yes" if match else "no")]
            row += [d.latency_ms if d else "", d.engine if d else "", d.profile if d else "",
                    d.device if d else "", d.run_id if d else ""]
            writer.writerow(row)
        return response


# ---------------------------------------------------------------------------
# Governance policy (leadership/compliance parameters)
# ---------------------------------------------------------------------------

class PolicyView(APIView):
    def get(self, _request):
        cfg = PolicyConfig.objects.filter(is_active=True).order_by("-version").first()
        if cfg is None:
            cfg = policy.ensure_v1()
        versions = PolicyConfigSerializer(PolicyConfig.objects.all()[:25], many=True).data
        _, params = policy.active()
        return Response({"active": PolicyConfigSerializer(cfg).data, "versions": versions,
                         "merged": params, "write_roles": sorted(policy.WRITE_ROLES),
                         "governance_key_required": bool(os.environ.get("FASTHS_GOVERNANCE_KEY", ""))})

    def post(self, request):
        denied = _write_denied(request)
        if denied:
            return denied
        try:
            params = policy.validate_params(request.data.get("params"))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        note = str(request.data.get("note", ""))[:256]
        actor = _actor(request) or "governance"
        with transaction.atomic():
            PolicyConfig.objects.all().update(is_active=False)
            cfg = PolicyConfig.objects.create(version=policy.next_version(), is_active=True,
                                              params=params, note=note, created_by=actor)
        policy.invalidate()
        return Response(PolicyConfigSerializer(cfg).data, status=http_status.HTTP_201_CREATED)


class PolicyActivateView(APIView):
    def post(self, request, version: int):
        denied = _write_denied(request)
        if denied:
            return denied
        cfg = PolicyConfig.objects.filter(version=version).first()
        if not cfg:
            raise Http404("policy version not found")
        with transaction.atomic():
            PolicyConfig.objects.exclude(pk=cfg.pk).update(is_active=False)
            cfg.is_active = True
            cfg.save(update_fields=["is_active"])
        policy.invalidate()
        return Response(PolicyConfigSerializer(cfg).data)


# ---------------------------------------------------------------------------
# HITL feedback (human labels) + learning loop
# ---------------------------------------------------------------------------

class FeedbackView(APIView):
    def get(self, request):
        qs = Feedback.objects.select_related("record").order_by("-id")
        use_case = request.query_params.get("use_case")
        if use_case:
            qs = qs.filter(record__use_case=use_case)
        rows = qs[:200]
        return Response({"count": qs.count(), "results": [learning._feedback_row(f) for f in rows]})

    def post(self, request):
        denied = _analysis_denied(request)
        if denied:
            return denied
        record = Record.objects.filter(pk=request.data.get("record_id")).first()
        if not record:
            raise Http404("record not found")
        question_id = str(request.data.get("question_id", ""))
        uc = registry.get(record.use_case)
        q = uc["questions"].get(question_id)
        if q is None:
            return Response({"error": f"unknown question '{question_id}' for {record.use_case}"},
                            status=http_status.HTTP_400_BAD_REQUEST)
        value = request.data.get("value")
        if q["type"] == "boolean":
            if not isinstance(value, bool):
                return Response({"error": "value must be a boolean"},
                                status=http_status.HTTP_400_BAD_REQUEST)
        elif q["type"] == "choice":
            if str(value) not in q["criteria"]:
                return Response({"error": f"value must be one of {list(q['criteria'])}"},
                                status=http_status.HTTP_400_BAD_REQUEST)
            value = str(value)
        elif q["type"] == "score":
            try:
                value = int(value)
            except (TypeError, ValueError):
                return Response({"error": "value must be an integer level"},
                                status=http_status.HTTP_400_BAD_REQUEST)
            if not 0 <= value < len(q["criteria"]):
                return Response({"error": f"level must be 0..{len(q['criteria']) - 1}"},
                                status=http_status.HTTP_400_BAD_REQUEST)
        actor = (_actor(request) or str(request.data.get("actor", "")).strip()[:64]
                 or "human")
        fb = learning.record_feedback(
            record, question_id, value, actor=actor,
            note=str(request.data.get("note", ""))[:255])
        scope = learning.scope_key(record.use_case, question_id)
        from showcase.models import Calibration

        cal = Calibration.objects.filter(scope=scope).first()
        return Response({
            "feedback": learning._feedback_row(fb),
            "calibration": {
                "scope": scope,
                "fitted": bool(cal and cal.fitted),
                "n_samples": cal.n_samples if cal else 0,
                "ece_raw": cal.ece_raw if cal else None,
                "ece_calibrated": cal.ece_calibrated if cal else None,
                "bias": cal.bias if cal else {},
            },
        }, status=http_status.HTTP_201_CREATED)


class LearningView(APIView):
    def get(self, request):
        use_case = request.query_params.get("use_case")
        version, params = policy.active()
        data = learning.metrics(use_case)
        data["policy_version"] = version
        data["gates"] = params["gates"]
        data["apply_calibration"] = bool(params["learning"]["apply_calibration"])
        data["suggestions"] = learning.suggest_params()
        data["export_url"] = "/api/learning/export"
        return Response(data)


class LearningRefitView(APIView):
    def post(self, request):
        denied = _write_denied(request)
        if denied:
            return denied
        use_case = request.data.get("use_case")
        if use_case and use_case not in registry.USE_CASES:
            return Response({"error": f"unknown use case '{use_case}'"},
                            status=http_status.HTTP_400_BAD_REQUEST)
        fitted = learning.fit_all(use_case)
        return Response({"fitted": fitted, "metrics": learning.metrics(use_case)})


class LearningApplyView(APIView):
    """Promote a learning suggestion (or an explicit patch) to a new policy version."""

    def post(self, request):
        denied = _write_denied(request)
        if denied:
            return denied
        _, current = policy.active()
        patch = request.data.get("params")
        merged = policy.merge_params(current)
        if patch:
            if not isinstance(patch, dict):
                return Response({"error": "params must be an object"},
                                status=http_status.HTTP_400_BAD_REQUEST)
            for section, value in patch.items():
                if section in merged and isinstance(merged[section], dict) and isinstance(value, dict):
                    merged[section].update(value)
                elif section in merged:
                    merged[section] = value
        else:
            suggestions = learning.suggest_params().get("suggestions") or []
            if not suggestions:
                return Response({"error": "no suggestion to apply"},
                                status=http_status.HTTP_400_BAD_REQUEST)
            for s in suggestions:
                section, _, key = s["param"].partition(".")
                if section in merged and isinstance(merged[section], dict):
                    merged[section][key] = s["suggested"]
        try:
            params = policy.validate_params(merged)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        note = str(request.data.get("note", ""))[:256] or "learning auto-tune"
        with transaction.atomic():
            PolicyConfig.objects.all().update(is_active=False)
            cfg = PolicyConfig.objects.create(version=policy.next_version(), is_active=True,
                                              params=params, note=note,
                                              created_by=_actor(request) or "learning")
        policy.invalidate()
        return Response(PolicyConfigSerializer(cfg).data, status=http_status.HTTP_201_CREATED)


class LearningExportView(APIView):
    def get(self, _request):
        body = learning.export_jsonl()
        response = HttpResponse(body, content_type="application/x-ndjson; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="highspeed-finetune-dataset.jsonl"'
        return response
