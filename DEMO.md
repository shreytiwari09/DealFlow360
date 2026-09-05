# DealFlow360 — Demo Script

Flows 1-3 were verified on 2026-09-05 by driving the real API (56/56 checks)
and the real UI headlessly. Flows 4-6 were added on 2026-09-06 once
fulfillment, billing and the customer portal were built, each verified the
same way (86, 40 and 29 live-API checks respectively — see
`IMPLEMENTATION_LOG.md` for the exact entries). Nothing here is aspirational —
if it is written below, it runs.

**What is NOT built yet is listed in Section 9.** Read it before you demo, so
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
private) for Flows 1-5 — one will be the **Sales Rep**, the other whichever
approver a flow needs (Sales Manager, then Finance). A third window (or a
third private/incognito profile) is only needed for Flow 6, signed in as the
**Customer**, since a portal session and an internal session must never share
a browser profile — they are genuinely separate accounts with separate
permissions, not the same login viewed differently.

**Logins** — the login screen is a plain email/password form (no click-to-fill
buttons; those were removed once this stopped being a first-pass demo build).
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
> decides who has to approve it, and routes it there automatically — and the
> same order can carry hardware, a subscription, a warehouse split and a
> customer negotiation, all reconciled on one document.

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

## 5. Flow 4 — confirm → automatic warehouse split → accept

**Uses the demo's own staged stock numbers.** About 2 minutes. Continues from
any confirmed-eligible quote, or build a fresh one.

**As the Sales Rep:**

1. **+ New Quotation** → add **Business Laptop 14″**, quantity **10**, discount `0`.
   → No breach, so **Submit for Approval** sends it straight to `sent`.
2. Click **Confirm Quotation**. You are taken to the **Fulfillment Detail**
   screen, which auto-generates a suggested split the moment it opens — there
   is no separate "compute" button to remember.

**Stop here and talk.** The screen shows, exactly:

| Warehouse | Qty fulfilled |
|---|---|
| Main Warehouse | **6 units** |
| East Depot | **3 units** |
| *Backorder* | **1 unit outstanding** |

> Say: *"Main only had 6, East had 3. The system split across both rather than
> failing the whole order, and the last unit is a tracked backorder, not a
> silent shortfall. Stock is reserved the moment this split is generated, not
> when someone clicks Accept — that's what stops two confirmations racing for
> the same last unit."*

**As Finance** (sign in as `finance@dealflow360.example`):

3. Open the same order under **Fulfillment** → **Accept Suggested Split**.
4. The status badge updates to **Partially Fulfilled** (not "Fulfilled" — one
   unit is still on backorder).

> Say: *"If they ask about Manual Override — Finance can redistribute the
> split across warehouses by hand, and the backend re-validates live stock so
> an override can't oversell either."*

---

## 6. Flow 5 — a hybrid order: one-time hardware + a subscription, billed correctly

**Shows PRD B7's core claim — one time and recurring lines reconciled on a
single order.** About 2 minutes.

**As the Sales Rep:**

1. **+ New Quotation** → add **27″ 4K Monitor** (one-time), discount `0`.
2. Add **Premium Support Plan** — this is a subscription product, so a
   **Plan** column appears on its row. Choose **Premium Support (Monthly)**.
3. **Submit for Approval** (no breach → `sent`), then **Confirm Quotation**.

> Say: *"Confirming an order is the one trigger point that unlocks both
> fulfillment and billing — the same instant a warehouse split gets suggested,
> a one-time invoice line and a recurring subscription both get created."*

**As Finance:**

4. Open **Subscriptions** in the sidebar. The new subscription is there:
   quantity, plan, current billing cycle.
5. Open **Invoices**. Two rows exist for this order — one `one_time`, one
   `recurring` — both `Scheduled`.
6. Click the one-time row → **Issue Invoice** (assigns an invoice number) →
   **Record Payment** → status becomes **Paid**.

> Say: *"If they ask about mid-cycle changes: Modify Subscription re-prices
> the remainder of the current cycle on a strict daily basis and records every
> input alongside the result — old amount, new amount, days remaining, credit,
> charge — not just the final number, because a billing dispute needs the
> whole calculation, not just its answer. Cancel triggers the same kind of
> credit note automatically, governed by the plan's own refund policy."*

---

## 7. Flow 6 — customer negotiates a discount, quote re-enters approval automatically

**PRD B8's whole point.** About 2 minutes. Needs a third window/profile signed
in as the customer.

**As the Sales Rep:**

