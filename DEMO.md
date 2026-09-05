# DealFlow360 — Demo Script

Everything in this file was verified working on 2026-09-05 by driving the real
API (56/56 checks) and the real UI headlessly. Nothing here is aspirational —
if it is written below, it runs.

**What is NOT built yet is listed in Section 6.** Read it before you demo, so
you are never surprised by a question.

---

## 0. Before the interview — 2 minutes

```bash
cd DealFlow360
docker compose up -d
```

Wait for all three services, then **reset to clean demo data**:

```bash
docker compose exec db psql -U dealflow -d dealflow360 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.seed
```

Check it is up:

```bash
curl http://localhost:8000/api/v1/health/ready
# {"status":"ok","environment":"development","database":"ok"}
```

Open **http://localhost:5173** in two browser windows (or one normal + one
private). One will be the **Sales Rep**, the other the **Sales Manager**. That
avoids signing in and out mid-demo, which is where live demos die.

**Logins** — the login screen has click-to-fill buttons for all of these.
Password for every account: `DealFlow360!demo`

| Role | Email |
|---|---|
| Sales Rep | `rep@dealflow360.example` |
| Sales Manager | `manager@dealflow360.example` |
| Finance / Ops | `finance@dealflow360.example` |
| Admin | `admin@dealflow360.example` |
| Customer (portal) | `portal@acme.example` |

---

## 1. The one-sentence pitch

> Most quoting tools check one discount limit for the whole order. DealFlow360
> checks **every line against its own limit** — because a Gold customer allowed
> 15% overall can still be given 18% on a thin-margin service line, and that is
> exactly the discount that quietly destroys margin. The system scores that,
> decides who has to approve it, and routes it there automatically.

---

## 2. Flow 1 — over-limit discount routes itself to a Manager

**This is the PRD's own worked example, reproduced exactly.** Roughly 2 minutes.

**As the Sales Rep:**

1. Sign in as the rep. You land on the **Sales Dashboard**.
2. Click **+ New Quotation**. A draft opens for Acme Corp.
3. From **Add a product**, choose **Business Laptop 14″**.
   → Order total and margin appear. Risk score is `0.00 LOW`.
4. Add **Onboarding & Setup Service**.
5. In the Laptop row, set **Discount** to `12`. Tab out.
6. In the Setup Service row, set **Discount** to `18`. Tab out.

**Stop here and talk.** The screen now shows:

| | |
|---|---|
| Order total | **₹1,23,192** |
| Live margin | **18.58%** (was 29.17%) |
| Blended risk score | **1.33 · MEDIUM** |
| Caption | *"Routes to Sales Manager"* |

- The **Laptop** row shows `12.00%` given, `15.00%` limit → **OK**.
- The **Setup Service** row shows `18.00%` given, `10.00%` limit → **OVER LIMIT**, 8.00 pt over.
- A **"Why this will be flagged"** panel appears on the right.

> Say: *"Both lines are under the customer's 15% Gold tier cap. But Services
> carries a stricter 10% ceiling because the margin is thinner. That one line
> is 8 points over its own limit, and that is what flags the whole quotation.
> The rep never asked for approval — the score decided."*

7. Click **Submit for Approval**. You are taken to the Approvals list.

**As the Sales Manager (second window):**

8. Sign in as the manager → **Approvals** in the sidebar.
9. The quotation is there, badged **MEDIUM**, stage *Sales Manager / Approver*.
10. Click the row. The **Approval Detail** shows:
    - Stepper: `Submitted → Sales Manager / Approver → Confirmed`
    - **Why this quote was flagged** — Laptop `12% vs 15% → 0 pt OK`, Setup Service `18% vs 10% → 8.00 pt OVER`
    - **Audit trail** — created, updated, approval requested, each with user, timestamp and reason
11. Type a reason (e.g. *"Margin acceptable for Gold renewal"*) and click **Approve**.
12. The quotation is now **approved**, and the audit trail has a new row with the manager's name.

> Say: *"A reason is mandatory. Every approval, rejection and edit is written to
> an append-only audit log — that is a PRD requirement and a security one."*

---

## 3. Flow 2 — a severe single line escalates to Finance

**This is the part that shows the two-step chain.** Roughly 2 minutes.

**As the Sales Rep:**

1. **+ New Quotation** → add **Business Laptop 14″**, quantity **2**.
2. Set **Discount** to `35`.

The screen shows:

| | |
|---|---|
| Blended risk score | **20.00 · HIGH** |
| Live margin | **−7.69%** (the deal now loses money) |
| Caption | *"Routes to Sales Manager → Finance Ops"* |
| Warning banner | *"One line is more than 15 points over its own limit, so this quotation needs Finance approval regardless of the blended score."* |

> Say: *"35% against a 15% ceiling is 20 points over. There is a guard rail: any
> single line more than 15 points over forces Finance escalation, whatever the
> blended average says. That closes the blind spot in a value-weighted average —
> one badly discounted small line inside a big clean order would otherwise be
> diluted into insignificance."*

3. Click **Submit for Approval**.

**As the Sales Manager:**

