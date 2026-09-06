# Deploying DealFlow360 — Render (backend + Postgres) + Vercel (frontend)

Two platforms, two different registrable domains — that matters here because
auth uses cookies. `backend/app/core/cookies.py` already accounts for this
(`SameSite=None; Secure` in production instead of `Lax`), so nothing below
needs a workaround for it. The real CSRF defense is the signed double-submit
token, not `SameSite` — see that file's docstring if you want the reasoning.

Deploy backend first, frontend second, then come back and fix up the
backend's CORS/frontend-URL settings once you know the real Vercel URL.

---

## 0. Prerequisites

- Push your latest commit to GitHub (`origin` is already set to
  `github.com/shreytiwari09/DealFlow360.git`) — both platforms deploy from
  the pushed branch, not from your local working copy.
- A [Resend](https://resend.com) account (free tier, 3,000 emails/month) —
  sign up, then **API Keys → Create API Key**. Copy it; you'll paste it into
  Render as `SMTP_PASSWORD`.
  - Without verifying your own domain in Resend, you can only send FROM
    `onboarding@resend.dev` and only TO the email address you signed up
    with. Fine for testing the deployed app yourself; verify a domain in
    Resend later if you need to actually invite other people's real
    addresses.
- A JWT signing secret: run
  `python -c "import secrets; print(secrets.token_urlsafe(48))"` locally and
  save the output — you'll paste it into Render as `JWT_SECRET_KEY`.

---

## 1. Backend + database — Render

1. Render dashboard → **New → Blueprint** → select the `DealFlow360` repo.
   Render finds `render.yaml` at the repo root automatically and shows you
   two resources: the `dealflow360-db` database and the `dealflow360-backend`
   web service.
2. It will prompt for the values marked `sync: false` in `render.yaml`:
   - `JWT_SECRET_KEY` → the value you generated above.
   - `SMTP_PASSWORD` → your Resend API key.
   - `CORS_ORIGINS` / `FRONTEND_BASE_URL` → leave blank for now (a
     placeholder like `https://placeholder.example` also works) — you don't
     know the real Vercel URL yet. **You will come back and fix these in
     step 3.**
3. Click **Apply**. Render builds the Docker image, provisions Postgres, and
   starts the service — on deploy it runs `alembic upgrade head` and the
   idempotent seed automatically (see `render.yaml`'s `dockerCommand`), so
   it comes up with a real schema and the same demo logins as local dev
   (`admin@dealflow360.example` / `DealFlow360!demo`, etc.).
4. Once it's live, copy the backend's public URL from the Render dashboard
   (`https://dealflow360-backend-XXXX.onrender.com` or whatever it assigned).
   You need this for step 2.

**Free tier note:** the web service spins down after 15 minutes of no
traffic and takes 30-60 seconds to wake back up on the next request — the
first load after idle will look like it's hanging. Not a bug; upgrading off
the free instance type removes this.

---

## 2. Frontend — Vercel

1. `vercel login` (already installed locally) if you haven't, or use the
   Vercel dashboard → **Add New → Project** → import the same GitHub repo.
2. **Root Directory: `frontend`** — this is the one setting that must not be
   left at the repo root, since the repo is backend+frontend together.
   Vercel auto-detects Vite once the root is set correctly (build command
   `npm run build`, output directory `dist` — leave both as detected).
3. Add one environment variable before deploying:
   - `VITE_API_BASE_URL` = the Render backend URL from step 1.4
     (e.g. `https://dealflow360-backend-xxxx.onrender.com`) — **no trailing
     slash**, and note this is baked in at BUILD time (Vite convention), so
     changing it later means redeploying, not just editing a running server.
4. Deploy. Copy the resulting Vercel URL
   (`https://dealflow360-xxxx.vercel.app` or your own custom domain if you
   attach one).

---

## 3. Close the loop — point the backend back at the real frontend URL

Back in the Render dashboard, on the `dealflow360-backend` service →
**Environment**:

- `CORS_ORIGINS` = the exact Vercel URL from step 2.4 (scheme + host, no
  trailing slash — e.g. `https://dealflow360-xxxx.vercel.app`). Multiple
  origins are comma-separated if you later add a custom domain too.
- `FRONTEND_BASE_URL` = the same URL — this is what gets used to build the
  `/activate/<token>` link in invitation emails.

Save → Render redeploys the backend automatically. Once that finishes, the
whole thing is live: open the Vercel URL, log in, and it should behave
exactly like your local `docker compose` stack.

---

## Troubleshooting

- **Login works but every reload bounces to `/login`, or you get CORS
  errors in the browser console:** `CORS_ORIGINS` on Render doesn't exactly
  match the Vercel URL (scheme, host, and NO trailing slash all have to
  match exactly), or step 3 hasn't been redeployed yet.
- **Database connection errors on first boot:** Render's managed Postgres
  internal connections (what `fromDatabase` wires up) don't require SSL by
  default, but if you see an SSL-related connection error, that's the first
  thing to check with Render's own docs for your plan/region — this hasn't
  come up in testing this Blueprint, but is the one part of this setup that
  couldn't be verified without an actual Render account.
- **Invitation emails aren't arriving:** check you're sending TO the same
  address you signed up to Resend with (see the Prerequisites note) —
  that's a Resend sandbox limitation, not an app bug. The invite still
  works either way; `email_sent: false` in the response means copy the
  `invite_url` and send it yourself.
- **Want stronger demo credentials than the seeded default:** set
  `SEED_DEFAULT_PASSWORD` on Render before the first deploy (the seed script
  reads it instead of the `DealFlow360!demo` default).

## What's deliberately NOT covered here

Restricting `ALLOW_PUBLIC_SIGNUP` before a real public launch, rotating
`JWT_SECRET_KEY`/`POSTGRES_PASSWORD` beyond what's needed for the demo, and
verifying a real sending domain in Resend are all real production-hardening
steps this guide skips — see `PROJECT_CONTEXT.md`'s "Deferred deliberately"
section for the full list of what's a known, disclosed gap versus what's
actually broken.
