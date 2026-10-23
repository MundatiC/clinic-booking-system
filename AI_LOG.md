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
