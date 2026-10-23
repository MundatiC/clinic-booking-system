# AI Log

A running, factual log of how AI (Claude Code, model Claude Opus 5.5) was used in this project. It is written as the work happens. The README's Section 4 reflection is drawn **only** from entries here.

Format: what was asked → what AI produced → what was wrong or corrected → how it was verified.

---

## Session 1 (2026-10-23)

### Prompt
Caleb gave Claude Code one long, detailed brief: the assessment's verbatim requirements, a fixed stack (FastAPI, SQLAlchemy 2.0, Alembic, Postgres, uv, Render, GitHub Actions), the required edge cases, security/performance checklists, test list, CI/CD and keep-alive requirements, and honesty rules for this log. Caleb asked for plan mode first, the design committed before code, and the repo created and pushed to GitHub.

### Section 1: design
- AI produced the plan and the README Section 1 design (components, ER diagram, computed-slots and DB-uniqueness decisions, timezone rules, validation order, auth trade-off, growth path, decisions table).
- Most of the headline decisions (computed slots, partial unique indexes, UUIDs, UTC storage with Nairobi-local hours, row locks) were **specified in Caleb's brief**. The AI elaborated on them, but did not originate them.
- Decisions the AI added on top of the brief: 422-vs-409 convention, `APPOINTMENT_STARTED` for cancelling/rescheduling started visits, `PATIENT_EXISTS` on duplicate email, availability beyond the advance window returns `[]`, sync SQLAlchemy.

### Corrections and surprises (real, in order)
1. **Commit attribution rule (from Caleb).** The first commit had been made with Claude co-author trailers by default. Caleb set the rule "no Claude co-author on commits". The pushed commit was amended and force-pushed (`git push --force-with-lease`), then verified with `git log origin/main --format=%B | grep -ci co-authored` → `0`.
2. **Port clash (environment, not AI).** The compose Postgres on host port 5433 failed auth because a native Postgres (PID 7060) was already listening on 5433 and was answering instead. Diagnosed with `netstat -ano` + `Get-Process`. Moved compose to host port 55432.
3. **Redundant index (AI self-correction during review).** The first model had both a plain `(patient_id, start_at)` index and the partial unique index on the same columns. The partial one already serves the "upcoming booked appointments" query, so the plain one was dropped before the migration was committed. (The EXPLAIN check is in the README.)
4. **Body-size limit would have been swallowed (AI caught by reading framework source).** The first draft raised a custom `AppError` from the ASGI `receive` wrapper. Reading `fastapi/routing.py` showed that any non-`HTTPException` raised while FastAPI reads the body is converted into a generic 400 "error parsing the body". Changed to raise a 413 `HTTPException`. A test (`test_body_size_limit`) confirms 413 + `PAYLOAD_TOO_LARGE`.
5. **ORM cascade bug (caught by a failing test).** `Appointment.events` had no cascade, so deleting an appointment through the ORM tried to set `appointment_events.appointment_id = NULL` → NotNullViolation. A test's cleanup step exposed it. Fixed with `cascade="all, delete-orphan", passive_deletes=True`.
6. **500 responses lost the request id (caught by a failing test).** The generic `Exception` handler is run by Starlette's `ServerErrorMiddleware`, which sits *outside* user middleware. By then the request-id contextvar was reset and the security headers were never applied. `test_unhandled_error_is_generic_500` failed on the envelope. Moved unhandled-error rendering into `RequestContextMiddleware`.
7. **A sloppy test written by the AI.** One parametrized reschedule test had a muddled case and asserted `code in {code, "TOO_SOON", "OUTSIDE_WORKING_HOURS"}`, which would pass for the wrong reason. Noticed on re-read before running, and tightened to an exact `==` with correct cases.
8. **Bandit flagged `assert isinstance` narrowing** in the exception handlers (asserts vanish under `python -O`). Replaced with explicit re-raise.

### Verification evidence
- **Concurrency test is meaningful (mutation check).** A throwaway test dropped `uq_appointments_doctor_slot` and re-ran the 10-thread race: `Counter({'ok': 10})`, meaning all ten double-booked. With the index: exactly one `ok`, nine `SLOT_TAKEN`. So the DB index alone is what prevents double booking, and the test detects its removal.
- `pytest --cov`: 114 passed, 98% total coverage. Services and repositories are at 100% except one defensive re-raise branch in `integrity.py`.
- `ruff check`, `ruff format --check`, `mypy --strict`, `bandit`, `pip-audit --strict`, `alembic check`: all clean.

