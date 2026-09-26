"""DRF serializers for the HighSpeed showcase API."""
from __future__ import annotations

from rest_framework import serializers

from showcase.models import Decision, PolicyConfig, Record, ShowcaseRun


class RecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = Record
        fields = ["id", "ref", "payload", "ground_truth"]


class DecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Decision
        fields = ["id", "record", "run", "answers", "latency_ms", "engine", "profile", "device"]


class RunSerializer(serializers.ModelSerializer):
    progress = serializers.FloatField(read_only=True)

    class Meta:
        model = ShowcaseRun
        fields = ["id", "use_case", "status", "total", "done", "progress", "message", "error",
                  "decisions_per_second", "median_latency_ms", "agreement", "engine", "profile",
                  "device", "calibrated", "policy_version", "scope", "started_at", "finished_at"]


class PolicyConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolicyConfig
        fields = ["version", "is_active", "params", "note", "created_by", "created_at"]


class RecordWithDecisionSerializer(serializers.ModelSerializer):
    """Record + its latest decision answers (None when never decided)."""

    decision = serializers.SerializerMethodField()

    class Meta:
        model = Record
        fields = ["id", "ref", "payload", "ground_truth", "decision"]

    def get_decision(self, obj: Record) -> dict | None:
        decisions = getattr(obj, "prefetched_decisions", None)
        if decisions is None:
            d = obj.decisions.order_by("-id").first()
        else:
            d = decisions[0] if decisions else None
        if d is None:
            return None
        return {"run": d.run_id, "answers": d.answers, "latency_ms": d.latency_ms,
                "engine": d.engine, "profile": d.profile, "device": d.device}
