# Step 6 plan: one product, two ways to run it (hosted website + desktop app)

Status: **approved by delegation** ("you are the senior dev, build the best option for public"). Built so far: accounts, ownership guard, limits, hosted frontend, deployment files — see `docs/hosting.md`, `docs/security.md` and the progress log in `ROADMAP.md`. **Change from this plan:** version one uses ONE machine (shared local disk, in-process workers, SQLite) instead of object storage + a queue (6.1/6.3), because ffmpeg needs local files and that is the simplest design that is safe for a first public launch; the interfaces for the later split are kept.

## The idea
One codebase. The editor, the timeline, the renderer, the providers stay exactly as they are. What changes is *where things live* and *who is asking*, behind interfaces (the project's
rule: every capability behind a swappable provider). Two profiles chosen by config:

| | `MODE=local` (desktop app, `avc app`) | `MODE=hosted` (website) |
|---|---|---|
| Who | one person, implicit owner, no login | many accounts, login required |
| Metadata | SQLite file (or today's folders) | PostgreSQL |
| Files | the work folder on disk | object storage (Cloudflare R2), workers use a local scratch folder |
| Jobs | in-process worker thread (today) | separate worker processes with a queue, per-user limits |
| Updates | rebuild / Tauri updater | redeploy |

The desktop app stays offline-first and needs no account. Syncing a desktop project to the website is **not** part of this step.

## What is different about hosting (the real work)
1. **Isolation.** Every route today trusts that the caller owns every project. Hosted: every route checks ownership; every file path is derived from the owner.
2. **Files.** The code works with local paths everywhere (ffmpeg needs real files). Hosted workers must download inputs to scratch, render, upload results, and delete scratch. This is the biggest refactor.
3. **Cost.** A 1080p export is about 20 s of CPU per 12 s of video on a laptop (70 s at 4K). Hosting means servers, queues, quotas and a decision on who pays.
4. **Untrusted input.** ffmpeg decodes files from strangers: workers should run in containers with CPU/memory/time/disk limits and no network except storage.
5. **Licences.** The Urdu voice (MMS-TTS) is non-commercial and the Piper voice's licence is unclear: **the hosted service cannot ship them**. It launches with captions/audio-in only, or with a paid voice provider (ElevenLabs, per-use), until a permissive Urdu voice is found or made.
6. **Abuse and law.** Upload rights confirmation (exists), terms and privacy pages, account/data deletion and export, rate limits, email verification, stock-media credit handling (exists).

## Tasks
- **6.0 Decisions and spikes.** Hosting target (default: Oracle Cloud free VM for API+workers, Neon/Supabase free PostgreSQL, Cloudflare R2 for files); login methods (default: email+password with argon2 and email verification, plus Google sign-in); voice licence plan; measure one real job's CPU/RAM/disk on the target machine. *Done when:* decisions are written in `docs/decisions.md` with the measured numbers.
- **6.1 Storage interface.** `Storage` with `LocalStorage` and `S3Storage`; every place that reads or writes project/media files goes through it (audit first, list in the task); workers get `scratch()` helpers. *Done when:* the whole test suite passes on both implementations (S3 against a local MinIO container in tests).
- **6.2 Database and data model.** users, projects, assets metadata, jobs; migrations; `ProjectStore` over SQLAlchemy (SQLite local, PostgreSQL hosted); a one-time importer of today's project folders. *Done when:* existing tests pass unchanged on the new store and a real project round-trips through the importer.
- **6.3 Job queue and workers.** DB-backed queue, a `worker` command, concurrency and per-user limits, progress and cancel, crash recovery. Local mode keeps the in-process runner behind the same interface. *Done when:* two users' jobs run side by side, one cannot starve the other, a killed worker's job is retried.
- **6.4 Accounts and sessions.** sign-up, email verification, login/logout, password reset, Google sign-in, HttpOnly session cookies, CSRF protection, ownership checks on every route, rate limiting on auth. Local mode: a fixed implicit user. *Done when:* a test matrix proves user A cannot read, change, export or delete user B's project, media, avatar, export or storage report on any route.
- **6.5 Frontend for accounts.** login/sign-up/reset pages, account page (data export, delete account), quota display, friendly session-expired handling; the desktop app shows none of it. *Done when:* real-browser run for both modes.
- **6.6 Deployment.** Dockerfiles (api, worker), compose for local trial, reverse proxy + TLS, R2 bucket, secrets handling, backups, health checks, logging/metrics, a staging site. *Done when:* a fresh machine reaches a working site from the README alone.
- **6.7 Security and legal.** threat model, worker sandboxing (containers, limits, no network), dependency audit, security headers/CSP, terms of use, privacy policy, deletion/retention rules. *Done when:* the checklist in `docs/security.md` is ticked with evidence.
- **6.8 Desktop for other people.** bundle Python and a first-run model download (PyInstaller or a standalone Python), code-signing/notarisation (macOS) and signing (Windows), auto-update (Tauri updater). *Done when:* a clean Mac and a clean Windows PC install and run it without a developer set-up.
- **6.9 Windows and Linux verification.** run the CI matrix and a Windows PC, fix what fails (`docs/windows.md`). *Done when:* CI is green on all three.

## Order and why
6.0 first (it can change the rest), then 6.1 -> 6.2 -> 6.3 (the foundation: nothing user-facing, but accounts without it would be a lock on an open house), then 6.4 -> 6.5, then 6.6 -> 6.7 before any public use. 6.8 and 6.9 are independent of the hosted work and can be done in parallel or first if the desktop app is the earlier launch.

## Things only you can provide or decide
- Hosting choice and who pays (free tiers are enough to start; a public launch is not free).
- Whether the hosted site is public or invite-only at first.
- Domain name, email sender (for verification and password reset), Google sign-in credentials.
- Apple Developer ID and a Windows signing certificate for real desktop installers (paid).
- A permissive-licence Urdu voice, or the decision to use a paid voice provider on the website.
- The Urdu/English samples and real footage from before (still open).
