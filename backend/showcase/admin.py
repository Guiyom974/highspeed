"""Django admin registration (back-office view of the showcase datasets)."""
from __future__ import annotations

from django.contrib import admin

from showcase.models import Decision, Record, ShowcaseRun


@admin.register(Record)
class RecordAdmin(admin.ModelAdmin):
    list_display = ("ref", "use_case", "created_at")
    list_filter = ("use_case",)
    search_fields = ("ref",)


@admin.register(ShowcaseRun)
class ShowcaseRunAdmin(admin.ModelAdmin):
    list_display = ("id", "use_case", "status", "done", "total", "decisions_per_second",
                    "median_latency_ms", "engine", "started_at")
    list_filter = ("use_case", "status")


@admin.register(Decision)
class DecisionAdmin(admin.ModelAdmin):
    list_display = ("id", "record", "run", "latency_ms", "engine", "created_at")
    list_filter = ("run__use_case",)
