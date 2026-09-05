# DealFlow360 — Security Specification

## Purpose
This is the implementation contract for security across DealFlow360. Treat it as an engineering specification, not optional advice. Consolidated from the project's two source security documents — using the role model that actually matches the PRD (Sales Rep, Sales Manager/Approver, Finance/Operations User, Customer, Admin), not the generic placeholder roles from an earlier draft.

**Non-negotiables:**
- Do NOT weaken core security merely to make a demo work.
- Do NOT introduce unnecessary enterprise infrastructure that makes local setup difficult.
- Do NOT duplicate authentication/authorization logic in multiple inconsistent places.
- Backend enforcement is authoritative. Frontend controls are UX only.
- Never hardcode secrets. Never log passwords, OTPs, tokens, or DB credentials.

---

## 1. Architecture Overview (defense in depth)

```
Browser / Frontend
      | HTTPS in production
      v
Backend / API
      +--> Rate Limiter
      +--> Authentication (password hash, MFA, JWT/session)
      +--> Authorization / RBAC (role -> permission -> resource ownership)
      +--> Input Validation
      +--> Business Rules
      +--> Audit Events
      v
PostgreSQL
      +--> Constraints, Referential Integrity
      +--> Least-privilege DB roles
      +--> Indexes / query safety
```

---

## 2. Environment Model

Support development / test / production, with explicit config per environment.

**Development:** localhost frontend/backend/Postgres; Redis only if a feature genuinely needs it; local HTTP is fine; production-only HTTPS/HSTS must never block local runs. Core controls (hashing, auth, validation, SQL-injection protection, audit logging) stay ON even in dev.

**Production:** HTTPS + HSTS, secure cookies, restricted DB/Redis, strict CORS allowlist, real secrets, backups, monitoring.

**Local dev must just work:** provide `.env.example`, clear README steps, a migration command, a seed-data command, and a health-check endpoint. No hardcoded machine-specific paths/ports/credentials. Redis must NOT be a mandatory startup dependency unless a shipped feature genuinely uses it.

---

## 3. Authentication

**Registration:** validate + normalize email, enforce uniqueness, enforce password policy, hash with Argon2id or bcrypt (appropriate work factor), never return hashes to frontend, never expose raw DB errors.

**Login:** validate credentials backend-side, generic failure messages (never reveal if an account exists), rate-limit failures, log security-relevant events, never log credentials.

**MFA (if implemented):** enforced server-side; never trust a frontend-only `mfaVerified` flag; protect against bypass, OTP replay/guessing, and session creation before MFA completes.

**Password reset:** short-lived single-use tokens, invalidate after use, don't reveal account existence, don't log raw tokens.

**Session/token model — choose ONE and apply consistently:**

If JWT: short-lived access token, strong signing secret, algorithm explicitly whitelisted (reject `alg:none`, prevent algorithm confusion), validate `exp`/`iss`/`aud`/`nbf`, rotate refresh tokens, detect refresh-token reuse, never trust client-supplied claims.

If cookie session: `HttpOnly`, `Secure` in production, correct `SameSite`, rotate session on login, server-side invalidation on logout.

Logout must invalidate the relevant server-side refresh/session state.

---

## 4. Authorization / RBAC — Actual DealFlow360 Roles

The application has exactly these five roles (this is the authoritative list — do not substitute a generic role set):

1. **Sales Rep** — own quotations/lines, own activities, actions allowed by workflow. Should NOT access other reps' quotations, finance-only actions, or admin controls.
2. **Sales Manager / Approver** — team-level quotations, approval workflows, manager reports, discount-tier/approval-chain configuration.
3. **Finance / Operations User** — second-level approval on high-risk discounts, fulfillment/backorder decisions, billing reconciliation. Do not expose unrelated sales/admin controls.
4. **Customer (Portal User)** — own quotation only, own negotiation actions. Must never access another customer's records or any internal screen.
5. **Admin** — full system administration, user/role management, security config. Admin actions must still be audited, not exempt from logging.

**Authorization must check, in order:** authenticated identity → role → requested action → target resource → ownership/scope → business state → approval requirements.

