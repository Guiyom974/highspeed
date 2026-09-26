"""HighSpeed showcase tests — all engine-free (the decision engine is mocked).

Covers: registry/schema validity vs the systemone client rules, generator determinism and
ground-truth integrity, state-text bounds, agreement math, the synchronous runner path with a
mocked engine, and the HTTP API surface (stats/detail/reseed/export/busy-guard).
"""
from __future__ import annotations

import json
import random
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from showcase.models import Calibration, Decision, PolicyConfig, Record, ShowcaseRun
from showcase.services import datasets, learning, policy, registry, runner

VALID_TYPES = {"boolean", "noul", "choice", "score"}


class RegistryValidityTests(TestCase):
    def test_use_case_catalog_is_complete_and_unique(self):
        self.assertEqual(len(registry.USE_CASES), 62)
        self.assertEqual(len(set(registry.USE_CASE_ORDER)), 62)
        self.assertEqual(set(registry.USE_CASE_ORDER), set(registry.USE_CASES))

    def test_question_schemas_follow_client_rules(self):
        for key, uc in registry.USE_CASES.items():
            questions = uc["questions"]
            self.assertTrue(questions, f"{key}: no questions")
            total_opts = 0
            for qid, q in questions.items():
                self.assertIn(q["type"], VALID_TYPES, f"{key}.{qid}: bad type")
                self.assertIsInstance(q["instructions"], str)
                self.assertTrue(q["instructions"].strip(), f"{key}.{qid}: empty instructions")
                if q["type"] in ("boolean", "noul"):
                    crit = q.get("criteria")
                    if crit is not None:
                        self.assertIsInstance(crit, dict, f"{key}.{qid}: bool criteria must be dict")
                        self.assertTrue(str(crit.get("true", "")).strip())
                        self.assertTrue(str(crit.get("false", "")).strip())
                elif q["type"] == "choice":
                    crit = q["criteria"]
                    self.assertIsInstance(crit, dict, f"{key}.{qid}: choice criteria must be dict")
                    self.assertGreaterEqual(len(crit), 2, f"{key}.{qid}: choice needs >=2 options")
                    self.assertLessEqual(len(crit), 64, f"{key}.{qid}: NLI option cap is 64")
                    for opt, desc in crit.items():
                        self.assertTrue(str(desc).strip(), f"{key}.{qid}.{opt}: empty description")
                    total_opts += len(crit)
                else:  # score
                    crit = q["criteria"]
                    self.assertIsInstance(crit, list, f"{key}.{qid}: score criteria must be list")
                    self.assertTrue(2 <= len(crit) <= 10, f"{key}.{qid}: score needs 2-10 levels")
                    for lvl in crit:
                        self.assertTrue(str(lvl).strip(), f"{key}.{qid}: empty level text")
                    total_opts += len(crit)
            self.assertLessEqual(total_opts, 96, f"{key}: exceeds 96-question budget per request")

    def test_truth_map_and_display_fields(self):
        rng = random.Random(1)
        for key, uc in registry.USE_CASES.items():
            for qid in uc["truth_map"]:
                self.assertIn(qid, uc["questions"], f"{key}: truth_map qid {qid} not a question")
            rows = uc["generate"](rng, 4)
            self.assertTrue(rows, f"{key}: generator produced nothing")
            sample = rows[0]
            for field, _label in uc["display_fields"]:
                self.assertIn(field, sample["payload"], f"{key}: display field {field} missing")
            self.assertIn(uc["primary_field"], sample["payload"],
                          f"{key}: primary_field missing in payload")

    def test_state_text_within_context_bounds(self):
        rng = random.Random(2)
        for key, uc in registry.USE_CASES.items():
            for row in uc["generate"](rng, uc["count"]):
                text = uc["state_text"](row["payload"])
                self.assertIsInstance(text, str)
                self.assertLessEqual(len(text), 3500,
                                     f"{key}/{row['ref']}: state text too long for NLI context")
                self.assertTrue(text.strip())


