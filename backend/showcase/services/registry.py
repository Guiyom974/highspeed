"""Use-case registry: decision schemas, NLI-authored hypotheses, state composers.

The local NLI engine scores the *criteria texts* as entailment hypotheses against the state
premise — instructions are documentation for humans and other engines.

Two measured authoring lessons drive the wording below (see README "Hypothesis-authoring"):

1. Every criterion must be a **full declarative sentence** — keyword fragments
   ("charges, invoices, refunds") cannot be entailed and scored 22-35% agreement.
2. Options of one question must share an **identical stem and differ only in the label
   phrase** for choice/score. Rich but asymmetric *choice* options carry different entailment
   priors: the most alarming option ("...phishing...blocked and reported") won 40/40 regardless
   of the premise (classic zero-shot label bias). Symmetric minimal pairs restored premise
   sensitivity (verdict 50→92%, score levels 50→100%).
3. **Booleans are the exception**: they WANT rich descriptive contrasts. Bare negation pairs
   ("is phishing" / "is not phishing") dropped phishing detection 95→68% — weak NLI negation
   handling needs concrete patterns on both sides ("...using urgency, lookalike senders or
   suspicious links" vs "...such as a newsletter, meeting invite or order update").
"""
from __future__ import annotations

from showcase.services import datasets, packs_a, packs_b, packs_c, packs_d


def _ticket_state(p: dict) -> str:
    return (f"Support ticket.\nSubject: {p['subject']}\nChannel: {p['channel']}. "
            f"Customer tier: {p['customer_tier']}.\nMessage: {p['body']}")


def _phish_state(p: dict) -> str:
    return (f"Inbound email.\nFrom: {p['sender']}\nSubject: {p['subject']}\n"
            f"Contains links: {'yes' if p['has_link'] else 'no'}.\nBody: {p['body']}")


def _mod_state(p: dict) -> str:
    return f"User-generated {p['channel']} post by '{p['author']}':\n{p['text']}"


def _review_state(p: dict) -> str:
    return (f"Product review of '{p['product']}', {p['stars']} star(s), "
            f"{'verified purchase' if p['verified_purchase'] else 'unverified'}.\n"
            f"Title: {p['title']}\nReview: {p['text']}")


def _resume_state(p: dict) -> str:
    return (f"Job description: {p['job_description']}\n\nCandidate resume.\n"
            f"Role applied for: {p['role_applied']}. Years of experience: {p['years_experience']}. "
            f"Degree: {'yes' if p['has_degree'] else 'no'}. Mentoring: {'yes' if p['mentored_others'] else 'no'}.\n"
            f"Skills: {', '.join(p['skills'])}.\nSummary: {p['summary']}")


def _clause_state(p: dict) -> str:
    return f"Contract clause from {p['contract']} (section: {p['clause_type']}):\n\"{p['text']}\""


def _txn_state(p: dict) -> str:
    return (f"Card transaction attempt.\nAmount: USD {p['amount_usd']:.2f}. "
            f"Merchant category: {p['merchant_category']}. Merchant country: {p['merchant_country']}. "
            f"Card issued in: {p['card_country']}.\nTransactions with this card in the last hour: "
            f"{p['transactions_last_hour']}. Device matches cardholder history: "
            f"{'yes' if p['device_matches_history'] else 'no'}. Night time at cardholder location: "
            f"{'yes' if p['is_night_local'] else 'no'}."
            + (f"\nMemo: {p['memo']}" if p.get("memo") else ""))


def _intake_state(p: dict) -> str:
    return (f"Clinical intake note (operational triage only, not a diagnosis).\n"
            f"Patient age: {p['age']}. Arrival: {p['arrived_by']}.\n"
            f"Chief complaint: {p['chief_complaint']}\nNote: {p['note']}")


