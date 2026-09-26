"""Showcase models: synthetic records, batched runs, per-record decisions,
versioned governance policy, human-in-the-loop feedback and calibration state."""
from __future__ import annotations

from django.db import models
from django.utils import timezone


class Record(models.Model):
    """One synthetic item of a use-case dataset (ticket, email, review, log line, ...)."""

    use_case = models.CharField(max_length=32, db_index=True)
    ref = models.CharField(max_length=32)
    payload = models.JSONField(default=dict)
    ground_truth = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["use_case", "ref"], name="uniq_uc_ref")]
        indexes = [models.Index(fields=["use_case", "id"])]

    def __str__(self) -> str:
        return f"{self.use_case}:{self.ref}"


class ShowcaseRun(models.Model):
    """A (background) batch decision run over one use case, with live progress."""

    STATUSES = [("pending", "Pending"), ("running", "Running"), ("done", "Done"), ("error", "Error")]

    use_case = models.CharField(max_length=32, db_index=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="pending")
    total = models.PositiveIntegerField(default=0)
    done = models.PositiveIntegerField(default=0)
    message = models.CharField(max_length=256, blank=True, default="")
    error = models.TextField(blank=True, default="")
    decisions_per_second = models.FloatField(null=True, blank=True)
    median_latency_ms = models.FloatField(null=True, blank=True)
    agreement = models.JSONField(default=dict, blank=True)
    engine = models.CharField(max_length=32, blank=True, default="")
    profile = models.CharField(max_length=24, blank=True, default="")
    device = models.CharField(max_length=16, blank=True, default="")
    calibrated = models.BooleanField(default=False)
    policy_version = models.PositiveIntegerField(default=0)
    scope = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["use_case", "-id"])]

    @property
    def progress(self) -> float:
        return round(self.done / self.total, 4) if self.total else 0.0

    def __str__(self) -> str:
        return f"{self.use_case} {self.status} {self.done}/{self.total}"


class Decision(models.Model):
    """Typed answers for one record from one run — the replayable audit unit."""

    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="decisions")
    run = models.ForeignKey(ShowcaseRun, on_delete=models.CASCADE, related_name="decisions")
    answers = models.JSONField(default=dict)
    latency_ms = models.FloatField(null=True, blank=True)
    engine = models.CharField(max_length=32, blank=True, default="")
    profile = models.CharField(max_length=24, blank=True, default="")
    device = models.CharField(max_length=16, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["record", "-id"]), models.Index(fields=["run"])]

    def __str__(self) -> str:
        return f"decision {self.record_id} run={self.run_id}"


class PolicyConfig(models.Model):
    """Immutable, versioned governance parameters (gates, match criteria, materiality).

    Leadership/compliance edit these through the Governance API; every run stamps the
    version it executed under so an auditor can reconstruct which policy produced which
    routing. Editing creates a new version; activating an older version is the rollback.
    """

    version = models.PositiveIntegerField(unique=True)
    is_active = models.BooleanField(default=False)
    params = models.JSONField(default=dict)
    note = models.CharField(max_length=256, blank=True, default="")
    created_by = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-version"]

    def __str__(self) -> str:
        return f"policy v{self.version}{' (active)' if self.is_active else ''}"


class Feedback(models.Model):
    """A human label for one question's answer on one record — the HITL learning signal.

    Human labels override the designed synthetic ground truth for that (record, question)
    pair when calibrators are fitted; every row feeds the closed learning loop
    (decisions -> feedback -> fit -> calibrated gates/routing).
    """

    SOURCES = [("manual", "Human label"), ("ground_truth", "Ground truth")]

    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="feedback")
    question_id = models.CharField(max_length=48)
    model_value = models.JSONField(null=True, blank=True)
    model_confidence = models.FloatField(null=True, blank=True)
    human_value = models.JSONField()
    source = models.CharField(max_length=16, choices=SOURCES, default="manual")
    actor = models.CharField(max_length=64, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["record", "question_id"])]

    def __str__(self) -> str:
        return f"{self.record_id}.{self.question_id} -> {self.human_value}"


class Calibration(models.Model):
    """Fitted reliability map + learned bias for one (use case, question) pair.

    `bins` is the monotone confidence->accuracy map; `bias` carries the learned value
    correction (boolean p-shift, score level offset, choice correction map). Identity
    until `fitted` — calibrators only engage once MIN_SAMPLES labelled pairs exist.
    """

    scope = models.CharField(max_length=64, unique=True)  # "<use_case>:<question_id>"
    use_case = models.CharField(max_length=32, db_index=True)
    question_id = models.CharField(max_length=48)
    question_type = models.CharField(max_length=16, blank=True, default="")
    n_samples = models.PositiveIntegerField(default=0)
    n_human = models.PositiveIntegerField(default=0)
    bins = models.JSONField(default=list, blank=True)
    bias = models.JSONField(default=dict, blank=True)
    accuracy_raw = models.FloatField(null=True, blank=True)
    accuracy_calibrated = models.FloatField(null=True, blank=True)
    ece_raw = models.FloatField(null=True, blank=True)
    ece_calibrated = models.FloatField(null=True, blank=True)
    fitted = models.BooleanField(default=False)
    fitted_at = models.DateTimeField(null=True, blank=True)
    history = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["scope"]

    def __str__(self) -> str:
        return f"{self.scope} n={self.n_samples}{' fitted' if self.fitted else ''}"