1. **+ New Quotation** → add **Onboarding & Setup Service**, discount `5`
   (compliant — Services' ceiling is 10%). Submit → straight to `sent`.

**As the Customer** (`portal@acme.example`, third window):

2. Sign in. You land on **My Quotations** — a portal with no sidebar, no
   internal navigation, just this order.
3. Open it. Add a comment (*"Can we get 20% instead?"*), set **Counter
   Discount %** to `20`, click **Submit Request**.
   → Status becomes **Under Negotiation**.
4. Click **Confirm Quotation**.

> Say: *"20% against Services' 10% ceiling breaches policy — so confirming
> doesn't confirm anything yet. It automatically re-enters the exact same
> approval flow Screen 6 uses for an internal submission."* The customer sees
> a message saying so, and their status stays **Under Negotiation** — they are
> never shown the internal "Pending Approval" state.

**As the Sales Manager:**

5. Open **Approvals**. The new request is there. Open it — the audit trail
   shows *"customer confirmed negotiated terms; re-entered approval"*, so it's
   visibly not a first-time submission.
6. **Approve** with a reason.

**As the Customer again:**

7. Click **Confirm Quotation** once more.
   → This time it goes straight through to **Confirmed** — the system
   recognises these exact terms were just approved and does not send it back
   to the same manager a second time.

> Say: *"That last step is the subtle part. Re-scoring on every confirm is
> correct, but re-scoring alone would mean a quote that was ever approved
> could never actually be confirmed — it would always still 'breach policy'
> because nothing about it changed. The system checks whether an approval
> already covers these exact terms, not just whether they'd currently pass."*

---

## 8. Security — 60 seconds, do this if asked about RBAC

All verified:

| Demonstration | Result |
|---|---|
| Sign in as the **rep**, look at an approval | No Approve button — and the API returns **403** if called directly |
| **Finance** tries to approve before the Manager | **403** — steps are sequential |
| Sign in as the **customer** (`portal@acme.example`) | Lands on the portal, **never** the internal shell |
| An internal user calls a `/portal/*` route directly | **403** — a genuinely separate, permission-gated surface, not a filtered view |
| Customer opens another company's quotation | **404** — existence itself is not revealed to someone who can't see it |
| A rep tries the Admin-only confirm override | **403** — `deal.confirm_override` is seeded to Admin alone |
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

## 9. What is NOT built — say this before they find it

Be upfront. The sidebar deliberately shows these greyed out rather than as
links that go nowhere.

| Area | State |
|---|---|
| **Deal health dashboard** | Schema only; anomaly thresholds deliberately not yet defined (a real, open decision — not an oversight). |
| **Reports / exports** | Not started. |
| **Admin config screens** | Discount tiers and approval chains are configurable **as data** via the API and seeded; no UI to edit them yet. |
| **Product catalogue screens** | Products are seeded and used everywhere; no admin UI to create/edit one. |
| **Automatic backorder consolidation** | The action exists (`Consolidate` on Screen 8); nothing yet watches for a restock and surfaces the prompt unprompted — needs a background job. |
| **Automatic subscription renewal** | A subscription's billing cycle does not roll forward on its own once it ends; needs a scheduler. |

> Say: *"Everything in the PRD's Core classification is built and tested end
> to end — quotation, approval routing, fulfillment, hybrid billing, and the
> customer portal all work against the real API, not a mock. What's left is
> Supporting scope: dashboards and admin screens over data that's already
> correctly modelled and enforced underneath."*

---

## 10. If they ask "what is actually hard here?"

Four honest answers, all defensible:

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

**Re-approval has to check "was this approved," not "does this pass."** A
quotation approved at 18% still scores as breaching policy forever afterward —
nothing about it changed. If confirming re-checked the score alone, no
quotation that ever needed approval could ever be confirmed; it would bounce
back to the same approver endlessly. The system instead checks whether an
`ApprovalRequest` already covers these exact terms (same blended score, same
max line excess) before deciding whether to route it again.

---

## 11. Numbers worth memorising

| | |
|---|---|
| Gold tier ceilings | Hardware **15%**, Services **10%**, Subscriptions **8%** |
| PRD example | Laptop 12% (OK) + Service 18% (8 pt over) → score **1.33** → Manager |
| Finance escalation | Laptop 35% = 20 pt over → gate at 15 → **Manager + Finance** |
| Warehouse split | 10 laptops ordered → **6 from Main + 3 from East + 1 backordered** |
| Proration (locked formula) | 1200/mo → 1800/mo, day 10 of 30 → credit 800.00, charge 1200.00, **+400.00** |
| Schema | 30 tables, 70+ foreign keys, 2 migrations |
| Tests | 197 automated, plus 56 + 51 + 40 + 29 + 9 end-to-end API checks across every feature |

---

## 12. If something breaks live

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
