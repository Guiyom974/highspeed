"""Seeded synthetic dataset generators — one per use case.

Every generator is deterministic for a given seed and emits records shaped
`{"ref": str, "payload": dict, "ground_truth": dict}`. Ground truth keys match the registry
`truth_map` so the runner can compute agreement. Text is template-pool × slot-fill: varied
enough to be interesting, controlled enough that labels are unambiguous by construction.

All data is fictional. Any resemblance to real persons/companies is coincidental.
"""
from __future__ import annotations

import random

# ---------------------------------------------------------------------------
# shared slot pools
# ---------------------------------------------------------------------------
FIRST = ["Ava", "Liam", "Maya", "Noah", "Zoe", "Ethan", "Ines", "Omar", "Nina", "Kai", "Sofia",
         "Lucas", "Aria", "Milo", "Tara", "Jonas", "Leila", "Ravi", "Emma", "Hugo"]
LAST = ["Kowalski", "Nguyen", "Silva", "Okafor", "Berg", "Rossi", "Haddad", "Kim", "Novak",
        "Marino", "Duarte", "Fischer", "Sato", "Ali", "Vargas", "Lindqvist", "Moreau", "Reyes"]
COMPANY = ["Northwind", "Acme Logistics", "BluePeak", "Contoso Foods", "Ferright & Co",
           "Lumina Health", "Orbital Software", "Pinecrest Bank", "Redlane Media", "Solara Energy"]
PRODUCT = ["AeroPress coffee maker", "TrailMaster 40L backpack", "LumenDesk LED lamp",
           "PureTone earbuds", "ChefCore knife set", "NimbusX umbrella", "VoltFit power bank"]
ORDER = lambda rng: f"ORD-{rng.randint(10000, 99999)}"          # noqa: E731
TICKET = lambda rng: f"TCK-{rng.randint(1000, 9999)}"            # noqa: E731
DEVICE = ["iPhone 15", "Pixel 9", "Windows 11 desktop", "MacBook Air", "iPad", "Android tablet"]
CHANNEL = ["email", "chat", "phone", "web form"]


def _name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def _rec(i: int, prefix: str, payload: dict, truth: dict) -> dict:
    return {"ref": f"{prefix}-{i + 1:04d}", "payload": payload, "ground_truth": truth}


# ---------------------------------------------------------------------------
# 1 · Support ticket triage
# ---------------------------------------------------------------------------
_TICKET_POOL = {
    "billing": [
        ("Charged twice for {o}", "I was charged twice for order {o} on the same day. My card statement shows two identical amounts. I want the duplicate refunded immediately."),
        ("Invoice VAT wrong", "Invoice INV-{n} lists the wrong VAT number for our company. Accounting cannot book it. Please reissue with VAT ID {v}."),
        ("Refund not received", "I returned the {p} twelve days ago (tracking shows delivered) but the refund for {o} still has not appeared on my card."),
        ("Subscription renewed after cancel", "I cancelled the annual plan on time but was charged again yesterday for {o}. This is the second time. Refund and cancel, or I will file a chargeback."),
        ("Price changed mid-contract", "Our contract says EUR 49/seat but the latest invoice charges EUR 69/seat. Honour the agreed price or explain the change in writing."),
    ],
    "technical": [
        ("App crashes on {d}", "Since the last update the app crashes every time I open the reports tab on my {d}. Reinstalling did not help. Logs attached."),
        ("API 500 on POST /v2/orders", "POST /v2/orders returns HTTP 500 for about 30% of requests since 09:00 UTC. Request IDs: {v}, {v2}. Our integration is blocked."),
        ("Cannot log in after password reset", "The password reset email link works, I set a new password, but login says 'invalid credentials' forever. I have tried three browsers."),
        ("Sync broken between mobile and web", "Changes made on the {d} app stopped syncing to the web dashboard {k} days ago. Pull-to-refresh does nothing."),
        ("Export produces empty CSV", "Exporting the customer list to CSV produces a 0-byte file. It worked last week. We need this for our monthly reporting."),
    ],
    "sales": [
        ("Volume pricing for {k} seats", "We are evaluating you for {k} seats across two offices. Do you offer volume pricing and annual invoicing? Please send a quote."),
        ("SSO / SAML support", "Our IT team requires SAML SSO and SCIM provisioning before purchase. Is this available on the business plan or on the roadmap?"),
        ("Demo request", "I would like to schedule a demo for our operations team ({k} people) next week, focusing on the analytics module."),
        ("Migration from competitor", "We currently pay a competitor EUR {n}/month. What would migration cost and do you import our historical data?"),
    ],
    "abuse": [
        ("Spam sent from your platform", "Your platform is being used to send phishing spam from account id {v}. Recipients are our employees. Disable it and confirm."),
        ("Counterfeit listings", "Seller 'bestdeals-{n}' lists counterfeit {p} using our trademarked photos. Remove the listings or our legal team will get in touch."),
        ("Harassment in community forum", "User {u} is repeatedly posting harassing content in the community forum despite reports. This is the third complaint this week."),
        ("Data scraping detected", "We detect systematic scraping of our member directory from your IP range. Stop immediately or we escalate to counsel and file a report."),
    ],
}
_URGENCY_HIGH = ["production", "blocked", "500", "crash", "outage"]
_ESCALATE_MARKERS = ["chargeback", "legal", "counsel", "second time", "third", "escalate"]