def _news_state(p: dict) -> str:
    return (f"Monitored portfolio: {p['portfolio']}.\n\nArticle A.\nHeadline: {p['article_a_headline']}\n"
            f"Body: {p['article_a_body']}\n\nArticle B.\nHeadline: {p['article_b_headline']}\n"
            f"Body: {p['article_b_body']}")


def _log_state(p: dict) -> str:
    return (f"Log entry from service '{p['service']}' (level {p['level']}), "
            f"{p['occurrences_last_hour']} occurrence(s) in the last hour:\n{p['line']}")


def _fnol_state(p: dict) -> str:
    return (f"Insurance first notice of loss.\nPolicy: {p['policy']}. Incident: {p['incident_title']}.\n"
            f"Claimed amount: EUR {p['claimed_amount_eur']:,}. Days since incident: {p['days_since_incident']}. "
            f"Claims in last 12 months: {p['claims_last_12_months']}.\nReporter's note: {p['reporter_note']}")


def _survey_state(p: dict) -> str:
    return (f"Survey response from {p['respondent']} (NPS {p['nps_score']}/10).\n"
            f"Question: {p['survey_question']}\nAnswer: {p['verbatim']}")


USE_CASES: dict[str, dict] = {
    "ticket_triage": {
        "name": "Support ticket triage",
        "industry": "Customer support",
        "monogram": "ST",
        "pattern": "intent routing + gating",
        "blurb": "Route every inbound ticket to the right team, flag escalations and grade urgency — "
                 "in one batched pass, before a human ever sees the queue.",
        "count": 40,
        "questions": {
            "department": {
                "type": "choice",
                "instructions": "Which team should own this ticket?",
                "criteria": {
                    "billing": "This support ticket is about billing: charges, invoices, refunds or subscriptions.",
                    "technical": "This support ticket is about a technical problem: a bug, crash, API error or login failure.",
                    "sales": "This support ticket is about a potential sale: pricing, demos, quotes or migration.",
                    "abuse": "This support ticket is about platform abuse: spam, phishing, counterfeits, harassment or scraping.",
                },
            },
            "escalate": {
                "type": "boolean",
                "instructions": "Does this ticket need immediate escalation (legal threats, chargebacks, active abuse, outages)?",
                "criteria": {
                    "true": "This ticket needs immediate escalation: the sender threatens legal action or a chargeback, reports active abuse or fraud, or an outage is blocking users right now.",
                    "false": "This ticket is a routine request that can be handled in the normal queue without escalation.",
                },
            },
            "urgency": {
                "type": "score",
                "instructions": "How urgent is this ticket? (routine → urgent → critical)",
                "criteria": [
                    "This ticket is routine.",
                    "This ticket is urgent.",
                    "This ticket is critical.",
                ],
            },
        },
        "truth_map": {"department": "department", "escalate": "escalate", "urgency": "urgency"},
        "state_text": _ticket_state,
        "display_fields": [("subject", "Subject"), ("channel", "Channel"), ("customer_tier", "Tier")],
        "primary_field": "body",
        "generate": datasets.gen_ticket_triage,
    },
    "phishing_guard": {
        "name": "Phishing guard",
        "industry": "Cybersecurity",
        "monogram": "PG",
        "pattern": "guardrail gating",
        "blurb": "Screen every inbound email for credential theft and money-mule lures. The boolean "
                 "gate blocks, the choice grades, the score feeds the SOC queue.",
        "count": 40,
        "questions": {
            "phishing": {
                "type": "boolean",
                "instructions": "Is this email a phishing attempt?",
                "criteria": {
                    "true": "This email is a phishing or social-engineering attempt designed to steal credentials, money or data, using urgency, lookalike senders or suspicious links.",
                    "false": "This email is a legitimate, benign message such as a newsletter, meeting invite, order update or internal notice.",
                },
            },
            "verdict": {
                "type": "choice",
                "instructions": "Overall verdict for the mail gateway.",
                "criteria": {
                    "clean": "This email is clean and legitimate.",
                    "suspicious": "This email is suspicious but not certain.",
                    "phishing": "This email is phishing and fraudulent.",
                },
            },
            "risk": {
                "type": "score",
                "instructions": "Risk level of this email (low → high).",
                "criteria": [
                    "The risk of this email is low: a normal, expected message.",
                    "The risk of this email is medium: an unusual request deserves caution.",
                    "The risk of this email is high: an active attempt to steal.",
                ],
            },
        },
        "truth_map": {"phishing": "phishing", "verdict": "verdict", "risk": "risk"},
        "state_text": _phish_state,
        "display_fields": [("sender", "Sender"), ("subject", "Subject")],
        "primary_field": "body",
        "generate": datasets.gen_phishing_guard,
    },
    "content_moderation": {
        "name": "Content moderation",
        "industry": "Community / UGC",
        "monogram": "CM",
        "pattern": "boolean fan-out",
        "blurb": "Three independent policy booleans (toxicity, spam, PII exposure) plus a moderation "
                 "action — the classic fan-out where 20 checks cost about one LLM sentence.",
        "count": 40,
        "questions": {
            "toxic": {
                "type": "boolean",
                "instructions": "Is the post toxic?",
                "criteria": {
                    "true": "This post contains toxic language such as insults, harassment, demeaning wording or personal attacks.",
                    "false": "This post is civil and respectful, even if it is critical or disagrees.",
                },
            },
            "spam": {
                "type": "boolean",
                "instructions": "Is the post spam?",
                "criteria": {
                    "true": "This post is spam: unsolicited advertising, a scam offer or promotional links with sales pressure.",
                    "false": "This post is genuine user participation, not advertising.",
                },
            },
            "pii": {
                "type": "boolean",
                "instructions": "Does the post expose private personal information?",
                "criteria": {
                    "true": "This post exposes private personal information such as a home address, phone number or government ID.",
                    "false": "This post shares no private personal data about identifiable individuals.",
                },
            },
            "action": {
                "type": "choice",
                "instructions": "Moderation action (violations are removed; borderline posts are flagged).",
                "criteria": {
                    "keep": "The moderator should keep this post.",
                    "flag": "The moderator should flag this post.",
                    "remove": "The moderator should remove this post.",
                },
            },
        },
        "truth_map": {"toxic": "toxic", "spam": "spam", "pii": "pii", "action": "action"},
        "state_text": _mod_state,
        "display_fields": [("author", "Author"), ("channel", "Channel")],
        "primary_field": "text",
        "generate": datasets.gen_content_moderation,
    },
    "review_intel": {
        "name": "Review intelligence",
        "industry": "Retail / VoC",
        "monogram": "RI",
        "pattern": "rubric scoring",
        "blurb": "Turn thousands of product reviews into sentiment, churn signals and a 5-level "
                 "satisfaction rubric — batch-scored as they arrive.",
        "count": 40,
        "questions": {
            "sentiment": {
                "type": "choice",
                "instructions": "Overall sentiment of the review.",
                "criteria": {
                    "negative": "This review is negative: the reviewer is dissatisfied, complaining or warning others.",
                    "neutral": "This review is neutral: a mixed or matter-of-fact assessment without strong feeling.",
                    "positive": "This review is positive: the reviewer is satisfied, praising or recommending.",
                },
            },
            "churn_signal": {
                "type": "boolean",
                "instructions": "Does the review signal churn (cancel, switch, discourage others)?",
                "criteria": {
                    "true": "The reviewer intends to stop using the product, cancel, switch to a competitor, or discourage others from buying.",
                    "false": "There is no indication that the reviewer will leave, cancel or dissuade others.",
                },
            },
            "satisfaction": {
                "type": "score",
                "instructions": "Customer satisfaction (very dissatisfied → delighted).",
                "criteria": [
                    "The customer is very dissatisfied.",
                    "The customer is dissatisfied.",
                    "The customer is neither satisfied nor dissatisfied.",
                    "The customer is satisfied.",
                    "The customer is delighted.",
                ],
            },
        },
        "truth_map": {"sentiment": "sentiment", "churn_signal": "churn_signal",
                      "satisfaction": "satisfaction"},
        "state_text": _review_state,
        "display_fields": [("product", "Product"), ("stars", "Stars")],
        "primary_field": "text",
        "generate": datasets.gen_review_intel,
    },
    "resume_screen": {
        "name": "Resume pre-screening",
        "industry": "HR tech",
        "monogram": "RS",
        "pattern": "candidate pruning",
        "blurb": "Prune 10x more resumes than an LLM budget allows: one gate boolean, a 5-level fit "
                 "rubric and a disposition choice per candidate — humans only see the shortlist.",
        "count": 40,
        "questions": {
            "meets_minimum": {
                "type": "boolean",
                "instructions": "Does the candidate meet the JD minimums (5+ yrs Python, Django/FastAPI, SQL, cloud)?",
                "criteria": {
                    "true": "The candidate meets the core job requirements: at least five years of professional Python, production Django or FastAPI, solid SQL and cloud deployment experience.",
                    "false": "The candidate is missing one or more core requirements such as Python years, the framework, SQL or cloud experience.",
                },
            },
            "fit": {
                "type": "score",
                "instructions": "Overall fit for the role (poor → strong).",
                "criteria": [
                    "The candidate fit for this role is poor.",
                    "The candidate fit for this role is weak.",
                    "The candidate fit for this role is partial.",
                    "The candidate fit for this role is good.",
                    "The candidate fit for this role is strong.",
                ],
            },
            "disposition": {
                "type": "choice",
                "instructions": "Recruiter disposition.",
                "criteria": {
                    "reject": "The recruiter should reject this candidate.",
                    "maybe": "The recruiter should keep this candidate as a maybe.",
                    "shortlist": "The recruiter should shortlist this candidate.",
                },
            },
        },
        "truth_map": {"meets_minimum": "meets_minimum", "fit": "fit", "disposition": "disposition"},
        "state_text": _resume_state,
        "display_fields": [("name", "Candidate"), ("years_experience", "Years"),
                           ("has_degree", "Degree")],
        "primary_field": "summary",
        "generate": datasets.gen_resume_screen,
    },
    "contract_guard": {
        "name": "Contract clause guard",
        "industry": "Legal ops",
        "monogram": "CG",
        "pattern": "clause guardrails",
        "blurb": "Scan every clause for the three riskiest patterns (auto-renewal, uncapped "
                 "liability, non-compete) and grade it — before legal spends a minute.",
        "count": 40,
        "questions": {
            "auto_renewal": {
                "type": "boolean",
                "instructions": "Does the clause contain auto-renewal?",
                "criteria": {
                    "true": "This clause automatically renews the agreement for further terms unless a party gives notice.",
                    "false": "This clause has no automatic renewal; the agreement ends unless the parties actively extend it.",
                },
            },
            "unlimited_liability": {
                "type": "boolean",
                "instructions": "Is liability unlimited/uncapped?",
                "criteria": {
                    "true": "This clause leaves liability unlimited or uncapped, including indirect or consequential damages.",
                    "false": "This clause caps liability at a defined amount or excludes consequential damages.",
                },
            },
            "non_compete": {
                "type": "boolean",
                "instructions": "Is there a non-compete restriction?",
                "criteria": {
                    "true": "This clause restricts working with competitors after the engagement ends.",
                    "false": "This clause lets the person freely work with or for competitors afterwards.",
                },
            },
            "risk_level": {
                "type": "choice",
                "instructions": "Risk level of this clause for the signing party.",
                "criteria": {
                    "low": "The risk level of this clause is low.",
                    "medium": "The risk level of this clause is medium.",
                    "high": "The risk level of this clause is high.",
                },
            },
        },
        "truth_map": {"auto_renewal": "auto_renewal", "unlimited_liability": "unlimited_liability",
                      "non_compete": "non_compete", "risk_level": "risk_level"},
        "state_text": _clause_state,
        "display_fields": [("contract", "Contract"), ("clause_type", "Section")],
        "primary_field": "text",
        "generate": datasets.gen_contract_guard,
    },
    "payments_fraud": {
        "name": "Payments fraud pre-filter",
        "industry": "FinTech",
        "monogram": "PF",
        "pattern": "pre-filter cascade",
        "blurb": "Score every transaction before it hits an expensive rules engine or a human: "
                 "fraud and card-testing gates, an allow/review/block route, a risk grade.",
        "count": 40,
        "questions": {
            "likely_fraud": {
                "type": "boolean",
                "instructions": "Is this transaction likely fraudulent?",
                "criteria": {
                    "true": "This transaction shows fraud patterns: card-testing bursts, impossible velocity, a high-risk merchant category, high-risk geography, or a device that does not match the cardholder's history.",
                    "false": "This transaction looks like normal cardholder activity for this amount, merchant and geography.",
                },
            },
            "card_testing": {
                "type": "boolean",
                "instructions": "Is this automated card testing?",
                "criteria": {
                    "true": "This transaction is part of automated card testing with stolen card numbers.",
                    "false": "This is an ordinary purchase, not automated testing of card numbers.",
                },
            },
            "routing": {
                "type": "choice",
                "instructions": "Payment routing decision.",
                "criteria": {
                    "allow": "This transaction should be allowed.",
                    "review": "This transaction should be held for review.",
                    "block": "This transaction should be blocked.",
                },
            },
            "risk": {
                "type": "score",
                "instructions": "Fraud risk grade (low → high).",
                "criteria": [
                    "The fraud risk of this transaction is low.",
                    "The fraud risk of this transaction is medium.",
                    "The fraud risk of this transaction is high.",
                ],
            },
        },
        "truth_map": {"likely_fraud": "likely_fraud", "card_testing": "card_testing",
                      "routing": "routing", "risk": "risk"},
        "state_text": _txn_state,
        "display_fields": [("amount_usd", "Amount USD"), ("merchant_category", "Merchant"),
                           ("merchant_country", "Country")],
        "primary_field": "merchant_category",
        "generate": datasets.gen_payments_fraud,
    },
    "intake_triage": {
        "name": "Clinical intake triage",
        "industry": "Healthcare ops",
        "monogram": "IT",
        "pattern": "safety gating",
        "blurb": "Operational queue-sorting for intake notes — red-flag gating, department routing, "
                 "urgency grading. Explicitly NOT a diagnosis; humans always decide care.",
        "disclaimer": "Operational demo only — routes paperwork, never diagnoses. Real deployments "
                      "require clinical governance, calibration studies and human-in-the-loop by law.",
        "count": 40,
        "questions": {
            "red_flag": {
                "type": "boolean",
                "instructions": "Does the note contain emergency red flags (chest pain, stroke signs, severe bleeding, head injury)?",
                "criteria": {
                    "true": "The note describes immediate life-threatening symptoms such as chest pain, stroke signs, severe bleeding or head injury with loss of consciousness.",
                    "false": "The symptoms described are stable and not immediately life-threatening.",
                },
            },
            "department": {
                "type": "choice",
                "instructions": "Which department should see this patient first?",
                "criteria": {
                    "emergency": "This patient should be seen by the emergency department.",
                    "internal": "This patient should be seen by internal medicine.",
                    "dermatology": "This patient should be seen by dermatology.",
                    "pediatrics": "This patient should be seen by pediatrics.",
                },
            },
            "urgency": {
                "type": "score",
                "instructions": "How urgent is this intake? (low → immediate)",
                "criteria": [
                    "The urgency of this intake is low.",
                    "The urgency of this intake is moderate.",
                    "The urgency of this intake is high.",
                    "The urgency of this intake is immediate.",
                ],
            },
        },
        "truth_map": {"red_flag": "red_flag", "department": "department", "urgency": "urgency"},
        "state_text": _intake_state,
        "display_fields": [("age", "Age"), ("chief_complaint", "Complaint"), ("arrived_by", "Arrival")],
        "primary_field": "note",
        "generate": datasets.gen_intake_triage,
    },
    "news_dedup": {
        "name": "Wire dedup & relevance",
        "industry": "Media / intelligence",
        "monogram": "ND",
        "pattern": "NLI entailment (native)",
        "blurb": "Textual entailment is the NLI engine's home turf: are two articles the same event, "
                 "is the pair relevant to the monitored portfolio, how newsworthy is it?",
        "count": 40,
        "questions": {
            "same_event": {
                "type": "boolean",
                "instructions": "Do both articles report the same event?",
                "criteria": {
                    "true": "Article A and Article B report the same underlying news event.",
                    "false": "Article A and Article B report different news events.",
                },
            },
            "relevant": {
                "type": "boolean",
                "instructions": "Is the pair relevant to the portfolio (climate policy or semiconductor supply chains)?",
                "criteria": {
                    "true": "The articles are about climate policy or semiconductor supply chains.",
                    "false": "The articles are about topics outside the monitored portfolio of climate policy and semiconductor supply chains.",
                },
            },
            "newsworthiness": {
                "type": "score",
                "instructions": "Newsworthiness of the story (low → high).",
                "criteria": [
                    "The newsworthiness of this story is low.",
                    "The newsworthiness of this story is moderate.",
                    "The newsworthiness of this story is high.",
                ],
            },
        },
        "truth_map": {"same_event": "same_event", "relevant": "relevant",
                      "newsworthiness": "newsworthiness"},
        "state_text": _news_state,
        "display_fields": [("article_a_headline", "Article A"), ("article_b_headline", "Article B")],
        "primary_field": "article_a_body",
        "generate": datasets.gen_news_dedup,
    },
    "log_noise": {
        "name": "Log & alert noise reduction",
        "industry": "DevOps / SRE",
        "monogram": "LN",
        "pattern": "alert triage",
        "blurb": "Classify every log line, decide whether a human must be woken up, and grade "
                 "severity — 90% of the noise never reaches the on-call.",
        "count": 40,
        "questions": {
            "category": {
                "type": "choice",
                "instructions": "Classify this log entry.",
                "criteria": {
                    "error": "This log entry is an error.",
                    "warn": "This log entry is a warning.",
                    "info": "This log entry is informational.",
                    "noise": "This log entry is debug noise.",
                },
            },
            "needs_page": {
                "type": "boolean",
                "instructions": "Should this page the on-call engineer now?",
                "criteria": {
                    "true": "This entry requires waking an on-call engineer immediately.",
                    "false": "This entry can wait for business hours or needs no human action at all.",
                },
            },
            "severity": {
                "type": "score",
                "instructions": "Severity grade (minimal → critical).",
                "criteria": [
                    "The severity of this log entry is minimal.",
                    "The severity of this log entry is low.",
                    "The severity of this log entry is elevated.",
                    "The severity of this log entry is critical.",
                ],
            },
        },
        "truth_map": {"category": "category", "needs_page": "needs_page", "severity": "severity"},
        "state_text": _log_state,
        "display_fields": [("service", "Service"), ("level", "Level"),
                           ("occurrences_last_hour", "Count/h")],
        "primary_field": "line",
        "generate": datasets.gen_log_noise,
    },
    "fnol_fasttrack": {
        "name": "Claims FNOL fast-track",
        "industry": "InsurTech",
        "monogram": "FN",
        "pattern": "straight-through processing",
        "blurb": "First notice of loss: fast-track the obvious, route the standard, and flag fraud "
                 "suspicion for the SIU — most claims never need a human first pass.",
        "count": 40,
        "questions": {
            "fraud_suspicion": {
                "type": "boolean",
                "instructions": "Are there fraud indicators?",
                "criteria": {
                    "true": "This claim shows fraud indicators: an implausibly high value, missing evidence or declined documents, timing around missed payments, repeated claims, or inconsistent details.",
                    "false": "This claim is well-documented and consistent, with no notable fraud indicators.",
                },
            },
            "fast_track": {
                "type": "boolean",
                "instructions": "Eligible for straight-through settlement?",
                "criteria": {
                    "true": "This claim can be settled automatically without an adjuster.",
                    "false": "This claim needs an adjuster.",
                },
            },
            "queue": {
                "type": "choice",
                "instructions": "Handling queue.",
                "criteria": {
                    "fast_track": "This claim belongs in the fast-track auto-settle queue.",
                    "standard": "This claim belongs in the standard adjuster queue.",
                    "siu": "This claim belongs in the fraud investigations queue.",
                },
            },
            "severity": {
                "type": "score",
                "instructions": "Claim severity (minor → severe).",
                "criteria": [
                    "The severity of this claim is minor.",
                    "The severity of this claim is moderate.",
                    "The severity of this claim is severe.",
                ],
            },
        },
        "truth_map": {"fraud_suspicion": "fraud_suspicion", "fast_track": "fast_track",
                      "queue": "queue", "severity": "severity"},
        "state_text": _fnol_state,
        "display_fields": [("policy", "Policy"), ("incident_title", "Incident"),
                           ("claimed_amount_eur", "EUR")],
        "primary_field": "reporter_note",
        "generate": datasets.gen_fnol_fasttrack,
    },
    "survey_coding": {
        "name": "Survey verbatim coding",
        "industry": "Market research",
        "monogram": "SV",
        "pattern": "verbatim coding",
        "blurb": "Code open-ended survey answers into themes with intensity grading and an "
                 "actionability gate — the tedious 80% of every research sprint, automated.",
        "count": 40,
        "questions": {
            "theme": {
                "type": "choice",
                "instructions": "Primary theme of the verbatim.",
                "criteria": {
                    "price": "The primary theme of this response is price.",
                    "quality": "The primary theme of this response is product quality.",
                    "support": "The primary theme of this response is customer support.",
                    "shipping": "The primary theme of this response is shipping and returns.",
                    "other": "The primary theme of this response is another topic.",
                },
            },
            "actionable": {
                "type": "boolean",
                "instructions": "Is the feedback actionable?",
                "criteria": {
                    "true": "This feedback contains a specific, actionable improvement request or complaint.",
                    "false": "This response is vague, purely emotional, or general praise without a concrete action.",
                },
            },
            "intensity": {
                "type": "score",
                "instructions": "Emotional intensity (mild → intense).",
                "criteria": [
                    "The emotional intensity of this feedback is mild.",
                    "The emotional intensity of this feedback is firm.",
                    "The emotional intensity of this feedback is intense.",
                ],
            },
        },
        "truth_map": {"theme": "theme", "actionable": "actionable", "intensity": "intensity"},
        "state_text": _survey_state,
        "display_fields": [("respondent", "Respondent"), ("nps_score", "NPS")],
        "primary_field": "verbatim",
        "generate": datasets.gen_survey_coding,
    },
}

USE_CASE_ORDER = list(USE_CASES)

# --- spec-driven expansion packs (50 more use cases, 62 total) --------------
ALL_PACKS = packs_a.PACKS_A + packs_b.PACKS_B + packs_c.PACKS_C + packs_d.PACKS_D

for _pack in ALL_PACKS:
    if _pack["key"] in USE_CASES:
        raise RuntimeError(f"duplicate use-case key in packs: {_pack['key']}")
    USE_CASES[_pack["key"]] = packs_a.to_use_case(_pack)
    USE_CASE_ORDER.append(_pack["key"])


def get(key: str) -> dict:
    if key not in USE_CASES:
        raise KeyError(f"unknown use case '{key}'")
    return USE_CASES[key]
