# DeeptechIndia.in

A discovery platform for Indian deep-tech startups, with an investor workspace and a **private, paid ranking system** for featured placement.

**Stack:** HTML5 + CSS3 + vanilla JavaScript · Python Flask (Jinja2 + REST API) · SQLAlchemy + Flask-Migrate · PostgreSQL (SQLite for local development) · Razorpay (with a local sandbox simulator) · Gunicorn.

---

## 1. Quick start (local development)

```bash
cd deeptechindia
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt        # on Windows, gunicorn installs but only runs on Linux/macOS
cp .env.example .env                   # defaults work for local development

flask --app app db upgrade             # create the schema from migrations
flask --app app seed                   # load clearly-labelled SAMPLE data
flask --app app run --debug            # http://127.0.0.1:5000
```

Demo accounts created by `seed` (development only):

| Role | Email | Password |
|---|---|---|
| Admin | admin@deeptechindia.local | Admin@12345 |
| Startup owner (Akashdeep Aerospace) | founder@deeptechindia.local | Founder@12345 |
| Investor (Meru Ventures) | investor@deeptechindia.local | Investor@12345 |

`flask --app app seed --reset` wipes and reloads the sample data. Every company, person, investor and amount in the seed is **fictional**.

**Demo imagery.** Startup covers, product and gallery photos come from Wikimedia Commons (CC BY / BY-SA / CC0 / public domain, credited at `/credits` and in `static/images/photos/CREDITS.json`; re-fetch with `python tools/fetch_images.py`). Founder portraits are randomuser.me placeholders, and startup/investor logos are original demo marks from `tools/generate_logos.py`. Replace all of these with each company's own uploads before launch.

Without SMTP configured, verification and password-reset emails are written to the server log. In debug mode the link is also shown as a flash message.

### Try the bidding flow
1. Sign in as the founder and open **Manage Bids** (`/dashboard/bids`).
2. Click **Place Bid** on #1 or #2, accept the terms, then click **Pay**.
3. With `PAYMENT_PROVIDER=mock`, a sandbox checkout page opens. **Simulate successful payment** sends an HMAC-signed webhook through the same verification and processing code that production uses.
4. The result page polls until the webhook has been processed, and the board and public ranking update.

### Tests
```bash
pytest -q
```
76 tests cover team invites and roles, investor verification, data export and account deletion, end-to-end journeys (founder signup → review → bid → pay, investor introductions, profile editing, admin controls), authentication (hashing, verification, single-use reset links, open-redirect, CSRF, rate limiting), access control and IDOR, public-API data exposure, bid rules and idempotency, and payment handling (signature checks, duplicate and out-of-order webhooks, failed and retried payments, amount mismatches, simultaneous bids, late captures and expiry).

---

## 2. Project structure

```text
deeptechindia/
├── app.py                 # application factory, error handlers, security headers
├── config.py              # Development / Testing / Production config (env-driven)
├── extensions.py          # db, migrate, login_manager, csrf, limiter
├── commands.py            # flask seed | create-admin | bids maintain | payments reconcile
├── seed.py                # SAMPLE data
├── wsgi.py, gunicorn.conf.py, Dockerfile, docker-compose.yml
├── models/                # user, startup, founder, product, funding, investor, bid, payment, notification
├── routes/                # auth, startups, categories, funding, investors, dashboard, bidding, payments, admin
├── services/              # ranking_service, bidding_service, payment_service, notification_service, audit_service
├── utils/                 # security (RBAC, headers), uploads, validation, formatting
├── templates/             # one Jinja template per page + base/dashboard layouts
├── static/css/            # style.css (public), components.css (shared), dashboard.css (private app)
├── static/js/             # main, search, startup, bidding, investors, dashboard, auth
├── static/images/         # hero image, icon sprite, generated category covers
├── migrations/            # Alembic migrations
├── tools/generate_art.py  # regenerates the category cover illustrations
└── tests/
```

### Pages
`/` home · `/startups` directory · `/startups/<slug>` profile · `/categories`, `/categories/<slug>` · `/funding` · `/investors` (directory, or the workspace for investors) · `/startup/new` · `/dashboard`, `/dashboard/profile`, `/dashboard/payments`, `/dashboard/settings` · `/dashboard/bids`, `/dashboard/bids/review`, `/dashboard/bids/result/<id>`, `/dashboard/bids/history` · `/login`, `/register`, `/forgot-password`, `/reset-password/<token>` · `/admin`