### Section 3 and final verification
9. **Version-aware smoke test (AI suggestion).** While writing the deploy workflow, the AI noted that Render's deploy hook returns immediately while the old release keeps serving, so a plain `/health` smoke test would pass against the old version. It added the commit to `/health` (`RENDER_GIT_COMMIT`) and `scripts/smoke.py` waits for the merged `GITHUB_SHA`. **Unverified** until a Render service exists: whether `RENDER_GIT_COMMIT` is populated for Docker services.
10. **Clean-clone compose run.** `git clone` into a scratch dir, then `docker compose up -d --build`: migrations and seed ran on boot, `/health` and `/ready` returned 200, and the container user is `uid=999(app)`. A full curl flow (register → availability → book → 409 → off-grid 422 → reschedule → upcoming → cancel → 409 → naive 422) behaved as designed, and that output is quoted in the README.
11. **Inconsistency found in manual testing.** `POST /patients` returned `created_at` in UTC (`…Z`) while everything else used `+03:00`. Fixed, with a test added.
12. **EXPLAIN on ~100k synthetic rows.** The AI's first load script violated the `cancelled_at` CHECK constraint (the constraint did its job); the script was fixed. Plans: availability is an Index Only Scan on `uq_appointments_doctor_slot` (0.27 ms); patient page and count use `uq_appointments_patient_slot`. The plan showed an Incremental Sort caused by a redundant `ORDER BY …, id` tie-breaker, so the tie-breaker was removed.
13. **Encoding scare.** A Python in-place edit read README.md with Windows' default cp1252 and failed. Checked every tracked file for mojibake, and none was damaged (earlier edits round-tripped bytes and only inserted ASCII). Further README edits used the editor tool.
14. **First Deploy run on main** (after merging PR #4): all four CI jobs re-ran green inside the Deploy workflow. The deploy job skipped with the intended warning because `RENDER_DEPLOY_HOOK_URL` / `APP_URL` are not set yet.

## Session 1, phase 2: auth, email, security testing, UI (2026-10-23)

### Prompt (Caleb)
"Build the UI, add authentication, also use a tool for tests that test for security stuff, make sure the basic security and even complex ones are all handled, use the front end skill and even ponytail skill." Caleb then chose password + server-side sessions, asked for Schemathesis + ZAP + Trivy + Semgrep + a pytest security suite ("as many as we can that are relevant"), kept the keep-alive cron and will add an external trigger, deferred Render, and added: email verification + password reset with Resend in production and a local SMTP catcher, plus templates for sign-up, sign-in "and any other relevant ones".

### Skills
- `frontend-design` was not installed. Its SKILL.md was found in the synced official plugin marketplace on disk and followed from there.
- `ponytail` did not exist locally. Caleb linked `DietrichGebert/ponytail/skills/ponytail/SKILL.md`. The AI downloaded only that markdown file into a scratch folder, read it fully (no code, no instructions to run anything), and installed it to `~/.claude/skills/ponytail/`. It did **not** install the repo's JS hooks/plugins.

### Design refinements the AI made while implementing (not in the approved plan; recorded as decisions)
- Sign-up always answers 202 "check your email". An existing email gets an "already registered" email. This means sign-up does not log you in.
- Sign-in requires a verified email. This made it safe to link a new account to an existing walk-in patient record with the same email, and removed per-endpoint "verified?" checks.
- `/auth/login` sets only the HttpOnly cookie. A separate `/auth/token` returns a bearer token for API clients, so the browser token never reaches JavaScript.
- Lockout reuses the existing `RateLimiter`, keyed by email, so unknown emails lock identically (no enumeration through lockout).
- Password reset marks the email verified. This defeats "squatting" someone's email with an unverified account (tested).
- Resend is used via its SMTP relay, so stdlib `smtplib` is the only transport (no SDK).

### Bugs and corrections in phase 2
15. **Timing leak in sign-up (AI caught on self-review).** The first `register` hashed the password only for new emails, so existing emails answered faster (an enumeration oracle). Fixed by hashing before the existence check.
16. **`render(name, ..., **values)` clash (caught by tests).** Templates take a `name` value, which collided with the function's first parameter → TypeError → 500 on every email. Made the parameter positional-only.
17. **`email-validator` rejects reserved TLDs** (`.test`, `.localhost`) for the test/staff accounts. Switched to `example.com`. Tests caught it.
18. **Raw control bytes written into source (AI tooling mistake).** Writing a regex `\x00-\x1f` through a shell heredoc + Python string produced literal NUL/control bytes in `app/schemas/patients.py` (grep reported "binary file"). Fixed by writing the bytes explicitly, then scanned every tracked file for control bytes (none).
19. **FastAPI 0.161 nests included routers** (`_IncludedRouter`), so iterating `app.routes` for `APIRoute` found nothing and the "every route needs auth" test silently had zero routes. It failed on its `len >= 8` guard. Switched to enumerating operations from the OpenAPI schema.
20. **Bandit flagged three new `assert user is not None`.** Replaced with an `EmailToken.user` relationship and an explicit `user is None or not ok` check.

### Verification
- 188 tests pass (184 + SMTP mailer tests). New security suite: 63 tests in `tests/security/`.
- **Mutation checks:** removing the ownership check, the cookie CSRF check, or the enumeration-safe sign-up each made at least one security test fail. Removing the cookie CSRF check broke only the "no Origin" test, because the global origin check still blocked foreign origins (defence in depth). Files were restored afterwards.
- Compose stack with Mailpit: sign-up → verification email caught in Mailpit → verify via token → welcome email → sign-in (cookie set) → "new sign-in" email; staff bearer token works. API logs: 0 lines containing an email address, 0 containing `token=`.