def gen_ticket_triage(rng: random.Random, n: int) -> list[dict]:
    cats = list(_TICKET_POOL)
    out = []
    for i in range(n):
        cat = cats[i % len(cats)]
        subject, body = rng.choice(_TICKET_POOL[cat])
        slots = dict(o=ORDER(rng), n=rng.randint(1000, 99999), v=f"VAT-{rng.randint(10**7, 10**8 - 1)}",
                     p=rng.choice(PRODUCT), d=rng.choice(DEVICE), k=rng.randint(2, 400),
                     v2=f"req_{rng.randint(10**5, 10**6 - 1)}",
                     u=f"{rng.choice(FIRST).lower()}{rng.randint(10, 99)}")
        body = body.format(**slots)
        subject = subject.format(**slots)
        angry = rng.random() < (0.7 if cat in ("billing", "abuse") else 0.2)
        if angry:
            body += rng.choice([" This is unacceptable.", " Third time I contact you!!",
                                " I expect a reply today or I escalate.", " Very disappointed."])
        low = body.lower()
        escalate = cat == "abuse" or any(m in low for m in _ESCALATE_MARKERS)
        if escalate or any(m in low for m in ["500", "blocked", "crashes every time"]):
            urgency = 2 if (cat == "abuse" or "500" in low or "blocked" in low) else 1
        elif cat in ("billing", "technical"):
            urgency = 1 if angry else 0
        else:
            urgency = 0
        out.append(_rec(i, "TCK", {
            "subject": subject, "body": body, "channel": rng.choice(CHANNEL),
            "customer_tier": rng.choice(["free", "pro", "business", "enterprise"]),
        }, {"department": cat, "escalate": escalate, "urgency": urgency}))
    return out


# ---------------------------------------------------------------------------
# 2 · Phishing guard
# ---------------------------------------------------------------------------
_PHISH_POOL = [
    ("Action required: verify your account", "security@acc0unt-{dom}-verify.com",
     "We detected unusual activity. Verify your password within 24 hours or your account will be suspended: http://{dom}-secure.login-verify.{tld}/confirm?id={n}"),
    ("URGENT: invoice payment redirected", "accounts@{vendor}-billing.{tld}",
     "Our bank changed. Please route the outstanding invoice INV-{n} (USD {amt}) to the new account IBAN GB33-CITI-{n2}. Confirmation required today. CEO approved by phone."),
    ("You have a DocuSign document", "docus1gn@dse-signature.{tld}",
     "A document titled 'Contract_{n}.pdf' is awaiting your signature. Review in DocuSign: http://ds-signature.{tld}.x9.{tld}/review/{n2}. Enable macros to view."),
    ("Your package could not be delivered", "no-reply@post-{dom}-fees.{tld}",
     "Delivery failed: unpaid customs fee of 1.99 EUR. Pay within 48h to reschedule: https://{dom}-fees.pay-now.{tld}/{n}. Card details required."),
    ("CEO request - confidential", "c.eo.office@{vendor}-exec.{tld}",
     "I am in meetings all day. Can you purchase 8 gift cards (500 each) for a client surprise? Send me the codes. Do not tell finance yet, it is a surprise."),
    ("Password expired - reset now", "it-desk@{dom}-helpdesk.{tld}",
     "Your mailbox password expired. Reset it here to keep your emails: http://{dom}.helpdesk-reset.{tld}/owa?u={u}. Failure resets your account tonight."),
]
_CLEAN_POOL = [
    ("Your {m} newsletter", "news@{vendor}.{tld}",
     "This month in {m}: product updates, a case study from {c}, and the recording of last week's webinar. You receive this because you subscribed."),
    ("Meeting invite: weekly sync", "calendar@{vendor}.{tld}",
     "Weekly team sync moved to Thursday 10:00. Agenda: roadmap review, hiring pipeline, Q4 planning. Join link is in the calendar entry."),
    ("Your order {o} has shipped", "shipments@store.{vendor}.{tld}",
     "Good news: your {p} is on the way. Carrier tracking shows delivery by Friday. Questions? Reply to this email and our support team will help."),
    ("IT notice: maintenance window", "it@{vendor}.{tld}",
     "Planned maintenance Saturday 02:00-04:00 UTC. VPN will be unavailable for ~15 minutes. No action needed; do not reply to this address."),
    ("Invoice INV-{n} paid - thank you", "billing@{vendor}.{tld}",
     "We received your payment of EUR {amt} for invoice INV-{n}. Your account is up to date. The receipt is attached for your records."),
]


def gen_phishing_guard(rng: random.Random, n: int) -> list[dict]:
    tlds = ["xyz", "top", "click", "biz", "info"]
    out = []
    for i in range(n):
        phish = i % 2 == 0
        dom = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(8))
        vendor = rng.choice(COMPANY).replace(" ", "").replace("&", "").lower()
        slots = dict(dom=dom, tld=rng.choice(tlds), n=rng.randint(10**5, 10**6 - 1),
                     n2=rng.randint(10**4, 10**5 - 1), amt=f"{rng.randint(4, 90)},000",
                     vendor=vendor, u=f"{rng.choice(FIRST).lower()}.{rng.choice(LAST).lower()}",
                     m=rng.choice(["Product Digest", "DevOps Weekly", "The Margin"]),
                     c=rng.choice(COMPANY), o=ORDER(rng), p=rng.choice(PRODUCT))
        if phish:
            subject, sender, body = rng.choice(_PHISH_POOL)
            truth = dict(phishing=True, verdict="phishing", risk=2)
        else:
            subject, sender, body = rng.choice(_CLEAN_POOL)
            truth = dict(phishing=False, verdict="clean", risk=0)
        out.append(_rec(i, "EML", {
            "subject": subject.format(**slots), "sender": sender.format(**slots),
            "body": body.format(**slots),
            "has_link": phish or rng.random() < 0.4,
        }, truth))
    return out


