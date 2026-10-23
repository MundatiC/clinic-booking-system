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
