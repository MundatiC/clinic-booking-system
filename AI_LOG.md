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

### Phase 2 continued: scanners, UI, and a laptop out of memory
21. **Schemathesis found three real bugs**, all fixed with regression tests:
    - a 500 when `doctor_id` exceeds Postgres `integer` (now bounded to 2³¹−1 → 422);
    - an undocumented 400 for non-UTF-8 bodies (now the same 422 as malformed JSON);
    - `?date=0` accepted because Pydantic reads numbers as Unix timestamps (now ISO dates only).
22. **ZAP's own logout revoked its token.** The first authenticated scan called `POST /auth/logout`, after which 1,333 of 3,188 requests were 401. This was spotted by counting status codes in the API logs, not from ZAP's summary, which looked clean. `/auth/logout` is now excluded via a hook. The first full CI run reported 120/120 rules passed. ZAP also flagged a missing `Cross-Origin-Resource-Policy` header, now added.
23. **zizmor:** 6× `artipacked`, fixed with `persist-credentials: false`. **hadolint:** non-numeric USER and shell-form HEALTHCHECK, both fixed; base images were also pinned by digest. **Trivy:** clean.
24. **Semgrep supply-chain finding the AI declined to apply as written.** `exclude-newer = "7 days"` made uv backtrack FastAPI 0.161 → 0.143. The AI's first attempt at it also corrupted `pyproject.toml` (a regex rewrote the project `name` line), so it was reverted from backups. Decision: enforce the cooldown in Dependabot (7 days) and exclude that one rule with a written reason.
25. **The same shell-escaping mistake twice.** Backslash escapes sent through a heredoc reached files as literal text or bytes (`\n` in a Dockerfile `RUN`, NUL bytes in a regex). After the second time, the AI switched to the editor tool for anything containing backslashes.
26. **Docker Desktop ran out of memory** (Postgres + API + Mailpit + ZAP + Semgrep images on the laptop) and its engine hung twice. Caleb asked to stop local heavy runs and to be given the commands instead. Heavy verification now runs in GitHub Actions.
27. **CodeQL JavaScript failed on PR #7** because the JS lived only in the uncommitted UI ("could not process any code written in JavaScript"). Caleb spotted it in a GitHub email. JS analysis moved to the UI PR, together with the code it scans.
28. **UI guard test caught its author.** `test_script_never_parses_html_from_strings` failed on the AI's own comment containing the word "innerHTML". The comment was reworded and the test kept strict.
29. **UI design pass (frontend-design skill).**
    - The first idea for date picking, a row of identical rounded "next 7 days" chips, matched the skill's "SaaS-card kit" tell and was replaced with a native date input and previous/next buttons.
    - The day strip needs working windows, so the availability response gained `working_hours`.
    - Self-review before running caught two JS flaws: messages set just before navigation were wiped by the navigation handler, and `aria-current` was handled twice.
