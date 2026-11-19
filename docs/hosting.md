# Hosting the website (hosted mode)

One codebase, two modes. `MODE=local` is the desktop app / `avc app` for one person. `MODE=hosted` adds accounts, per-user limits and security headers.

## Architecture (single server, on purpose)
```
browser ──HTTPS──> Caddy (certificate, request size) ──> app container (API + web editor + render workers) ──> /data volume
                                                                                                         ├─ app.db     accounts, sessions (SQLite, WAL)
                                                                                                         └─ projects/  every project's files (one folder per project)
```
Decision (senior-dev call, replaces the first sketch in `STEP6_PLAN.md`): **no object storage and no separate worker fleet in version one.** ffmpeg needs real local files, so API and workers share one disk
on one machine; isolation is by *ownership checks on every route* plus unguessable 32-hex project ids, limits per user, and a container with capped CPU/memory. Moving to several machines later means
replacing the disk with object storage and the in-process job pool with a queue; the interfaces (`ProjectStore`, `JobRunner`, `Accounts`) are where that happens. A single 4-core machine renders roughly one 1080p minute of video per 1-2 minutes of CPU
(measured: 20 s for a 12 s video on a 4-core laptop), so plan about 20-40 active users per such machine with the default limits.

## What the hosted mode does
- Accounts: e-mail + password (scrypt), e-mail verification, password reset, session cookie (HttpOnly, SameSite=Lax, Secure on https), data export, account deletion.
- Every `/api` route passes one guard (`app/accounts/guard.py`): login required, project routes answer 404 for projects of others, the header/Origin check against cross-site requests, administrators-only storage clean-up, limits.
- Limits per user (settings): projects, storage, one job at a time, exports per day; global `JOB_WORKERS`.
- Sign-ups: `SIGNUPS=open|invite|closed` with `INVITE_CODES`. Start with `invite`.
- Downloads started by search results can only go to public internet addresses (no localhost, private networks or the cloud metadata address).
- The free computer voices are **off** (`ALLOW_NONCOMMERCIAL_VOICES` unset): their licences do not allow a public product. Speech from text works only with a paid provider you configure.

## Deploy (any Linux server with Docker, 4 cores / 8 GB RAM / 100 GB disk is a sensible start)
1. Point a domain name at the server. Open ports 80 and 443.
2. `git clone` the repository; `cp deploy/.env.production.example .env.production` and fill it in (domain, SMTP, API keys, limits, invitation codes, your admin e-mail).
3. `docker compose -f deploy/docker-compose.yml --env-file .env.production up -d --build`
4. Open `https://<domain>/`, sign up with your admin e-mail (confirm through the e-mail), and try a project.
5. Backups: run `deploy/backup.sh /backups` from cron and copy the files off the machine (for example to Cloudflare R2 with rclone).
Updating: `git pull` then step 3 again. Logs: `docker compose -f deploy/docker-compose.yml logs -f app`.