4. Open the approval. The stepper now has **two** steps:
   `Submitted → Sales Manager / Approver → Finance / Operations → Confirmed`
5. Approve with a reason.
6. **The quotation is still `pending_approval`.** The current stage moves to
   *Finance / Operations*.

> Say: *"Steps are sequential. Finance cannot approve before the Manager has —
> the backend returns 403 if they try."*

**As Finance** (sign in as `finance@dealflow360.example`):

7. Open the same approval → **Approve**.
8. Now the quotation is **approved**, and both steps show their actor's name.

---

## 4. Flow 3 — return for revision, and a compliant quote skipping approval

Fast, and it proves the loop closes. About 1 minute.

1. As the rep, build a quote with **Setup Service at 20%** and submit.
2. As the manager, click **Return for Revision** with a reason.
3. The quotation goes back to **draft** and the rep can edit it again.
4. As the rep, change the discount to **8%** → the OVER LIMIT badge disappears,
   score returns to `0.00`.
5. Submit. **The status goes straight to `sent` — no approval step at all.**

> Say: *"When nothing breaches a limit, the quote skips approval entirely. The
> point of the score is to stop managers reviewing every single quotation by
> hand."*

---

## 5. Security — 60 seconds, do this if asked about RBAC

All verified:

| Demonstration | Result |
|---|---|
| Sign in as the **rep**, look at an approval | No Approve button — and the API returns **403** if called directly |
| **Finance** tries to approve before the Manager | **403** — steps are sequential |
| Sign in as the **customer** (`portal@acme.example`) | Lands on the portal, **never** the internal shell |
| Customer opens another company's quotation | **403** |
| Wrong password / unknown email | Identical generic message — no user enumeration |

> Say: *"Authorization is permission-based, not `if role == manager`. And a
> permission alone is not enough on a resource route — a rep holding
> `deal.update_own` is still checked against whether they own **that**
> quotation. That is what stops changing the id in the URL."*

Extra credit if they press on it:

- Passwords are Argon2id. A login for an unknown email still runs a hash, so a
  missing account does not return measurably faster than a wrong password.
- JWT uses an explicit algorithm allowlist, so `alg:none` is impossible.
- Refresh tokens rotate, and replaying a rotated token revokes the whole family.
- Login is rate-limited.
- Every denied attempt is written to `audit_logs` as `UNAUTHORIZED_ACCESS_ATTEMPT`.

---

## 6. What is NOT built — say this before they find it

Be upfront. The sidebar deliberately shows these greyed out rather than as
links that go nowhere.

| Area | State |
|---|---|
| **Fulfillment / warehouse split** | Schema, stock and seed data exist (Laptop: 6 in Main, 3 in East). No API, no screen. |
| **Subscriptions & hybrid billing** | Full schema including proration records. No API, no screen. |
| **Invoices & payments** | Schema only. |
| **Customer portal negotiation** | Portal login works and is correctly restricted; the negotiation screen itself is a placeholder. |
| **Deal health dashboard** | Schema only; thresholds deliberately not yet defined. |
| **Reports / exports** | Not started. |
| **Admin config screens** | Discount tiers and approval chains are configurable **as data** and seeded; no UI to edit them yet. |
| **Order-level discount** | API endpoint works; no button in the builder yet. |

> Say: *"We built the spine end to end rather than every screen half-way. The
> data model covers all of it — 30 tables, migrated — and the two flows that
> demonstrate the actual business logic work completely."*

---

## 7. If they ask "what is actually hard here?"

Three honest answers, all defensible:

**The score is a weighted mean, so it can never exceed its worst line.**
That is why the `>15` single-line gate exists as a separate rule — without it,
one severely discounted small line inside a large compliant order gets diluted
and slips through.

**A breach must never round away.** One line a single point over its ceiling
inside a very large order produces a raw score around 0.0005, which rounds to
0.00 — a stored score claiming no breach on a quotation that has one. The
approval trigger therefore reads the unrounded per-line excess, and any
non-zero score is floored at 0.01.

**Prices and limits are snapshotted onto the line at quoting time.** Master
data changes. An approved quotation has to stay reproducible, and
`allowed_discount_percent` on the line answers the question an auditor actually
asks: *what was the policy when this was approved?*

---

## 8. Numbers worth memorising

| | |
|---|---|
| Gold tier ceilings | Hardware **15%**, Services **10%**, Subscriptions **8%** |
| PRD example | Laptop 12% (OK) + Service 18% (8 pt over) → score **1.33** → Manager |
| Finance escalation | Laptop 35% = 20 pt over → gate at 15 → **Manager + Finance** |
| Schema | 30 tables, 70 foreign keys, 2 migrations |
| Tests | 124 automated, plus 56 end-to-end API checks |

---

## 9. If something breaks live

```bash
docker compose restart backend
docker compose logs backend --tail 30
```

Full reset (destroys data, ~40 seconds):

```bash
docker compose down -v && docker compose up -d --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.seed
```

If the UI shows *"Your session has expired"*, just sign in again — access
tokens last 15 minutes and the refresh happens automatically, but a laptop
resumed from sleep can outrun it.
