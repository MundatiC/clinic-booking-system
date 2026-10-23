import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db.models import AuthSession, EmailToken, Patient, User
from app.repositories.integrity import flush_or_translate


def by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email))


def patient_by_email(session: Session, email: str) -> Patient | None:
    return session.scalar(select(Patient).where(Patient.email == email))


def add(session: Session, *objects: object) -> None:
    session.add_all(objects)
    flush_or_translate(session)


def session_by_token_hash(session: Session, token_hash: bytes) -> AuthSession | None:
    return session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))


def delete_sessions(
    session: Session, user_id: uuid.UUID, *, expired_before: datetime | None = None
) -> None:
    stmt = delete(AuthSession).where(AuthSession.user_id == user_id)
    if expired_before is not None:
        stmt = stmt.where(AuthSession.expires_at <= expired_before)
    session.execute(stmt)


def usable_token(
    session: Session, token_hash: bytes, purpose: str, now: datetime
) -> EmailToken | None:
    """The unused, unexpired token, row-locked so it can only be redeemed once."""
    stmt = (
        select(EmailToken)
        .where(
            EmailToken.token_hash == token_hash,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
            EmailToken.expires_at > now,
        )
        .with_for_update()
    )
    return session.scalar(stmt)


def retire_tokens(session: Session, user_id: uuid.UUID, purpose: str, now: datetime) -> None:
    """Mark earlier unused tokens of this purpose as used (only the newest link works)."""
    session.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user_id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