### REST API (JSON)
| Method | Endpoint | Access |
|---|---|---|
| GET | `/api/startups`, `/api/startups/<slug>`, `/api/categories`, `/api/funding`, `/api/investors`, `/api/stats` | public |
| POST | `/api/startups` | startup owner |
| PUT | `/api/startups/<id>`, `/api/startups/<id>/funding` | that startup's members |
| POST/DELETE | `/api/startups/<id>/founders`, `/products`, `/gallery`, `/updates` | that startup's members |
| POST | `/api/startups/<id>/save` | signed in |
| GET | `/api/dashboard/bids`, `/api/bids/history`, `/api/bids/<id>` | owner (own startup only) |
| POST | `/api/bids`, `/api/bids/<id>/cancel`, `/api/payments/checkout` | owner (own startup only) |
| POST | `/api/payments/webhook` | payment provider (signature-verified) |
| GET/PUT | `/api/investors/me` | investor |
| POST | `/api/introduction-requests` | verified investor |
| PUT | `/api/introduction-requests/<id>` | the startup's members |
| GET/POST | `/api/notifications`, `/api/notifications/read` | signed in |

Public responses never include bid amounts, qualifying bids or bid history. `tests/test_access.py` checks this.

---

## 3. Teams, investor verification and personal data

- **Team members** (`/dashboard/team`): owners invite people by email. Invitations are single-use links valid for 7 days, and only a hash of the token is stored. Roles: **owner** (everything, including bids, payments and the team) and **editor** (company profile and introductions). A startup always keeps at least one owner. Accepting requires an account with the invited email address.
- **Investor verification** (`/admin#investors`): admins verify investor profiles. Founders see a "Verified investor" or "Unverified" badge on every introduction request.
- **Data rights (DPDP Act 2023)** (`/dashboard/settings`): *Download my data* exports everything held about the user as JSON. *Delete my account* (password plus typing DELETE) erases personal data and disables sign-in. A sole founder's startup is deleted, or unlisted if it has payment records, which are retained for tax law. Startups with teammates pass to them, with the earliest member promoted to owner if needed. The last administrator can't delete their account.

## 4. Private bidding system

**Model.** Each startup holds at most one *active* (confirmed, unexpired) bid. The public ranking is computed only from active bids: highest amount first, and the earlier confirmation wins a tie. The result is materialised in `ranking_positions`, which stores position and startup and **no amounts**.

**Rules (admin-configurable in `/admin#rules`):** opening bid ₹100 · increment ₹100 · 10 paid positions · 30-day ranking period · 20-minute checkout window · ₹10,00,000 safety cap · global on/off switch.

**Flow and safeguards**
1. **Board.** The server computes each position's qualifying bid and *minimum next bid* (qualifying bid + increment), excluding the owner's own bid. Owners can only bid for positions above their current one. Competitor identities are never returned.
2. **`POST /api/bids`.** The server re-validates against live data while holding a row lock on `bidding_rules` (`SELECT … FOR UPDATE` on PostgreSQL), which serialises every ranking-changing operation. A client-generated idempotency key (unique per startup) turns double-submits into replays. A partial unique index allows only one pending checkout per startup.
3. **`POST /api/payments/checkout`.** The bid is validated again, then a provider order is created. The DB lock is released before the network call.
4. **Confirmation.** Only a webhook whose HMAC signature verifies, or a direct server-to-server status query to the provider (`reconcile`), can mark a payment paid. Browser callbacks only redirect to a status page.
   - Webhook events are de-duplicated by provider event id, and a paid payment is never processed twice (`order.paid` after `payment.captured` is a no-op).
   - The amount and currency must match the order, otherwise the payment is flagged for review and nothing is ranked.
   - A failed attempt followed by a successful retry on the same order is handled correctly.
   - A capture that arrives after the owner cancelled or the checkout expired is still honoured, because the money was taken.
   - Rankings are rebuilt in the same transaction; displaced startups get "outbid" notifications.
5. **Maintenance.** `flask --app app bids maintain` expires abandoned checkouts and lapsed rankings; run it from cron every 5 minutes. Lapsed rankings are also expired lazily whenever a ranking is read.

Every bid, checkout, confirmation, failure, mismatch and admin rule change is written to `audit_logs` and `ranking_events`.

---

## 5. Payments (Razorpay)

Development uses `PAYMENT_PROVIDER=mock`, which production config refuses to start with. To switch to Razorpay **test mode**:

1. Create a Razorpay account and generate **test** API keys (`rzp_test_…`).
2. Create a webhook pointing to `https://<your-domain>/api/payments/webhook` with events `payment.captured`, `payment.failed` and `order.paid`, and set a webhook secret.
3. Set `PAYMENT_PROVIDER=razorpay`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET`.
4. For local webhook testing, expose your dev server with a tunnel (e.g. ngrok) and use that URL in step 2.
5. Schedule `flask --app app payments reconcile` every 10 minutes to catch any webhooks that never arrived.

Checkout is Razorpay's hosted modal (`checkout.js`). No card or bank data ever reaches this server; only order and payment IDs and statuses are stored.

---

## 6. Security summary
- Werkzeug **scrypt** password hashing; single-use, time-limited, signed tokens for email verification (72 h) and password reset (1 h); equalised login timing; no account enumeration.
- Flask-Login sessions with HttpOnly, SameSite=Lax cookies (Secure in production) and role-based access control (`startup_owner`, `investor`, `admin`). Admin role cannot be self-assigned.
- CSRF protection on every form and on JSON requests (`X-CSRFToken` header). Only the signature-verified webhook is exempt.
- Rate limits on login, registration, password reset, bids, checkout, uploads and introduction requests (use Redis storage in production).
- ORM-only queries, LIKE-wildcard escaping, Jinja auto-escaping, DOM output escaped in JS, and a strict Content-Security-Policy plus security headers.
- IDOR protection: every private resource is scoped to the signed-in user's startup, and a 404 (not a 403) hides private IDs.
- Uploads are checked by extension, size and decoded content, re-encoded with Pillow (strips EXIF and polyglots), saved under random names, with an 8 MB request cap and 5 MB per image.
- Secrets come only from environment variables; `ProductionConfig.validate()` refuses to boot with unsafe settings.
- Audit log for financial and administrative actions.

---

## 7. Production deployment
1. Provision PostgreSQL and Redis. Set `APP_ENV=production`, a strong `SECRET_KEY`, `DATABASE_URL`, `RATELIMIT_STORAGE_URI=redis://…`, Razorpay keys, SMTP and (optionally) `SENTRY_DSN`.
2. `pip install -r requirements.txt && flask --app wsgi db upgrade`
3. `flask --app wsgi create-admin` to create the first administrator.
4. Serve with **Gunicorn** (`gunicorn -c gunicorn.conf.py wsgi:app`) behind nginx or Caddy terminating **HTTPS**. Never use `flask run` in production. Serve `/static/` directly from nginx, and set `client_max_body_size 8m`.
5. Cron: `bids maintain` every 5 minutes, `payments reconcile` every 10 minutes.
6. Backups: nightly `pg_dump -Fc` to off-site storage with 30-day retention, plus a copy of `static/uploads/` (or move uploads to S3-compatible object storage). Test restores regularly.
7. Monitoring: Sentry (`SENTRY_DSN`), Gunicorn access/error logs to your log platform, uptime checks on `/` and alerts on webhook `error` rows.

`docker compose up --build` runs a production-like stack (PostgreSQL + Redis + Gunicorn). Set `POSTGRES_PASSWORD` and a `.env` first.

---

## 8. Decisions and credentials still needed

These are implemented with sensible defaults but need a business or legal owner before launch:

| Item | Current default | Decision needed |
|---|---|---|
| Payment provider and account | Razorpay integration; mock sandbox locally | KYC'd merchant account, live keys, webhook secret, GST invoicing |
| Bid pricing | Full amount paid per bid; the new bid replaces the startup's previous one (no top-up credit) | Whether earlier payments count towards a higher bid |
| Refunds | Confirmed bids are non-refundable; displaced startups are not refunded | Refund policy for outbid or unplaced paid bids (admins are alerted to unplaced paid bids) |
| Simultaneous payments | Accepted; the amount decides the position and the earlier confirmation wins ties | Alternatively hold a position during checkout, or auto-refund |
| Ranking period, positions, increments | 30 days, 10 positions, ₹100 opening and increment | Commercial pricing |
| Disclosure | "Promoted #n" badge plus footer note | Legal review of paid-placement disclosure (ASCI guidelines) |
| Listing approval | Admin approval required | Verification criteria (e.g. DPIIT / incorporation documents) |
| Email | SMTP via env vars | Transactional email provider and sender domain (SPF/DKIM) |
| Legal pages | Linked text only | Terms of Use, Privacy Policy (DPDP Act 2023), promoted-listing terms |