**Protect against:** IDOR, BOLA (broken object-level authorization), horizontal privilege escalation (rep accessing another rep's quote), vertical privilege escalation (rep performing manager/finance actions), role tampering, forged owner/customer IDs.

**Never trust client-provided:** `userId`, `ownerId`, `role`, `customerId`, approval status, privilege flags. Always derive these from authenticated server-side context.

**Recommended permission model** (not hardcoded `if role == "manager"` checks):

```
users -> role_id -> roles -> role_permissions -> permissions
```

Example permissions: `deal.create`, `deal.update_own`, `deal.approve_manager`, `deal.approve_finance`, `deal.assign`, `portal.own_quote.view`, `portal.own_quote.negotiate`, `user.manage`, `report.view`, `audit.view`.

**Resource-level check example:** a Sales Rep with `deal.update_own` attempting to edit Quotation #101 must be checked not just for the permission, but for whether #101 is actually assigned to them — this is what prevents one rep editing another's quote by changing an ID in the URL.

---

## 5. API / Backend Security

- Validate every external input (body, query params, path params, headers where relevant); use allowlists for sortable/filterable fields.
- Parameterized queries / ORM only — never string-concatenated SQL.
- Reasonable request size limits (body, JSON payload, pagination).
- Rate-limit login, registration, password reset, MFA verification, and any expensive/report-generating endpoints.
- Never expose stack traces, SQL, DB credentials, internal paths, or secrets in API error responses — log details securely instead.
- CORS: explicit allowlist in production; never combine wildcard origin with credentialed requests.

---

## 6. PostgreSQL Security

- Application DB user has least-privilege access — never run as Postgres superuser.
- All queries parameterized/ORM-safe.
- Use PRIMARY KEY, UNIQUE, NOT NULL, CHECK, FOREIGN KEY constraints as defense in depth — business invariants must not rely on frontend validation alone.
- Choose FK delete behavior deliberately (RESTRICT / CASCADE / SET NULL) per relationship — don't accidentally cascade-delete quotations, approvals, or audit records.
- Row Level Security (RLS) may be added as defense-in-depth on sensitive multi-tenant tables (e.g., quotations by customer) — but backend authorization remains mandatory regardless; RLS does not replace it.
- Never return password hashes, reset tokens, MFA secrets, or internal audit metadata in API responses — use explicit response DTOs.
- Bounded connection pools; indexes on auth lookups, foreign keys, ownership queries, quotation status/date, and approval-chain lookups. Don't blindly index every column.

---

## 7. Frontend / Browser Security

Frontend is never a trusted security boundary.

- Prevent XSS (reflected/stored/DOM) — never insert untrusted strings into raw HTML; sanitize any intentionally rendered rich content.
- Prefer secure HttpOnly cookies over `localStorage` for session/refresh credentials unless there's a strong specific reason otherwise. Never store passwords, MFA secrets, or DB credentials in browser storage.
- If cookie-based auth: implement CSRF protection, correct `SameSite`, validate origin/referer for state-changing requests.
- Use a reasonable Content-Security-Policy in production; don't weaken it just to make an arbitrary script work.
- Never ship DB credentials, private API keys, or signing secrets into frontend bundles — anything sent to the browser is public.

---

## 8. Additional Hardening

**Mass assignment:** never map arbitrary request JSON directly onto DB entities — a profile update must not silently allow `{"role": "Admin"}` unless that field is explicitly whitelisted for that endpoint.

**Prototype pollution / unsafe merging:** protect fields like `role`, `permissions`, `ownerId`, `status`, `approvalState`, `customerId` from being overwritten by unvalidated merged objects.

**Open redirects:** never redirect to an arbitrary client-supplied URL — allowlist trusted destinations only.

**Secrets management:** never commit `.env` with real values, DB passwords, JWT secrets, or API keys. `.env.example` contains placeholders only.

**File uploads (if applicable):** validate type/extension/MIME/size, generate safe server-side filenames, prevent path traversal, enforce download authorization per file.

---

## 9. JWT-Specific Attack/Defense Reference

| Attack | Defense |
|---|---|
| `alg:none` acceptance | Explicit algorithm whitelist server-side |
| Algorithm confusion (symmetric/asymmetric mixup) | Fixed algorithm + matching key type; don't select algorithm from the token header |
| Weak HS256 secret / offline brute force | 256-bit+ cryptographically random secret, or use asymmetric (RS256) signing |
| Token replay | Short-lived access token (5–15 min) + refresh-token rotation |
| Token/session hijacking | Secure storage/transmission, short lifetime, revocation, HTTPS |
| JWT payload disclosure (it's Base64, not encrypted) | Treat payload as non-secret; only `sub`, role/permission IDs, `iat`, `exp` — never PII or secrets |
| Expired token still accepted | Always validate `exp` (and `iss`/`aud`/`nbf` where relevant) |
| Wrong issuer/audience accepted | Validate `iss` and `aud` against expected DealFlow360 values |
| Brute-force login | Rate limiting, throttling, MFA, audit logging |
| Credential stuffing | MFA, rate limiting, monitoring for unusual login patterns |
| Authorization bypass (valid JWT, wrong permission) | Authentication must always be followed by an explicit permission check |
| IDOR (`/deals/101` → `/deals/102`) | Backend resource-ownership check on every request, not just a permission check |

---

## 10. Audit Logging

Recommended `audit_logs` fields: `id, user_id, action, resource, resource_id, status, ip_address, timestamp`.

Minimum events to log: `LOGIN_SUCCESS`, `LOGIN_FAILED`, `MFA_FAILED`, `QUOTATION_CREATED`, `QUOTATION_UPDATED`, `DISCOUNT_APPROVAL_REQUESTED`, `DISCOUNT_APPROVED`, `DISCOUNT_REJECTED`, `ROLE_CHANGED`, `UNAUTHORIZED_ACCESS_ATTEMPT`.

This is both a security control and an explicit PRD requirement (every approval/rejection/edit must be logged with user, timestamp, and reason).

---

## 11. Pre-Submission Security Checklist

- [ ] Passwords hashed with Argon2id/bcrypt — never plaintext, never logged
- [ ] JWT algorithm explicitly whitelisted; `alg:none` rejected
- [ ] Access tokens short-lived; refresh tokens rotated
- [ ] JWT payload contains no PII/secrets
- [ ] `exp`, `iss`, `aud` validated on every request
- [ ] Login/reset/MFA endpoints rate-limited
- [ ] All 5 roles enforced server-side (not just hidden in UI)
- [ ] Resource-ownership checked on every quotation/approval endpoint (rep-owns-quote, customer-owns-quote)
- [ ] No client-supplied `role`/`ownerId`/`customerId` trusted without server-side derivation
- [ ] All approval/rejection/edit actions written to `audit_logs`
- [ ] CORS explicit allowlist (no wildcard + credentials)
- [ ] No secrets committed; `.env.example` has placeholders only
- [ ] DB queries parameterized/ORM-only; no string-built SQL
- [ ] API error responses don't leak stack traces/DB details