# ---------------------------------------------------------------------------
# 3 · Content moderation
# ---------------------------------------------------------------------------
_TOXIC_POOL = [
    "You are all idiots for shipping this garbage, whoever made this change should be fired.",
    "What a pathetic excuse for an update. The team behind this is clueless and lazy.",
    "Delete your account, {u}, nobody asked for your stupid opinion. Learn to read.",
    "This company is a joke and its customers are brainwashed sheep defending a scam.",
]
_SPAM_POOL = [
    "BUY CHEAP FOLLOWERS NOW!!! Visit best-social-boost.{tld} - 10k followers for $9.99, no password needed, 24/7 delivery, MONEY BACK",
    "CASINO BONUS 500% on first deposit -> lucky-spin-{n}.{tld} - withdraw same day, no verification, works for all countries",
    "Work from home $400/day, no experience needed, message me on telegram @easy_cash_{n}, limited spots this week",
    "CHEAP sneakers watches wallets replica 1:1 quality, DM for catalog, ship worldwide, pay after delivery {u}{n}",
]
_PII_POOL = [
    "Posting the doxx here: {u} lives at {n} Maple Street, Springfield, phone 555-0{n}47, works at {c}. Someone should pay them a visit.",
    "Found her private number: +1 555-0{n}22 and home address {n} Oak Ave. Sharing her email too: {u}@mail.com. Spread it.",
    "Leaked: employee {u} SSN ends {n}41, home address {n} Pine Rd, and his kids' school. Print this everywhere.",
]
_OK_POOL = [
    "Honestly the new dark mode is great, but I wish the font size setting was per-screen instead of global.",
    "Does anyone know if the export feature supports XLSX or only CSV? Asking before our monthly report.",
    "Just finished onboarding my team - the import tool saved us hours. One papercut: column mapping resets on back.",
    "Friendly reminder to hydrate and take breaks, fellow lurkers. Also the community guidelines pinned post is worth reading.",
    "I disagree with the take above, but respectfully: the pricing page should state the seat minimums clearly.",
    "Can we get a keyboard shortcut for archive? Mouse-only workflow slows triage down a lot.",
]


def gen_content_moderation(rng: random.Random, n: int) -> list[dict]:
    tlds = ["xyz", "top", "buzz"]
    out = []
    kinds = ["ok", "ok", "toxic", "spam", "pii", "ok"]
    for i in range(n):
        kind = kinds[i % len(kinds)]
        slots = dict(u=f"{rng.choice(FIRST).lower()}{rng.randint(10, 99)}", tld=rng.choice(tlds),
                     n=rng.randint(100, 999), c=rng.choice(COMPANY))
        if kind == "toxic":
            text = rng.choice(_TOXIC_POOL).format(**slots)
            # blatant toxicity violates policy -> remove (flag is reserved for borderline content,
            # which this synthetic set does not contain; the model choosing flag counts as a miss)
            truth = dict(toxic=True, spam=False, pii=False, action="remove")
        elif kind == "spam":
            text = rng.choice(_SPAM_POOL).format(**slots)
            truth = dict(toxic=False, spam=True, pii=False, action="remove")
        elif kind == "pii":
            text = rng.choice(_PII_POOL).format(**slots)
            truth = dict(toxic=False, spam=False, pii=True, action="remove")
        else:
            text = rng.choice(_OK_POOL).format(**slots)
            truth = dict(toxic=False, spam=False, pii=False, action="keep")
        out.append(_rec(i, "CMT", {
            "author": slots["u"], "channel": rng.choice(["forum", "review", "chat", "comment"]),
            "text": text,
        }, truth))
    return out


# ---------------------------------------------------------------------------
# 4 · Review intelligence (VoC)
# ---------------------------------------------------------------------------
_REVIEW_POOL = {
    "negative": [
        ("Worst purchase this year", "The {p} broke after {k} weeks. Support never replied to three emails. I want a refund and I will not buy from this brand again. Uninstalling the app and telling my friends."),
        ("Actively misleading", "Advertised as waterproof, but it died in light rain. Returning it and switching to a competitor - already ordered one. Do not waste your money."),
        ("Terrible service experience", "Delivery was {k} weeks late, the item arrived damaged, and the return process is a nightmare. I have been a loyal customer for years but this was the last straw. Cancel my subscription."),
    ],
    "neutral": [
        ("Fine, with caveats", "The {p} does its job. Build quality feels cheap and the manual is confusing, but for the price it is acceptable. Might look at alternatives next time."),
        ("Okay experience overall", "Ordered on Monday, arrived Thursday. The product matches the description, nothing more. Support answered within a day when I asked about the warranty."),
        ("Mixed feelings", "Some things are great (battery life), some are not (the app crashes on my {d}). On the fence about recommending it."),
    ],
    "positive": [
        ("Exceeded expectations", "The {p} is fantastic - arrived early, works exactly as described, and the little extras (pouch, spare parts) show real care. Already ordered a second one as a gift."),
        ("Great product, great support", "Had a small issue with my order and support resolved it in hours, no arguments. The {p} itself is excellent quality. Five stars, will buy again."),
        ("Best in class", "I compared four brands and this one wins on quality and price. Setup took five minutes. Genuinely impressed - recommending to everyone at work."),
    ],
}