30. **CI on the UI PR (#8) found three more issues.** The database-backed tests all passed in CI.
    - **CodeQL `js/user-controlled-bypass`:** the verify page auto-POSTed the emailed token on load. The token isn't exploitable as such, but auto-acting on a link lets link scanners, or a link from someone else, act for the user. Now it needs a "Confirm my email" click (tested).
    - **CodeQL `py/bad-tag-filter`:** the AI's "no inline script" test matched `<script` case-sensitively and would miss `<SCRIPT>`. Made case-insensitive.
    - **ZAP 100001** (unexpected content type): the API scan crawled the UI's HTML/CSS/JS. The API scan now excludes `/` and `/assets/`, which the baseline scan covers.
31. **The AI repeated the heredoc-escaping mistake a third time** (a Python patch script with regexes), right after logging it. This time the script's own assertions stopped it before it wrote anything. The edits were redone with the editor tool.
32. **The ZAP logout hook never worked, and an AI-added CI check proved it.** After adding a step that counts 401s on non-auth paths from the API logs after the scan, CI showed **2,350 of 3,215** requests were 401, even with the hook. Likely cause: ZAP calls every operation while *importing* the spec, before the hook's exclusions apply. The fix was to scan a copy of the spec without `/auth/logout`. The next CI run had **0 of 3,175** non-auth 401s. The earlier README claim ("logout excluded via a hook") had been wrong and was corrected.
33. **ZAP baseline on the UI page found a real issue.** Without JS (spiders, or a user whose script fails to load), the forms submitted via GET, putting email and password in the URL. Every form is now `method="post"` (tested). COEP was added. Three informational rules are ignored with written reasons.
34. A scoping regex required `/` after the host, so it missed `http://api:8000`; found by the next CI run and fixed.
35. **Local end-to-end run, after Caleb freed up memory (2026-10-23).**
    - Caleb ran the full suite (201 passed) and Schemathesis himself.
    - The AI ran a 51-check API script against his Docker stack. 50 passed. The one failure was the AI's own expectation (it expected 400 for a reused link; the app correctly answers 422 `INVALID_TOKEN`).
    - The AI then clicked through the UI in Chrome and found three bugs it had written:
      - After signing in from a protected page you stayed on the sign-in form, because navigating to the hash you are already on fires no `hashchange`. Its first fix (a role check) was wrong; re-testing in the browser showed the real cause.
      - The booking confirmation appeared off-screen.
      - An emptied list showed blank space.
    - The AI also claimed a missing label on the cancel-reason box, then retracted it on reading the markup (the textarea is inside its label; the browser tool just didn't show the name).
    - The AI started a second app server to check its fixes; Caleb stopped it ("that itself eats more memory"). Rule: ask him to rebuild the existing stack instead.
36. **Caleb spotted that required email confirmation would block every reviewer on the demo**: without a verified domain, Resend only delivers to its own account owner. He chose, from three options, to make confirmation a setting (off on Render) and to send through Gmail SMTP.
    - While implementing it, the AI found that switching confirmation off would let anyone sign up with a walk-in patient's email and see their appointments. Accounts claiming an earlier walk-in record therefore still need the emailed link (tested).
    - Also found while preparing for reviewers: Swagger had no Authorize button (the OpenAPI spec declared no security scheme), and there was no ready-made patient login. Fixed with an `HTTPBearer` scheme and an optional seeded demo login.
37. **UI redesign from Google Stitch (2026-10-23).** Caleb generated the design in Stitch from an AI-written prompt and exported 7 screens (code, screenshot, DESIGN.md).
    - The first export had only 2 of the 11 screens asked for; the AI listed the missing ones and wrote a follow-up prompt, and Caleb exported the rest.
    - Stitch invented details the API doesn't have (fees, insurers, rooms, phone lines, credentials, a data-protection claim) and used AI photos of the doctors. Caleb chose, from options, to drop the invented details and use initials.
    - Caleb decided the Stitch exports and prompts stay out of the repo (excluded locally through `.git/info/exclude`, not `.gitignore`, so the repo doesn't even name them).
    - The export couldn't be shipped as is: it loads Tailwind from a CDN and fonts and images from Google, all blocked by the CSP. The AI rebuilt it in plain CSS with self-hosted fonts and an inline SVG icon sprite, keeping every security rule (no inline script/style, `textContent` only; the existing tests enforce both).
    - Stitch put rescheduling in a same-day panel on *My appointments*; the AI kept the existing flow (the full booking page in "move" mode, any day), styled as Stitch's rescheduling banner.
    - Added the patient's phone to the staff schedule response, which Stitch's schedule showed and the front desk needs.
    - The Figma MCP Caleb connected never showed up as tools in this session, so the work used the exported files only.
    - **Browser walkthrough (desktop and 498 px phone width) found nine issues, all fixed:**
      - The worst was the AI's own: it set `data-view` on `<body>` to colour the logo per page, and the router hides every `[data-view]` that isn't the current view, so it hid the whole page (white screen). Renamed to `data-page`.
      - Earlier times today showed "Taken" (now "Too late to book · Past").
      - The time list was taller than the screen, so the booking summary was off screen (the list now scrolls in its card).
      - The nav's "Create account" button went blank on its own page (current-link colour = button colour).
      - Success banners scrolled under the sticky header.
      - A stray dark border on staff rows, and a centred list under a left-aligned heading.
      - A new view opened at the previous view's scroll position.
      - Small change made at the same time: the staff schedule now loads today on open.
    - The exported `logo.svg` was a 64 px PNG inside an SVG wrapper (not recolourable); the AI redrew it as a vector without the stray orange dot, coloured per page (green for patients, terracotta for staff, deepest green on account pages), and used it as the favicon.
    - The container's read-only filesystem (a hardening setting) meant every fix needed a rebuild, which Caleb ran; the AI started no other server.
    - **CI's ZAP baseline failed on rule 10109** ("Modern Web Application"): the staff-row template had an `<a>` with no `href` (set later by JS). Fixed in the markup rather than ignored: the link is now built whole in JS, and a test checks every link in the page has an `href`.
    - **The heredoc-escaping mistake happened a fourth time** (entries 25 and 31): the new test's regex `\b` reached the file as a backspace byte, and because the shell commands weren't chained, the broken file was committed and pushed before lint stopped anything. A follow-up commit fixed it with the editor tool. Rule kept from now on: regexes and backslashes only through the editor, and commit only after lint passes in the same chained command.
38. **Credit rule from Caleb:** everything that came from the *ponytail* skill counts as his discovery, since he chose and supplied it ("basically everything else gotten from ponytail skill counts as Caleb's discoveries"). README "Decisions Caleb made" now says so, and later ponytail-driven calls are logged that way.
39. **Repo audit (ponytail audit skill, run by Caleb), findings counted as his.** Six findings; he chose to fix five:
    - **Rate-limit bypass:** `FORWARDED_ALLOW_IPS="*"` makes uvicorn 0.54 take the *first* `X-Forwarded-For` entry, which the client writes, so a forged header could dodge the per-IP limits. Render now trusts only private proxy ranges; a test runs uvicorn's own middleware with the value from `render.yaml`. The README's earlier claim that `"*"` was safe was wrong. Whether Render appends to the header still needs one check after the first deploy.
    - The "change or cancel up to an hour before" text (page and booking email) contradicted the rule in code (until the visit starts).
    - Setup comments still described Resend after the switch to Gmail.
    - Emails still used the old purple palette.
    - *My appointments* asked for only 50 visits (now the API's maximum, 100).
    - Not fixed, by Caleb's choice: every demo sign-in emails `demo.patient@example.com`, which can't receive mail.
40. **Second repo audit (run by Caleb), findings counted as his.** Both fixed:
    - Staff could not book for anyone who had signed up online: `POST /patients` answered `409 PATIENT_EXISTS` without an id, and there is no patient lookup. The 409 now includes the existing `patient_id` (the route is staff-only, so nothing leaks to patients); tests cover a walk-in duplicate and the seeded online patient.
    - Four ORM relationships nothing read (`Doctor.working_hours`, `WorkingHours.doctor`, `Appointment.events`, `AppointmentEvent.appointment`) were deleted. The schema is unchanged (`alembic check` in CI).
