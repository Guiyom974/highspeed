"""Seed the HighSpeed showcase datasets (62 use cases × N synthetic records, ground truth included)."""
from __future__ import annotations

import random

from django.core.management.base import BaseCommand

from showcase.models import Decision, Record, ShowcaseRun
from showcase.services import registry


class Command(BaseCommand):
    help = "Generate all synthetic datasets for the System One showcase (no engine required)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--seed", type=int, default=20260926, help="RNG seed (reproducible)")
        parser.add_argument("--scale", type=float, default=1.0,
                            help="record-count multiplier per use case (default 1.0 = 40)")
        parser.add_argument("--reset", action="store_true", help="wipe records/decisions/runs first")

    def handle(self, *args, **opts):
        if opts["reset"]:
            self.stdout.write("Resetting datasets...")
            Decision.objects.all().delete()
            ShowcaseRun.objects.all().delete()
            Record.objects.all().delete()

        if Record.objects.exists() and not opts["reset"]:
            self.stdout.write(self.style.WARNING(
                f"{Record.objects.count()} record(s) already exist; use --reset to rebuild."))
            return

        rng = random.Random(opts["seed"])
        total = 0
        for key in registry.USE_CASE_ORDER:
            uc = registry.get(key)
            count = max(2, int(round(uc["count"] * opts["scale"])))
            rows = uc["generate"](rng, count)
            Record.objects.bulk_create([
                Record(use_case=key, ref=r["ref"], payload=r["payload"],
                       ground_truth=r["ground_truth"]) for r in rows
            ])
            total += len(rows)
            self.stdout.write(f"  {key:22s} {len(rows):3d} records · "
                              f"{len(uc['questions'])} questions")
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {total} records across {len(registry.USE_CASE_ORDER)} use cases (seed {opts['seed']})."))