def gen_review_intel(rng: random.Random, n: int) -> list[dict]:
    cats = list(_REVIEW_POOL)
    stars = {"negative": (1, 2), "neutral": (3,), "positive": (4, 5)}
    out = []
    for i in range(n):
        cat = cats[i % len(cats)]
        title, text = rng.choice(_REVIEW_POOL[cat])
        text = text.format(p=rng.choice(PRODUCT), k=rng.randint(2, 8), d=rng.choice(DEVICE))
        low = text.lower()
        churn = cat == "negative" and any(m in low for m in ["not buy", "switching", "cancel", "competitor", "uninstalling"])
        sat = {"negative": rng.choice([0, 1]), "neutral": 2, "positive": rng.choice([3, 4])}[cat]
        out.append(_rec(i, "REV", {
            "product": rng.choice(PRODUCT), "stars": rng.choice(stars[cat]),
            "title": title, "text": text, "verified_purchase": rng.random() < 0.8,
        }, {"sentiment": cat, "churn_signal": churn, "satisfaction": sat}))
    return out


# ---------------------------------------------------------------------------
# 5 · Resume screening (fixed JD)
# ---------------------------------------------------------------------------
RESUME_JD = ("Senior Python Backend Engineer. Requirements: 5+ years professional Python; "
             "production experience with Django or FastAPI; strong SQL and data modelling; "
             "cloud deployment (AWS/GCP/Azure); mentoring experience; CS degree preferred.")
_SKILL_POOL = ["Python", "Django", "FastAPI", "Flask", "PostgreSQL", "MySQL", "SQL", "AWS", "GCP",
               "Azure", "Docker", "Kubernetes", "REST", "GraphQL", "Celery", "Redis", "Terraform",
               "Java", "C#", "Node.js", "React", "Go", "Rust", "PHP"]