class GeneratorTests(TestCase):
    def test_deterministic_for_same_seed(self):
        a = [g(random.Random(42), 40) for g in datasets.GENERATORS.values()]
        b = [g(random.Random(42), 40) for g in datasets.GENERATORS.values()]
        self.assertEqual(a, b)

    def test_different_seeds_differ(self):
        x = datasets.gen_ticket_triage(random.Random(1), 40)
        y = datasets.gen_ticket_triage(random.Random(2), 40)
        self.assertNotEqual([r["payload"]["body"] for r in x],
                            [r["payload"]["body"] for r in y])

    def test_counts_refs_and_ground_truth(self):
        rng = random.Random(3)
        for key, uc in registry.USE_CASES.items():
            rows = uc["generate"](rng, uc["count"])
            self.assertEqual(len(rows), uc["count"], f"{key}: wrong count")
            refs = [r["ref"] for r in rows]
            self.assertEqual(len(set(refs)), len(refs), f"{key}: duplicate refs")
            truth_keys = set(uc["truth_map"].values())
            for row in rows:
                self.assertTrue(truth_keys <= set(row["ground_truth"]),
                                f"{key}/{row['ref']}: ground truth missing keys")
                for qid, tkey in uc["truth_map"].items():
                    q = uc["questions"][qid]
                    tv = row["ground_truth"][tkey]
                    if q["type"] in ("boolean", "noul"):
                        self.assertIsInstance(tv, bool, f"{key}.{qid}: truth must be bool")
                    elif q["type"] == "choice":
                        self.assertIn(tv, q["criteria"], f"{key}.{qid}: truth not an option")
                    else:
                        self.assertIn(tv, range(len(q["criteria"])),
                                      f"{key}.{qid}: truth level out of range")

    def test_ground_truth_has_variation(self):
        """Every question must have both 'yes-ish' and 'no-ish' truth in the dataset."""
        rng = random.Random(4)
        for key, uc in registry.USE_CASES.items():
            rows = uc["generate"](rng, uc["count"])
            for qid, tkey in uc["truth_map"].items():
                values = {r["ground_truth"][tkey] for r in rows}
                self.assertGreater(len(values), 1, f"{key}.{qid}: degenerate ground truth")


class AgreementMathTests(TestCase):
    def test_boolean_match(self):
        self.assertTrue(runner.matches("boolean", True, {"value": True}))
        self.assertFalse(runner.matches("boolean", True, {"value": False}))
        self.assertIsNone(runner.matches("boolean", None, {"value": True}))

    def test_choice_match(self):
        self.assertTrue(runner.matches("choice", "billing", {"value": "billing"}))
        self.assertFalse(runner.matches("choice", "billing", {"value": "sales"}))

    def test_score_tolerance(self):
        self.assertTrue(runner.matches("score", 2, {"level": 2}))
        self.assertTrue(runner.matches("score", 2, {"level": 3}))   # within ±1
        self.assertFalse(runner.matches("score", 0, {"level": 2}))
        # level missing -> derive from expectation value
        self.assertTrue(runner.matches("score", 1, {"value": 1.2}))

    def test_compute_agreement_shape(self):
        questions = {"q": {"type": "boolean"}}
        truth_map = {"q": "t"}
        pairs = [({"t": True}, {"q": {"value": True}}),
                 ({"t": False}, {"q": {"value": True}})]
        out = runner.compute_agreement(questions, truth_map, pairs)
        self.assertEqual(out["q"], {"type": "boolean", "matched": 1, "total": 2,
                                    "agree": 0.5, "agree_strict": 0.5})

    def test_score_strict_vs_tolerant_and_levels_used(self):
        questions = {"s": {"type": "score"}}
        truth_map = {"s": "t"}
        # constant mid-level predictor on a 3-level scale: tolerant 100%, strict ~0
        pairs = [({"t": 0}, {"s": {"level": 1}}), ({"t": 2}, {"s": {"level": 1}}),
                 ({"t": 1}, {"s": {"level": 1}})]
        out = runner.compute_agreement(questions, truth_map, pairs)
        self.assertEqual(out["s"]["agree"], 1.0)
        self.assertEqual(out["s"]["agree_strict"], round(1 / 3, 4))
        self.assertEqual(out["s"]["levels_used"], 1)


