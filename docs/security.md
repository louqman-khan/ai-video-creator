# Security notes for the hosted site

Honest status: built with care and tested locally, **not** penetration-tested and **not** run on a public server. Treat the list below as what exists, with its evidence, and what is still open.

## Threats and what answers them
| Threat | Answer | Evidence |
|---|---|---|
| Reading or changing another user's project | one global guard; ownership check on every `/api/projects/{id}/...` route, answers 404 (never reveals existence) | `tests/test_hosted.py::test_nobody_can_touch_somebody_elses_project_on_any_route` (26 route shapes, 3 identities); real browser run `frontend/e2e/hosted.mjs` |
| New routes forgotten by a developer | the guard is a global dependency, so a new route is protected by default | same test + design |
| Guessing project ids | 128-bit random ids, ownership check even if guessed | design |
| Stolen passwords from a database leak | scrypt (N=2^15) with random salts; sessions and e-mail tokens stored only as SHA-256 | `test_passwords_*` |
| Guessing passwords | rate limit per IP and per account, same answer and same time for unknown e-mail and wrong password | `test_logging_in_is_rate_limited_per_account`, `test_sign_up_verification_login_logout` |
| Finding out who has an account | sign-up and reset answer the same for known and unknown addresses | tests above |
| Cross-site request forgery | state-changing requests need the `X-Requested-With: avc` header and a matching Origin; cookies are SameSite=Lax | `test_nothing_works_without_logging_in...`, e2e |
| Script injection / clickjacking | CSP (self only), `X-Frame-Options: DENY`, `nosniff`, no inline scripts, React escapes text | e2e checks the headers and that the editor works under the CSP |
| Stolen session | HttpOnly cookie, ends on logout/password change/account deletion, 14-day expiry | tests, e2e |
| Server fetching internal addresses through a malicious search result | downloads accept public addresses only, also after redirects | `test_the_hosted_site_never_fetches_from_its_own_network` |
| Hostile media files | decoded by ffmpeg inside a container: non-root, read-only filesystem, no capabilities, memory/CPU/process limits; upload size, length, pixel and fps limits; files recognised by content | `deploy/docker-compose.yml`, `app/media/ingest.py` tests |
| One user starving the others | one job at a time per user, storage/project/export limits, global worker count | `test_limits_*` |
| Abuse of the free voices licence | free voices are off in hosted mode | `test_the_free_voices_stay_off...` |
| Losing data | `deploy/backup.sh` (database + projects) | not exercised on a server |

## Still open (do before a wide public launch)
- An independent security review / penetration test; dependency audit in CI (`pip-audit`, `npm audit`).
- Real e-mail deliverability (SPF/DKIM for your domain) and a bounce/abuse process.
- Content moderation: the service renders whatever people upload. Decide a policy and a way to take content down.
- Legal texts: `terms` and `privacy` pages are drafts; have them reviewed. Check GDPR/PDPL duties for your users' country.
- CAPTCHA or e-mail-domain rules against sign-up abuse if invite-only is lifted.
- Monitoring and alerting (uptime, disk, CPU); log retention rules (logs contain e-mail addresses at sign-up).
- Disk quota is checked when work starts, not while it runs; a single job can exceed it a little.
- The first administrator is whoever is in `ADMIN_EMAILS` and verifies that address: keep that mailbox safe.