def gen_resume_screen(rng: random.Random, n: int) -> list[dict]:
    out = []
    bands = [("strong", 12), ("mid", 16), ("weak", 12)]
    i = 0
    for band, count in bands:
        for _ in range(count if n >= 40 else max(1, count * n // 40)):
            if i >= n:
                break
            if band == "strong":
                years = rng.randint(6, 14)
                skills = ["Python", rng.choice(["Django", "FastAPI"]), "PostgreSQL",
                          rng.choice(["AWS", "GCP", "Azure"]), "Docker", "Kubernetes"]
                if rng.random() < 0.5:
                    skills += rng.sample(["Terraform", "Celery", "Redis", "GraphQL"], 2)
                degree = rng.random() < 0.85
                mentored = True
                summary = (f"{years} years building high-traffic Python services. Led a team of "
                           f"{rng.randint(3, 8)} engineers; owns architecture for a platform "
                           f"serving {rng.randint(2, 90)}M requests/day on {skills[3]} with "
                           f"Postgres. Mentors mid-level engineers and runs design reviews.")
                truth = dict(meets_minimum=True, fit=rng.choice([3, 4]), disposition="shortlist")
            elif band == "mid":
                years = rng.randint(4, 6)
                skills = ["Python", rng.choice(["Django", "Flask", "FastAPI"]), "SQL",
                          rng.choice(["AWS", "Docker"])]
                degree = rng.random() < 0.6
                mentored = rng.random() < 0.4
                summary = (f"Backend developer with {years} years of Python experience building "
                           f"REST APIs and internal tools. Comfortable with SQL and basic cloud "
                           f"deployment. Looking for a senior role with mentoring opportunities.")
                truth = dict(meets_minimum=years >= 5, fit=2,
                             disposition="maybe" if years >= 5 else "reject")
            else:
                years = rng.randint(0, 3)
                skills = rng.sample([s for s in _SKILL_POOL if s not in
                                     ("Python", "Django", "FastAPI")], rng.randint(3, 6))
                if rng.random() < 0.5:
                    skills.append("Python")
                degree = rng.random() < 0.4
                summary = (f"Developer with {years} year(s) of experience across "
                           f"{', '.join(skills[:3])}. Eager to transition into Python backend work; "
                           f"completed an online bootcamp last year.")
                truth = dict(meets_minimum=False, fit=rng.choice([0, 1]), disposition="reject")
            out.append(_rec(i, "CV", {
                "name": _name(rng), "role_applied": "Senior Python Backend Engineer",
                "years_experience": years, "skills": skills, "has_degree": degree,
                "mentored_others": mentored, "summary": summary, "job_description": RESUME_JD,
            }, truth))
            i += 1
    return out[:n]


# ---------------------------------------------------------------------------
# 6 · Contract clause guard
# ---------------------------------------------------------------------------
_CLAUSE_POOL = {
    "auto_renewal": [
        "This Agreement shall automatically renew for successive twelve (12) month terms unless either party provides written notice of non-renewal at least ninety (90) days prior to the end of the then-current term.",
        "Upon expiry of the initial term, the subscription renews automatically at the then-list price; cancellation is only effective at the end of a renewal period.",
    ],
    "liability": [
        "The Provider's aggregate liability arising out of or related to this Agreement shall be unlimited and shall include all indirect, consequential and punitive damages without cap.",
        "Supplier's total liability under this Agreement shall not exceed the fees paid by Customer in the twelve (12) months preceding the claim, excluding breaches of confidentiality.",
    ],
    "non_compete": [
        "For twenty-four (24) months following termination, the Contractor shall not provide similar services to any competitor of the Company within the same market, worldwide.",
        "During the engagement and for six (6) months after, the Employee will not solicit the Company's clients for a competing product within the EU.",
    ],
    "benign": [
        "Either party may terminate this Agreement for convenience with thirty (30) days' written notice. Fees are prorated to the termination date.",
        "The Provider shall process personal data solely on documented instructions and maintains SOC 2 Type II certification; the DPA at Annex 3 applies.",
        "Invoices are payable net thirty (30) days from receipt. Late payments accrue interest at 1% per month or the legal maximum, whichever is lower.",
        "Each party retains ownership of its pre-existing intellectual property; deliverables transfer to Customer upon full payment.",
        "Disputes shall be resolved by binding arbitration in {city} under the rules of the local chamber of commerce; governing law is {law}.",
    ],
}


def gen_contract_guard(rng: random.Random, n: int) -> list[dict]:
    kinds = ["benign", "benign", "auto_renewal", "liability", "non_compete", "benign"]
    out = []
    for i in range(n):
        kind = kinds[i % len(kinds)]
        text = rng.choice(_CLAUSE_POOL[kind]).format(
            city=rng.choice(["Zurich", "London", "New York", "Singapore"]),
            law=rng.choice(["Swiss law", "English law", "Delaware law"]))
        truth = dict(
            auto_renewal=kind == "auto_renewal",
            unlimited_liability=kind == "liability" and "unlimited" in text,
            non_compete=kind == "non_compete",
            risk_level={"auto_renewal": "medium", "liability": "high" if "unlimited" in text else "low",
                        "non_compete": "high", "benign": "low"}[kind],
        )
        out.append(_rec(i, "CLZ", {
            "contract": f"MSA-{rng.randint(100, 999)} · {rng.choice(COMPANY)}",
            "clause_type": {"auto_renewal": "Term & Renewal", "liability": "Limitation of Liability",
                            "non_compete": "Restrictive Covenants", "benign": rng.choice(
                                ["Termination", "Data Protection", "Payment", "IP Ownership",
                                 "Dispute Resolution"])}[kind],
            "text": text,
        }, truth))
    return out


# ---------------------------------------------------------------------------
# 7 · Payments fraud pre-filter
# ---------------------------------------------------------------------------
def gen_payments_fraud(rng: random.Random, n: int) -> list[dict]:
    out = []
    kinds = (["clean"] * 24 + ["suspicious"] * 10 + ["fraud"] * 6)
    rng.shuffle(kinds)
    mcc_clean = ["grocery", "fuel", "restaurant", "pharmacy", "streaming service"]
    mcc_risk = ["crypto exchange", "gift cards", "wire transfer", "online gambling", "electronics resale"]
    for i in range(n):
        kind = kinds[i % len(kinds)]
        if kind == "clean":
            amount = round(rng.uniform(4, 300), 2)
            mcc = rng.choice(mcc_clean)
            country = rng.choice(["DE", "DE", "FR", "NL", "US", "GB", "NO"])
            velocity = rng.randint(1, 3)
            device_match = True
            truth = dict(likely_fraud=False, card_testing=False, routing="allow", risk=0)
        elif kind == "suspicious":
            amount = round(rng.uniform(300, 2500), 2)
            mcc = rng.choice(mcc_clean + mcc_risk)
            country = rng.choice(["DE", "CY", "LV", "US", "NG", "BR"])
            velocity = rng.randint(3, 8)
            device_match = rng.random() < 0.5
            truth = dict(likely_fraud=False, card_testing=False, routing="review",
                         risk=1)
        else:
            pattern = rng.choice(["testing", "burst"])
            if pattern == "testing":
                amount = round(rng.uniform(0.5, 3.0), 2)
                velocity = rng.randint(15, 60)
                mcc = rng.choice(mcc_risk)
                country = rng.choice(["RU", "CN", "NG", "IR", "MM"])
                truth = dict(likely_fraud=True, card_testing=True, routing="block", risk=2)
            else:
                amount = round(rng.uniform(2500, 9800), 2)
                velocity = rng.randint(6, 20)
                mcc = rng.choice(mcc_risk)
                country = rng.choice(["RU", "CY", "PA", "MM"])
                truth = dict(likely_fraud=True, card_testing=False, routing="block", risk=2)
            device_match = False
        out.append(_rec(i, "TXN", {
            "amount_usd": amount, "merchant_category": mcc, "merchant_country": country,
            "card_country": rng.choice(["DE", "DE", "FR", "US"]),
            "transactions_last_hour": velocity,
            "device_matches_history": device_match,
            "is_night_local": rng.random() < (0.8 if kind == "fraud" else 0.2),
            "memo": rng.choice(["", "", "quick purchase", "gift", "reseller order", "test"]) if kind != "clean" else "",
        }, truth))
    return out


# ---------------------------------------------------------------------------
# 8 · Clinical intake triage (non-diagnostic operational demo)
# ---------------------------------------------------------------------------
_INTAKE_POOL = {
    "emergency": [
        ("Chest pain and shortness of breath", "{age} y/o reports crushing chest pain radiating to the left arm for the past {m} minutes, with sweating and shortness of breath at rest."),
        ("Sudden one-sided weakness", "{age} y/o with sudden right-sided facial droop and arm weakness that started {m} minutes ago; speech is slurred. Family witnessed onset."),
        ("Severe bleeding after fall", "{age} y/o fell from a ladder; deep leg laceration with active spurting bleeding, soaking through two bandages. Pale and dizzy."),
        ("Head injury with loss of consciousness", "{age} y/o struck head in a car accident, lost consciousness for about a minute, now vomiting and confused."),
    ],
    "internal": [
        ("Persistent fever and cough", "{age} y/o with fever up to 39.1C for {d} days, productive cough and fatigue. No breathing difficulty at rest. Vaccinations up to date."),
        ("Worsening hypertension readings", "{age} y/o reports home blood pressure readings of 165/100 over the past week despite medication. Mild headaches, no chest pain."),
        ("Abdominal pain after meals", "{age} y/o with recurring upper-abdominal pain after fatty meals for {d} weeks, nausea but no vomiting, no fever."),
    ],
    "dermatology": [
        ("Spreading rash on forearm", "{age} y/o with an itchy red rash on the forearm that appeared {d} days ago after gardening; no fever, no breathing problems."),
        ("Changing mole on shoulder", "{age} y/o noticed a shoulder mole changed color and size over {m} months; no bleeding, no pain. Requests check."),
    ],
    "pediatrics": [
        ("Child with ear pain", "{age}-month-old infant, irritable and pulling at the right ear since yesterday, mild fever 38.2C, feeding reduced but drinking."),
        ("Child vaccination consult", "Parent requests the scheduled vaccination check for a {age}-month-old; child is well, no symptoms, mild eczema history."),
    ],
}


def gen_intake_triage(rng: random.Random, n: int) -> list[dict]:
    cats = list(_INTAKE_POOL)
    quotas = {"emergency": 8, "internal": 14, "dermatology": 9, "pediatrics": 9}
    out, i = [], 0
    for cat in cats:
        for _ in range(max(1, round(quotas[cat] * n / 40))):
            if i >= n:
                break
            chief, text = rng.choice(_INTAKE_POOL[cat])
            age = (rng.randint(2, 14) if cat == "pediatrics" else rng.randint(19, 88))
            text = text.format(age=age, m=rng.randint(10, 90), d=rng.randint(1, 12))
            red = cat == "emergency"
            urgency = {"emergency": 3, "internal": rng.choice([1, 2]),
                       "dermatology": rng.choice([0, 1]), "pediatrics": rng.choice([0, 1, 2])}[cat]
            out.append(_rec(i, "INT", {
                "age": age, "chief_complaint": chief, "note": text,
                "arrived_by": rng.choice(["walk-in", "ambulance", "referral"]) if red else "walk-in",
            }, {"red_flag": red, "department": cat, "urgency": urgency}))
            i += 1
    rng.shuffle(out)
    for j, r in enumerate(out):
        r["ref"] = f"INT-{j + 1:04d}"
    return out[:n]


# ---------------------------------------------------------------------------
# 9 · News dedup & relevance (NLI-native)
# ---------------------------------------------------------------------------
_EVENT_POOL = [
    ("EU agrees landmark carbon border tax extension",
     "EU member states agreed on Friday to extend the carbon border adjustment mechanism to cover additional sectors from 2028, after marathon negotiations in Brussels. Officials called it a decisive step for climate policy fairness.",
     "Brussels extends landmark carbon border levy to new sectors",
     "Negotiators in Brussels reached a deal on Friday expanding the EU's carbon border tax to further industries starting 2028, a move framed as leveling the playing field on climate policy."),
    ("TSMC breaks ground on Dresden fab expansion",
     "TSMC began construction of a second fabrication plant in Dresden on Monday, doubling its European semiconductor capacity by 2029 in a 12 billion euro project backed by German subsidies.",
     "Chip giant TSMC starts building second Dresden factory",
     "Work started Monday on TSMC's new Dresden wafer fab, a 12bn euro expansion that will double the company's European chip output by the end of the decade, with Berlin funding support."),
    ("Wildfire forces evacuations near Porto",
     "A fast-moving wildfire south of Porto forced 3,000 residents to evacuate over the weekend as temperatures hit 43C; two villages were destroyed and 40 firefighters were injured.",
     "Thousands evacuated as wildfire ravages villages near Porto",
     "Portuguese authorities evacuated about 3,000 people near Porto as a wildfire destroyed two villages in 43C heat, injuring dozens of firefighters over the weekend."),
    ("WHO updates pandemic treaty financing terms",
     "The World Health Assembly adopted new financing terms for the pandemic treaty on Wednesday, committing member states to a tiered contribution model and a pathogen-sharing framework.",
     "WHO member states adopt new pandemic treaty funding rules",
     "On Wednesday, WHO members agreed on tiered contributions and pathogen-access provisions that reshape financing of the global pandemic treaty."),
    ("Global shipping rates fall for sixth straight month",
     "Container freight rates declined again in August, the sixth consecutive monthly fall, as new vessel capacity absorbed post-pandemic demand; the drawdown eased inflation pressure on goods.",
     "Freight rates slide again as container capacity glut persists",
     "Shipping costs dropped for a sixth straight month in August because a wave of new container ships met softer demand, giving goods inflation further room to cool."),
]
_UNRELATED = [
    ("Local council approves new cycling lanes", "The city council voted 31-9 to build 40 km of protected cycling lanes over three years, funded by the municipal transport budget."),
    ("Studio announces sequel to hit adventure game", "The studio confirmed a sequel to its best-selling adventure title, slated for next autumn, with the original creative team returning."),
    ("National team names squad for friendly", "The head coach named a 26-player squad for next month's friendly, including two uncapped teenagers from the youth academy."),
]
_PORTFOLIO = "climate policy and semiconductor supply chains"


def gen_news_dedup(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        same = i % 2 == 0
        if same:
            ha, ba, hb, bb = rng.choice(_EVENT_POOL)
            relevant = True   # portfolio events are in-topic by construction
            newsw = rng.choice([1, 2])
        else:
            (ha, ba), (hb, bb) = rng.sample(_UNRELATED, 2)  # distinct: identical text would be same-event
            relevant = False
            newsw = 0
        out.append(_rec(i, "NWS", {
            "article_a_headline": ha, "article_a_body": ba,
            "article_b_headline": hb, "article_b_body": bb,
            "portfolio": _PORTFOLIO,
        }, {"same_event": same, "relevant": relevant, "newsworthiness": newsw}))
    return out


# ---------------------------------------------------------------------------
# 10 · Log/alert noise reduction
# ---------------------------------------------------------------------------
_LOG_POOL = {
    "error": [
        "FATAL {svc}: database connection pool exhausted, all {n} connections busy, requests failing",
        "ERROR {svc}: unhandled exception in payment webhook processor: NullPointerException at PaymentHandler.java:{n}",
        "CRITICAL {svc}: disk usage on /var/lib/data at 97%, writes will fail within minutes",
        "ERROR {svc}: primary node lost quorum, cluster degraded, automatic failover triggered",
    ],
    "warn": [
        "WARN {svc}: request latency p99 at {n}ms exceeds SLO of 400ms for the last 5 minutes",
        "WARN {svc}: retrying upstream call to billing-api (attempt 2/3) after timeout",
        "WARN {svc}: certificate for api.{dom} expires in {n} days",
        "WARN {svc}: cache hit ratio dropped to 62%, expected > 90%",
    ],
    "info": [
        "INFO {svc}: deployment v2.{n}.0 rolled out to 12/12 pods, health checks green",
        "INFO {svc}: nightly backup completed in {n}s, {n2} GB archived",
        "INFO {svc}: autoscaler added 2 replicas, current desired=6",
        "INFO {svc}: configuration reloaded from consul, {n} keys updated",
    ],
    "noise": [
        "DEBUG {svc}: heartbeat ok",
        "TRACE {svc}: entering method processItem with args=[]",
        "DEBUG {svc}: GET /healthz 200 {n}ms (probe)",
        "TRACE {svc}: gc pause 3ms",
        "DEBUG {svc}: connection keep-alive ping",
    ],
}


def gen_log_noise(rng: random.Random, n: int) -> list[dict]:
    cats = list(_LOG_POOL)
    doms = ["internal", "example.com", "corp.local"]
    svcs = ["orders-api", "auth-svc", "ingest-worker", "checkout-web", "kafka-bridge", "cron-runner"]
    out = []
    for i in range(n):
        cat = cats[i % len(cats)]
        line = rng.choice(_LOG_POOL[cat]).format(
            svc=rng.choice(svcs), n=rng.randint(2, 999), n2=rng.randint(10, 900),
            dom=rng.choice(doms))
        level = {"error": rng.choice(["ERROR", "FATAL", "CRITICAL"]),
                 "warn": "WARN", "info": "INFO", "noise": rng.choice(["DEBUG", "TRACE"])}[cat]
        page = cat == "error" or (cat == "warn" and rng.random() < 0.25)
        severity = {"error": rng.choice([2, 3]), "warn": 1, "info": 0, "noise": 0}[cat]
        out.append(_rec(i, "LOG", {
            "service": line.split()[1].rstrip(":"), "level": level, "line": line,
            "occurrences_last_hour": rng.randint(1, 50) if cat in ("noise", "info") else rng.randint(1, 12),
        }, {"category": cat, "needs_page": page, "severity": severity}))
    return out


# ---------------------------------------------------------------------------
# 11 · Insurance FNOL fast-track
# ---------------------------------------------------------------------------
_FNOL_POOL = {
    "fast": [
        ("Windshield chip from highway debris", "Single-vehicle incident on the highway; small chip in the windshield from debris. Photos attached, police not involved, estimate EUR 180 from partner garage."),
        ("Hail damage to parked car", "Car was parked during the hailstorm on {date}; dents on roof and hood. Multiple neighbours affected, weather report attached, estimate EUR 950."),
        ("Bicycle theft from locked storage", "Bicycle (value EUR 600, receipt available) stolen from locked building storage between Monday and Wednesday. Police report filed, number {n}."),
    ],
    "standard": [
        ("Rear-ended at traffic light", "Stopped at a red light when another car hit the rear bumper. Police report filed, other driver admitted fault, repair estimate EUR 2,400, no injuries."),
        ("Kitchen water leak damage", "Washing machine hose burst while away for the weekend; kitchen and hallway floor damaged. Plumber invoice and photos attached, estimate EUR 6,800."),
        ("Fender bender in parking garage", "Low-speed collision reversing out of a parking spot. Both drivers exchanged details, damage to rear quarter panel, estimate EUR 1,100."),
    ],
    "suspicious": [
        ("Multiple electronics lost in 'burglary'", "Reports burglary of the apartment on {date}; items taken: 3 laptops, 6 phones, 2 consoles, jewelry, total claimed EUR 31,000. No forced entry visible, receipts 'lost', third claim this policy year."),
        ("Fire in rented warehouse - stock only", "Fire damaged rented warehouse on {date}; claim covers only stock (EUR 240,000 of electronics), no equipment. Policy started 6 weeks ago, rent was 3 months in arrears, insured declined fire brigade report copy."),
        ("Stolen car reported right after missed payment", "Vehicle reported stolen on {date}, two days after the third payment reminder. GPS shows the car crossed the border the previous night. Claim amount EUR 45,000, sole owner just changed."),
    ],
}


def gen_fnol_fasttrack(rng: random.Random, n: int) -> list[dict]:
    kinds = ["fast", "standard", "suspicious"]
    out = []
    for i in range(n):
        kind = kinds[i % len(kinds)]
        title, note = rng.choice(_FNOL_POOL[kind])
        note = note.format(date=f"2026-0{rng.randint(1, 9)}-{rng.randint(10, 28)}",
                           n=rng.randint(100000, 999999))
        truth = {
            "fast": dict(fraud_suspicion=False, fast_track=True, queue="fast_track",
                         severity=rng.choice([0, 1])),
            "standard": dict(fraud_suspicion=False, fast_track=False, queue="standard", severity=1),
            "suspicious": dict(fraud_suspicion=True, fast_track=False, queue="siu", severity=2),
        }[kind]
        out.append(_rec(i, "CLM", {
            "policy": f"POL-{rng.randint(100000, 999999)}", "incident_title": title,
            "reporter_note": note,
            "claimed_amount_eur": {"fast": rng.randint(120, 1200), "standard": rng.randint(900, 9000),
                                   "suspicious": rng.randint(20000, 250000)}[kind],
            "days_since_incident": rng.randint(0, 40),
            "claims_last_12_months": {"fast": rng.randint(0, 1), "standard": rng.randint(0, 2),
                                      "suspicious": rng.randint(2, 4)}[kind],
        }, truth))
    return out


# ---------------------------------------------------------------------------
# 12 · Survey verbatim coding
# ---------------------------------------------------------------------------
_VERBATIM_POOL = {
    "price": [
        "The price went up 30% this year while the product stayed the same. That feels greedy and I am reconsidering the renewal.",
        "Your competitor offers the same features for half the price. Unless pricing changes we will move at contract end.",
        "Honestly the value is there but the add-on fees (support, storage) make the real cost hard to predict. Publish a clear total price.",
    ],
    "quality": [
        "Build quality slipped badly - the hinges on my unit broke within two months of normal use.",
        "The latest update introduced constant crashes; earlier versions were rock solid. Feels like QA was skipped.",
        "Materials feel premium and it has survived a year of daily use and travel without a scratch.",
    ],
    "support": [
        "Support took nine days to answer a billing question and then sent a canned reply. Unacceptable for a paid plan.",
        "The support engineer stayed on chat until my issue was fully fixed, then followed up next day to check. Rare and appreciated.",
        "Your knowledge base is outdated - three of the top articles describe menus that no longer exist.",
    ],
    "shipping": [
        "Order arrived two weeks late with no tracking updates, and the box was crushed. The product inside was fine but the experience was poor.",
        "Fast delivery, good packaging, carbon-neutral option at checkout - exactly what I want from a modern store.",
        "Returns are painfully slow: I sent the item back 18 days ago and the refund still shows 'processing'.",
    ],
    "other": [
        "Would love a dark mode for the mobile app, the white screen at night is harsh.",
        "Please add CSV export to the reports page, we currently screenshot numbers into spreadsheets.",
        "The onboarding wizard is excellent - had my team set up in under an hour.",
    ],
}


def gen_survey_coding(rng: random.Random, n: int) -> list[dict]:
    cats = list(_VERBATIM_POOL)
    out = []
    for i in range(n):
        cat = cats[i % len(cats)]
        text = rng.choice(_VERBATIM_POOL[cat])
        actionable = cat != "other" or rng.random() < 0.5
        low = text.lower()
        intense = any(m in low for m in ["unacceptable", "greedy", "will move", "painfully",
                                         "constantly", "crushed", "30%"])
        out.append(_rec(i, "SRV", {
            "survey_question": "What is the one thing we should improve, and why?",
            "verbatim": text,
            "respondent": f"R-{rng.randint(1000, 9999)}",
            "nps_score": rng.randint(0, 4) if intense else rng.randint(4, 10),
        }, {"theme": cat, "actionable": actionable, "intensity": 2 if intense else rng.choice([0, 1])}))
    return out


# ---------------------------------------------------------------------------
GENERATORS = {
    "ticket_triage": gen_ticket_triage,
    "phishing_guard": gen_phishing_guard,
    "content_moderation": gen_content_moderation,
    "review_intel": gen_review_intel,
    "resume_screen": gen_resume_screen,
    "contract_guard": gen_contract_guard,
    "payments_fraud": gen_payments_fraud,
    "intake_triage": gen_intake_triage,
    "news_dedup": gen_news_dedup,
    "log_noise": gen_log_noise,
    "fnol_fasttrack": gen_fnol_fasttrack,
    "survey_coding": gen_survey_coding,
}