def _perfect_engine(uc_key: str):
    """Patches making the engine return answers that exactly match designed ground truth."""
    uc = registry.get(uc_key)
    truth_by_id = {r.id: r.ground_truth for r in Record.objects.filter(use_case=uc_key)}

    def fake_decide_many(states, questions, chunk=8):
        out = []
        for s in states:
            truth = truth_by_id[int(s["id"])]
            answers = {}
            for qid, q in questions.items():
                tv = truth.get(uc["truth_map"][qid])
                if q["type"] in ("boolean", "noul"):
                    answers[qid] = {"type": "boolean", "value": bool(tv),
                                    "p_true": 0.99 if tv else 0.01, "confidence": 0.99,
                                    "routing": "act"}
                elif q["type"] == "choice":
                    answers[qid] = {"type": "choice", "value": tv, "choice": tv,
                                    "confidence": 0.97,
                                    "probabilities": {k: (0.97 if k == tv else 0.01)
                                                      for k in q["criteria"]},
                                    "routing": "act"}
                else:
                    answers[qid] = {"type": "score", "value": float(tv), "score": float(tv),
                                    "level": int(tv), "confidence": 0.95,
                                    "probabilities": {str(i): (0.95 if i == int(tv) else 0.01)
                                                      for i in range(len(q["criteria"]))},
                                    "routing": "act"}
            out.append({"id": s["id"], "answers": answers, "wall_seconds": 0.5,
                        "batch_size": len(states), "engine": "mock-nli", "profile": "gpu-nli"})
        return out

    return [
        mock.patch("showcase.services.engine.warm",
                   return_value={"status": "ready", "engine": "mock-nli"}),
        mock.patch("showcase.services.engine.status",
                   return_value={"status": "ready", "engine": "mock-nli", "device": "mock",
                                 "profile": "gpu-nli", "calibrated": False,
                                 "requested_profile": "gpu-nli", "engine_ready": True}),
        mock.patch("showcase.services.engine.decide_many", side_effect=fake_decide_many),
    ]


class RunnerTests(TestCase):
    KEY = "ticket_triage"

    def _seed(self, key=KEY, count=12):
        rng = random.Random(99)
        rows = registry.get(key)["generate"](rng, count)
        Record.objects.bulk_create([Record(use_case=key, ref=r["ref"], payload=r["payload"],
                                           ground_truth=r["ground_truth"]) for r in rows])

    def test_run_persists_decisions_and_perfect_agreement(self):
        self._seed()
        run = ShowcaseRun.objects.create(use_case=self.KEY, status="pending")
        patches = _perfect_engine(self.KEY)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        runner.run_use_case(run, self.KEY)

        run.refresh_from_db()
        self.assertEqual(run.status, "done")
        self.assertEqual(run.total, 12)
        self.assertEqual(run.done, 12)
        self.assertEqual(Decision.objects.filter(run=run).count(), 12)
        for qid, metric in run.agreement.items():
            self.assertEqual(metric["agree"], 1.0, f"{qid}: expected perfect mock agreement")
            self.assertEqual(metric["total"], 12)
        self.assertEqual(run.engine, "mock-nli")
        self.assertIsNotNone(run.decisions_per_second)
        self.assertIsNotNone(run.median_latency_ms)
        d = Decision.objects.first()
        self.assertIn("department", d.answers)
        self.assertEqual(d.answers["department"]["type"], "choice")

    def test_rerun_replaces_previous_decisions(self):
        self._seed(count=4)
        patches = _perfect_engine(self.KEY)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        run1 = ShowcaseRun.objects.create(use_case=self.KEY, status="pending")
        runner.run_use_case(run1, self.KEY)
        run2 = ShowcaseRun.objects.create(use_case=self.KEY, status="pending")
        runner.run_use_case(run2, self.KEY)
        self.assertEqual(Decision.objects.filter(record__use_case=self.KEY).count(), 4)
        self.assertEqual(Decision.objects.filter(run=run2).count(), 4)

    def test_run_without_records_errors(self):
        run = ShowcaseRun.objects.create(use_case="phishing_guard", status="pending")
        patches = _perfect_engine(self.KEY)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        runner.run_use_case(run, "phishing_guard")
        run.refresh_from_db()
        self.assertEqual(run.status, "error")
        self.assertIn("no records", run.error)


class ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        rng = random.Random(7)
        uc = registry.get("log_noise")
        rows = uc["generate"](rng, 8)
        Record.objects.bulk_create([Record(use_case="log_noise", ref=r["ref"],
                                           payload=r["payload"],
                                           ground_truth=r["ground_truth"]) for r in rows])

    def setUp(self):
        self.client = APIClient()

    def test_health_and_engine(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["service"], "HighSpeed")
        self.assertEqual(self.client.get("/api/engine").status_code, 200)

    def test_stats_and_usecases(self):
        res = self.client.get("/api/stats")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["use_case_count"], 62)
        self.assertEqual(res.data["total_records"], 8)
        self.assertEqual(len(res.data["use_cases"]), 62)
        summaries = {s["key"]: s for s in res.data["use_cases"]}
        self.assertEqual(summaries["log_noise"]["record_count"], 8)
        res = self.client.get("/api/usecases")
        self.assertEqual(len(res.data), 62)

    def test_usecase_detail(self):
        res = self.client.get("/api/usecases/log_noise")
        self.assertEqual(res.status_code, 200)
        self.assertIn("category", res.data["questions"])
        self.assertEqual(len(res.data["records"]), 8)
        self.assertIsNone(res.data["records"][0]["decision"])
        res = self.client.get("/api/usecases/nope")
        self.assertEqual(res.status_code, 404)

    def test_run_busy_guard(self):
        with mock.patch("showcase.services.jobs.is_busy", return_value=True):
            res = self.client.post("/api/usecases/log_noise/run", {}, format="json")
        self.assertEqual(res.status_code, 409)

    def test_run_no_records(self):
        with mock.patch("showcase.services.jobs.is_busy", return_value=False):
            res = self.client.post("/api/usecases/ticket_triage/run", {}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("no records", res.data["error"])

    def test_reseed_creates_all_datasets(self):
        res = self.client.post("/api/actions/reseed", {"seed": 5}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["use_cases"], 62)
        self.assertEqual(Record.objects.count(), res.data["records"])
        expected = sum(registry.get(k)["count"] for k in registry.USE_CASE_ORDER)
        self.assertEqual(Record.objects.count(), expected)
        # deterministic: reseed with same seed produces identical first record
        first_a = Record.objects.filter(use_case="ticket_triage").order_by("id").first().payload
        self.client.post("/api/actions/reseed", {"seed": 5}, format="json")
        first_b = Record.objects.filter(use_case="ticket_triage").order_by("id").first().payload
        self.assertEqual(first_a, first_b)

    def test_export_csv_after_mocked_run(self):
        run = ShowcaseRun.objects.create(use_case="log_noise", status="pending")
        patches = _perfect_engine("log_noise")
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        runner.run_use_case(run, "log_noise")

        res = self.client.get("/api/usecases/log_noise/export.csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res["Content-Type"])
        body = res.content.decode()
        lines = body.strip().splitlines()
        self.assertEqual(len(lines), 9)  # header + 8 records
        self.assertIn("category_value", lines[0])
        self.assertIn("category_truth", lines[0])
        self.assertIn("category_match", lines[0])
        self.assertIn("yes", body)

    def test_run_views(self):
        res = self.client.get("/api/runs/latest")
        self.assertEqual(res.status_code, 200)
        run = ShowcaseRun.objects.create(use_case="log_noise", status="pending", total=8)
        res = self.client.get(f"/api/runs/{run.id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["use_case"], "log_noise")
        res = self.client.get("/api/runs/latest?use_case=log_noise")
        self.assertEqual(res.data["id"], run.id)
        res = self.client.get("/api/runs/999999")
        self.assertEqual(res.status_code, 404)


class PolicyServiceTests(TestCase):
    def setUp(self):
        self.addCleanup(policy.invalidate)
        self.addCleanup(learning.clear_cache)

    def test_defaults_preserve_original_behaviour(self):
        version, params = policy.active()
        self.assertEqual(version, 1)
        self.assertEqual(params["gates"], {"act_gate": 0.90, "floor": 0.50})
        self.assertFalse(params["criteria"]["enabled"])
        self.assertFalse(params["materiality"]["enabled"])
        self.assertEqual(sorted(params["use_cases"]), [])

    def test_validate_rejects_bad_params(self):
        with self.assertRaisesMessage(ValueError, "floor"):
            policy.validate_params({"gates": {"act_gate": 0.5, "floor": 0.9}})
        with self.assertRaisesMessage(ValueError, "match_mode"):
            policy.validate_params({"criteria": {"match_mode": "maybe"}})
        with self.assertRaisesMessage(ValueError, "min_similarity"):
            policy.validate_params({"criteria": {"fuzzy": True, "min_similarity": 2}})
        with self.assertRaisesMessage(ValueError, "review_amount"):
            policy.validate_params({"materiality": {"enabled": True, "field": "amount_usd",
                                                    "min_amount": 100, "review_amount": 10}})

    def test_validate_normalises_and_accepts_good_params(self):
        out = policy.validate_params({
            "criteria": {"enabled": True, "match_mode": "all",
                         "must_contain": ["  refund  ", "chargeback"],
                         "must_not_contain": ["x" * 100]},
            "materiality": {"enabled": True, "field": "amount_usd",
                            "min_amount": 100, "review_amount": 5000},
            "use_cases": {"payments_fraud": {"gates": {"act_gate": 0.95, "floor": 0.6}}},
        })
        self.assertEqual(out["criteria"]["must_contain"], ["refund", "chargeback"])
        self.assertEqual(len(out["criteria"]["must_not_contain"][0]), 64)
        self.assertEqual(out["use_cases"]["payments_fraud"]["gates"]["act_gate"], 0.95)

    def test_params_for_deep_merges_use_case_override(self):
        params = policy.merge_params({
            "gates": {"act_gate": 0.8},
            "use_cases": {"ticket_triage": {"gates": {"act_gate": 0.99},
                                            "criteria": {"enabled": True,
                                                         "must_contain": ["urgent"]}}},
        })
        tc = policy.params_for("ticket_triage", params)
        self.assertEqual(tc["gates"]["act_gate"], 0.99)
        self.assertTrue(tc["criteria"]["enabled"])
        other = policy.params_for("log_noise", params)
        self.assertEqual(other["gates"]["act_gate"], 0.8)
        self.assertFalse(other["criteria"]["enabled"])

    def test_criteria_scope_evaluation(self):
        payload = {"body": "My payment was refunded after the chargeback", "id": 1}
        text = policy.searchable_text(payload)
        off = {"enabled": False, "must_contain": [], "must_not_contain": [],
               "fuzzy": False, "min_similarity": 0.85, "match_mode": "any"}
        self.assertTrue(policy.evaluate_criteria(payload, text, off)["in_scope"])
        blocked = {**off, "enabled": True, "must_not_contain": ["chargeback"]}
        res = policy.evaluate_criteria(payload, text, blocked)
        self.assertFalse(res["in_scope"])
        self.assertEqual(res["reason"], "excluded")
        self.assertIn("chargeback", res["detail"])
        need = {**off, "enabled": True, "match_mode": "all", "must_contain": ["refund"]}
        self.assertTrue(policy.evaluate_criteria(payload, text, need)["in_scope"])
        need_all = {**off, "enabled": True, "match_mode": "all",
                    "must_contain": ["refund", "missing-term"]}
        self.assertFalse(policy.evaluate_criteria(payload, text, need_all)["in_scope"])
        fuzzy = {**off, "enabled": True, "fuzzy": True, "min_similarity": 0.6,
                 "must_contain": ["refunded"]}
        self.assertTrue(policy.evaluate_criteria(payload, text, fuzzy)["in_scope"])

    def test_materiality_evaluation(self):
        mat = {"enabled": True, "field": "amount_usd", "min_amount": 100,
               "review_amount": 5000}
        low = policy.evaluate_materiality({"amount_usd": 42.5}, mat)
        self.assertFalse(low["material"])
        self.assertEqual(low["reason"], "below_materiality")
        high = policy.evaluate_materiality({"amount_usd": 9000}, mat)
        self.assertTrue(high["material"])
        self.assertTrue(high["force_review"])
        mid = policy.evaluate_materiality({"amount_usd": 500}, mat)
        self.assertTrue(mid["material"])
        self.assertFalse(mid["force_review"])
        missing = policy.evaluate_materiality({"other": 1}, mat)
        self.assertTrue(missing["material"])
        self.assertIsNone(missing["amount"])
        disabled = policy.evaluate_materiality({"amount_usd": 1}, {**mat, "enabled": False})
        self.assertTrue(disabled["material"])

    def test_routing_ladder(self):
        gates = {"act_gate": 0.9, "floor": 0.5}
        out_of_scope = {"in_scope": False}
        neutral = {"in_scope": True}
        self.assertEqual(policy.routing_for(0.99, gates, neutral, {"material": True}), "act")
        self.assertEqual(policy.routing_for(0.7, gates, neutral, {"material": True}), "review")
        self.assertEqual(policy.routing_for(0.2, gates, neutral, {"material": True}), "fallback")
        self.assertEqual(policy.routing_for(None, gates, neutral, {"material": True}), "review")
        self.assertEqual(policy.routing_for(0.99, gates, out_of_scope, {"material": True}),
                         "excluded")
        self.assertEqual(policy.routing_for(0.99, gates, neutral, {"material": False}),
                         "auto_dispose")
        self.assertEqual(policy.routing_for(0.99, gates, neutral,
                                            {"material": True, "force_review": True}), "review")


class LearningServiceTests(TestCase):
    KEY = "ticket_triage"

    def setUp(self):
        self.addCleanup(policy.invalidate)
        self.addCleanup(learning.clear_cache)

    def _seed(self, key=KEY, count=12):
        rng = random.Random(21)
        rows = registry.get(key)["generate"](rng, count)
        Record.objects.bulk_create([Record(use_case=key, ref=r["ref"], payload=r["payload"],
                                           ground_truth=r["ground_truth"]) for r in rows])

    def _run(self, key=KEY):
        run = ShowcaseRun.objects.create(use_case=key, status="pending")
        for p in _perfect_engine(key):
            p.start()
            self.addCleanup(p.stop)
        runner.run_use_case(run, key)
        run.refresh_from_db()
        return run

    def test_fit_identity_below_min_samples(self):
        self._seed(count=4)
        self._run()
        cal = learning.fit(self.KEY, "department")
        self.assertIsNotNone(cal)
        self.assertFalse(cal.fitted)
        self.assertEqual(cal.n_samples, 4)
        out = learning.calibrate(self.KEY, "department", {"value": "billing",
                                                          "confidence": 0.97})
        self.assertEqual(out, {})

    def test_fit_from_ground_truth_and_calibrated_confidence(self):
        self._seed(count=12)
        self._run()
        fitted = learning.fit_all(self.KEY)
        self.assertGreater(fitted, 0)
        cal = learning.fit(self.KEY, "department")
        self.assertTrue(cal.fitted)
        self.assertEqual(cal.n_samples, 12)
        self.assertEqual(cal.n_human, 0)
        self.assertTrue(cal.bins)
        self.assertIsNotNone(cal.ece_raw)
        out = learning.calibrate(self.KEY, "department", {"value": "billing",
                                                          "confidence": 0.97})
        self.assertIn("confidence_calibrated", out)

    def test_human_feedback_overrides_ground_truth_and_refits(self):
        self._seed(count=12)
        self._run()
        rec = Record.objects.filter(use_case=self.KEY).first()
        truth = rec.ground_truth[registry.get(self.KEY)["truth_map"]["department"]]
        flipped = not truth if isinstance(truth, bool) else "billing"
        decisions = list(rec.decisions.all())
        answer = decisions[-1].answers["department"]
        fb = learning.record_feedback(rec, "department", flipped, actor="tester",
                                      model_answer=answer)
        self.assertEqual(fb.source, "manual")
        rows = learning.training_rows(self.KEY, "department")
        manual = [r for r in rows if r["source"] == "manual"]
        self.assertEqual(len(manual), 1)
        self.assertEqual(manual[0]["label"], flipped)
        cal = learning.fit(self.KEY, "department")
        self.assertTrue(cal.fitted)
        self.assertEqual(cal.n_human, 1)

    def test_boolean_p_shift_correction(self):
        scope = learning.scope_key(self.KEY, "escalate")
        Calibration.objects.create(
            scope=scope, use_case=self.KEY, question_id="escalate",
            question_type="boolean", n_samples=40, fitted=True,
            bins=[{"lo": 0.0, "hi": 1.0, "n": 40, "acc": 0.95}],
            bias={"p_shift": -0.6})
        answer = {"type": "boolean", "value": True, "p_true": 0.95, "confidence": 0.95}
        out = learning.calibrate(self.KEY, "escalate", answer)
        self.assertEqual(out["value"], False)
        self.assertAlmostEqual(out["p_true_calibrated"], 0.35, places=3)
        self.assertIn("corrected True->False", out["adjustment"])
        learning.clear_cache(scope)

    def test_score_offset_and_choice_map(self):
        scope = learning.scope_key(self.KEY, "urgency")
        qtype = registry.get(self.KEY)["questions"]["urgency"]["type"]
        Calibration.objects.create(
            scope=scope, use_case=self.KEY, question_id="urgency",
            question_type=qtype, n_samples=30, fitted=True,
            bins=[{"lo": 0.0, "hi": 1.0, "n": 30, "acc": 0.9}],
            bias={"score_offset": 1.0} if qtype == "score" else
                 {"choice_map": {"low": "high"}})
        if qtype == "score":
            out = learning.calibrate(self.KEY, "urgency",
                                     {"value": 1.0, "level": 1, "confidence": 0.9})
            self.assertEqual(out.get("level"), 2)
        else:
            out = learning.calibrate(self.KEY, "urgency", {"value": "low", "confidence": 0.9})
            self.assertEqual(out.get("value"), "high")
        learning.clear_cache(scope)

    def test_suggestions_and_export(self):
        self._seed(count=12)
        self._run()
        learning.fit_all(self.KEY)
        sugg = learning.suggest_params()
        self.assertIn("suggestions", sugg)
        self.assertIn("basis", sugg)
        self.assertIn("current_act_gate", sugg["basis"])
        for s in sugg["suggestions"]:
            self.assertEqual(s["param"], "gates.act_gate")
            self.assertGreaterEqual(s["suggested"], s["current"])
        body = learning.export_jsonl()
        lines = [json.loads(line) for line in body.strip().splitlines()]
        self.assertTrue(lines)
        self.assertTrue(all("label_source" in row for row in lines))
        self.assertTrue(any(row["label_source"] == "ground_truth" for row in lines))


class RunnerGovernanceTests(TestCase):
    def setUp(self):
        self.addCleanup(policy.invalidate)
        self.addCleanup(learning.clear_cache)

    def _seed(self, key, count=12):
        rng = random.Random(33)
        rows = registry.get(key)["generate"](rng, count)
        Record.objects.bulk_create([Record(use_case=key, ref=r["ref"], payload=r["payload"],
                                           ground_truth=r["ground_truth"]) for r in rows])

    def _run(self, key):
        run = ShowcaseRun.objects.create(use_case=key, status="pending")
        for p in _perfect_engine(key):
            p.start()
            self.addCleanup(p.stop)
        runner.run_use_case(run, key)
        run.refresh_from_db()
        return run

    def _activate(self, params, note="test"):
        merged = policy.validate_params({**policy.bootstrap_params(), **params})
        cfg = PolicyConfig.objects.create(version=policy.next_version(), is_active=True,
                                          params=merged, note=note)
        policy.invalidate()
        return cfg

    def test_criteria_excludes_records_and_stamps_policy_version(self):
        self._seed("ticket_triage")
        cfg = self._activate({"criteria": {"enabled": True, "match_mode": "all",
                                           "must_contain": ["no-such-term-anywhere"]}})
        run = self._run("ticket_triage")
        self.assertEqual(run.status, "done")
        self.assertEqual(run.policy_version, cfg.version)
        self.assertEqual(run.scope["excluded"], 12)
        d = Decision.objects.filter(record__use_case="ticket_triage").first()
        for answer in d.answers.values():
            self.assertEqual(answer["routing"], "excluded")
            self.assertIn("excluded:", answer["scope_note"])

    def test_materiality_auto_dispose_and_forced_review(self):
        self._seed("payments_fraud")
        self._activate({"materiality": {"enabled": True, "field": "amount_usd",
                                        "min_amount": 1e12, "review_amount": 0}})
        run = self._run("payments_fraud")
        self.assertEqual(run.scope["below_materiality"], 12)
        d = Decision.objects.filter(record__use_case="payments_fraud").first()
        for answer in d.answers.values():
            self.assertEqual(answer["routing"], "auto_dispose")

        policy.invalidate()
        self._activate({"materiality": {"enabled": True, "field": "amount_usd",
                                        "min_amount": 0, "review_amount": 1}})
        run2 = self._run("payments_fraud")
        self.assertEqual(run2.scope["forced_review"], 12)
        d = Decision.objects.filter(record__use_case="payments_fraud").order_by("-id").first()
        for answer in d.answers.values():
            self.assertEqual(answer["routing"], "review")

    def test_calibration_applied_during_run(self):
        self._seed("ticket_triage")
        self._run("ticket_triage")
        learning.fit_all("ticket_triage")
        for qid, q in registry.get("ticket_triage")["questions"].items():
            scope = learning.scope_key("ticket_triage", qid)
            cal = Calibration.objects.get(scope=scope)
            self.assertTrue(cal.fitted, f"{scope}: expected fitted from 12 labelled pairs")
            cal.bins = [{"lo": 0.0, "hi": 0.9, "n": 10, "acc": 0.7},
                        {"lo": 0.9, "hi": 1.01, "n": 30, "acc": 0.88}]
            cal.bias = {"p_shift": -0.5} if q["type"] == "boolean" else {}
            cal.save()
            learning.clear_cache(scope)
        run = self._run("ticket_triage")
        self.assertEqual(run.status, "done")
        self.assertGreater(run.scope["calibrated"], 0)
        self.assertGreater(run.scope["adjusted"], 0)
        d = Decision.objects.filter(record__use_case="ticket_triage").first()
        bool_answers = [a for a in d.answers.values() if a.get("type") == "boolean"]
        self.assertTrue(bool_answers)
        self.assertIn("confidence_calibrated", bool_answers[0])
        self.assertIn("adjustment", bool_answers[0])


class GovernanceApiTests(TestCase):
    def setUp(self):
        self.addCleanup(policy.invalidate)
        self.addCleanup(learning.clear_cache)
        self.client = APIClient()
        rng = random.Random(11)
        uc = registry.get("log_noise")
        rows = uc["generate"](rng, 6)
        Record.objects.bulk_create([Record(use_case="log_noise", ref=r["ref"],
                                           payload=r["payload"],
                                           ground_truth=r["ground_truth"]) for r in rows])

    def test_policy_get_and_role_gate(self):
        res = self.client.get("/api/policy")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["active"]["version"], 1)
        self.assertIn("compliance", res.data["write_roles"])
        res = self.client.post("/api/policy", {"params": {"gates": {"act_gate": 0.9}}},
                               format="json")
        self.assertEqual(res.status_code, 403)
        res = self.client.post("/api/policy", {"params": {"gates": {"act_gate": 0.9}}},
                               format="json", HTTP_X_ROLE="compliance")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["version"], 2)
        self.assertTrue(res.data["is_active"])
        stats = self.client.get("/api/stats").data
        self.assertEqual(stats["policy"]["version"], 2)
        self.assertEqual(stats["policy"]["gates"]["act_gate"], 0.9)
        res = self.client.post("/api/policy/activate/1", {}, format="json",
                               HTTP_X_ROLE="compliance")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.client.get("/api/stats").data["policy"]["version"], 1)

    def test_policy_post_validation_error(self):
        res = self.client.post("/api/policy", {"params": {"gates": {"act_gate": 5}}},
                               format="json", HTTP_X_ROLE="admin")
        self.assertEqual(res.status_code, 400)
        self.assertIn("act_gate", res.data["error"])

    def test_feedback_requires_analysis_role_and_valid_value(self):
        rec = Record.objects.filter(use_case="log_noise").first()
        res = self.client.post("/api/feedback",
                               {"record_id": rec.id, "question_id": "needs_page",
                                "value": True}, format="json")
        self.assertEqual(res.status_code, 403)
        res = self.client.post("/api/feedback",
                               {"record_id": rec.id, "question_id": "nope", "value": True},
                               format="json", HTTP_X_ROLE="analyst")
        self.assertEqual(res.status_code, 400)
        res = self.client.post("/api/feedback",
                               {"record_id": rec.id, "question_id": "needs_page",
                                "value": "not-a-bool"}, format="json",
                               HTTP_X_ROLE="analyst")
        self.assertEqual(res.status_code, 400)
        res = self.client.post("/api/feedback",
                               {"record_id": rec.id, "question_id": "needs_page",
                                "value": True, "actor": "analyst-1"}, format="json",
                               HTTP_X_ROLE="analyst")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["feedback"]["human_value"], True)
        self.assertEqual(res.data["feedback"]["actor"], "analyst-1")
        self.assertEqual(res.data["calibration"]["fitted"], False)
        listing = self.client.get("/api/feedback?use_case=log_noise")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["count"], 1)

    def test_learning_endpoints(self):
        res = self.client.get("/api/learning")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["policy_version"], 1)
        self.assertIn("suggestions", res.data)
        self.assertEqual(res.data["feedback_count"], 0)
        res = self.client.post("/api/learning/refit", {}, format="json")
        self.assertEqual(res.status_code, 403)
        res = self.client.post("/api/learning/refit", {"use_case": "log_noise"},
                               format="json", HTTP_X_ROLE="compliance")
        self.assertEqual(res.status_code, 200)
        self.assertIn("fitted", res.data)
        res = self.client.post("/api/learning/apply", {}, format="json",
                               HTTP_X_ROLE="compliance")
        self.assertEqual(res.status_code, 400)
        res = self.client.post("/api/learning/apply",
                               {"params": {"gates": {"act_gate": 0.93}},
                                "note": "manual tune"}, format="json",
                               HTTP_X_ROLE="compliance")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["params"]["gates"]["act_gate"], 0.93)
        self.assertEqual(self.client.get("/api/stats").data["policy"]["version"], 2)
        res = self.client.get("/api/learning/export")
        self.assertEqual(res.status_code, 200)
        self.assertIn("ndjson", res["Content-Type"])
        self.assertIn("highspeed-finetune-dataset.jsonl", res["Content-Disposition"])