## Cost reality
Free tiers cover testing (Oracle Cloud's free ARM machine is an option: the image builds for ARM, untested here). A public service needs a paid machine, an SMTP provider (free tiers exist), and a decision on
who pays for AI services that bill per use (Gemini planning, optional paid voices). Rendering is CPU time on your own machine.

## Not done / known limits of version one
- One machine only; no horizontal scaling, no job queue across machines. A restart marks running jobs as failed (users retry).
- SQLite is used for accounts (PostgreSQL works by changing `DATABASE_URL`, not tried).
- No Google sign-in (needs credentials from you), no payments or plans, no admin screen (only the storage clean-up).
- Rate limits are per process, in memory.
- Untested on a real server and domain: see `docs/security.md` for what was and was not verified.

## Credits (hosted mode)
Each account has a monthly allowance (`CREDITS_PER_MONTH`, default 10; renews on the 1st, UTC). Creating a video charges 1 credit per `CREDIT_MINUTES` (default 1) of narration, rounded up, at least 1; a typed script is priced at 150 words a minute. Not enough credits: the server answers 402 with the reason and no project is made. A video that fails before it ever produced a preview gives its credits back, once. Administrators (`ADMIN_EMAILS`) are not charged. The ledger is the `credit_events` table (spent, refund, bonus rows), so balances are auditable and a bonus is one inserted row.
The sidebar shows the plan card (used / left / renewal date), the new-project page shows the cost before Create, the account page explains the rule. Plans and payment are not built: `CREDITS_PLAN_NAME` is only a label for now.

## Operator page (accounts)
Administrators (`ADMIN_EMAILS`) get an **Accounts** page (`/admin`) in the sidebar: every account with its e-mail, role, whether the address was confirmed, join date, last login, credits used and left this month, number of projects and storage used. Per account: **Add credits** (a whole number from -1000 to 1000; bonus credits do not expire with the month and are shown as "includes N bonus"; a negative number takes bonus credits back, never below zero) and **Switch off / Switch on** (a switched-off person is logged out at once and cannot log in; administrators cannot be switched off from here). API: `GET /api/admin/users`, `POST /api/admin/users/{id}/credits`, `POST /api/admin/users/{id}/disabled`; the guard answers 403 to everyone who is not an administrator and 401 to visitors. Bonus rows are `credit_events` with reason `bonus`, so every gift is in the ledger.

## E-mail (verification and password reset)
Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` and `MAIL_FROM` (for example `AI Video Creator <no-reply@your-domain>`) in the server's `.env`. Port **465** uses an encrypted connection from the first byte (SMTPS); ports 587/25 start plain and upgrade with STARTTLS. Without `SMTP_HOST` the messages are written to `<work_dir>/outbox/` (development). Tests always use the outbox, even when `.env` holds real mail settings. Check that the login works without sending anything: connect with `smtplib.SMTP_SSL(host, 465)` and call `login`. Never commit `.env`.

## Sign-in experience (English and Urdu)
- **Languages:** every sign-in page has a switch (English | اردو); the choice is remembered, Urdu turns the page right to left and uses Noto Nastaliq. The interface language is sent with sign-up, resend and forgot-password, so the e-mail arrives in the same language (`app/accounts/emails.py`). Texts are keyed by their English wording in `frontend/src/i18n.ts` (an unknown text stays English; server messages are translated there too).
- **E-mail:** a styled HTML message (plain text for clients that do not show HTML) with the **six-digit code** in the middle. There is no confirmation link: the code is typed on the sign-up page (owner's decision, 2026-11-19). Open `<work_dir>/outbox/*.html` in a browser to see the styled version when no SMTP is configured.
- **Code:** `POST /api/auth/verify-code {email, code}`; stored only as a hash, valid 30 minutes, one per account, single use; five wrong tries per address per 15 minutes (a six-digit code cannot be guessed), 30 per hour per IP. - **Resend:** `POST /api/auth/resend {email, lang}` (the answer never reveals whether the address exists or is confirmed; 3 per address per hour). The pages offer it after sign-up and when a log-in is refused for an unconfirmed address, with a 45 s wait between sends.
- **Password reset** stays link-only (one hour, single use).
- **Passwords:** at least 6 characters (owner's decision), and a list of commonly used passwords (`123456`, `qwerty`, `password1`, ...), repeated characters and the e-mail address itself are refused; hashing is scrypt and log-in attempts are rate limited, which is what makes a short minimum acceptable. Raise `MIN_LENGTH` in `app/accounts/passwords.py` to tighten it.
- **Existing addresses:** signing up with an address that already has a confirmed account answers 409 "This e-mail already has an account" (the page then links to log in and forgot-password). An address whose sign-up was never confirmed gets a new code and the code box, and keeps its first password (so nobody can swap the password of an unconfirmed account). The sign-up form is rate limited (5 per hour per IP), so it cannot be used to comb through addresses. (Earlier versions answered identically for known and unknown addresses; the owner asked for the explicit message.)
- **Sending:** e-mail is sent in the background with up to 4 attempts (`BackgroundMailer`), so a slow or unreachable mail server never delays or breaks a request; if all attempts fail it is logged and the person can press "Send a new e-mail". (The mail server was reachable only intermittently from the development network: the old synchronous send took 22 s and ended in a 500.)

