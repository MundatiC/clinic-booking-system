"""Accounts, sign-in sessions, email verification and password reset.

Enumeration rules: sign-up, resend-verification and forgot-password answer the
same way whether or not the email has an account; sign-in failures are
identical for unknown emails and wrong passwords, and lockout is keyed by email
so unknown emails "lock" too. Only someone who knows the password learns that
an account is unverified.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core import security
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, ForbiddenError, UnauthorizedError
from app.core.ratelimit import RateLimiter, too_many
from app.db.models import AuthSession, EmailToken, EmailTokenPurpose, Patient, User, UserRole
from app.repositories import users as users_repo
from app.services.notifications import Notifier

VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(minutes=30)
_LAST_SEEN_RESOLUTION = timedelta(minutes=1)  # don't write on every request


class AuthService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        clock: Clock,
        notifier: Notifier,
        login_failures: RateLimiter,
    ) -> None:
        self.session = session
        self.s = settings
        self.clock = clock
        self.notify = notifier
        self.failures = login_failures

    # ---- sign-up and verification --------------------------------------------------

    def register(self, full_name: str, phone: str, email: str, password: str) -> None:
        email = email.strip().lower()
        security.check_password_policy(password, email)
        # Hash before the existence check so both paths take the same time.
        password_hash = security.hash_password(password)
        if users_repo.by_email(self.session, email) is not None:
            self.notify.already_registered(email)
            return

        # A walk-in patient registered by staff keeps their record. Linking is safe
        # because sign-in to a walk-in record needs proof of this inbox (see login).
        patient = users_repo.patient_by_email(self.session, email) or Patient(
            full_name=full_name, phone=phone, email=email
        )
        user = User(
            email=email,
            password_hash=password_hash,
            role=UserRole.PATIENT,
            patient=patient,
        )
        try:
            users_repo.add(self.session, patient, user)
        except ConflictError:  # lost a race with a concurrent sign-up for this email
            self.notify.already_registered(email)
            return
        token = self._issue_token(user, EmailTokenPurpose.VERIFY, VERIFY_TTL)
        self.session.commit()
        self.notify.verify_email(email, patient.full_name, token)

    def verify_email(self, token: str) -> None:
        user = self._redeem(token, EmailTokenPurpose.VERIFY).user
        first_time = user.email_verified_at is None
        user.email_verified_at = user.email_verified_at or self.clock.now()
        self.session.commit()
        if first_time:
            self.notify.welcome(user.email, _name(user))

    def resend_verification(self, email: str) -> None:
        user = users_repo.by_email(self.session, email.strip().lower())
        if user is None or user.email_verified_at is not None:
            return
        token = self._issue_token(user, EmailTokenPurpose.VERIFY, VERIFY_TTL)
        self.session.commit()
        self.notify.verify_email(user.email, _name(user), token)

    # ---- sign-in sessions ----------------------------------------------------------

    def login(self, email: str, password: str, user_agent: str) -> tuple[User, str]:
        email = email.strip().lower()
        retry_after = self.failures.blocked(email)
        if retry_after is not None:
            raise too_many(retry_after, "ACCOUNT_LOCKED")

        user = users_repo.by_email(self.session, email)
        # Always run the hash check (a dummy one for unknown emails): same cost either way.
        password_ok = security.verify_password(password, user.password_hash if user else None)
        if user is None or not password_ok:
            self.failures.hit(email)
            raise UnauthorizedError("INVALID_CREDENTIALS", "Email or password is incorrect.")
        # A walk-in's record (created by staff before this account) only goes to someone
        # who proves they own the inbox, even when verification is otherwise optional.
        claims_walk_in = user.patient is not None and user.patient.created_at < user.created_at
        if user.email_verified_at is None and (self.s.require_email_verification or claims_walk_in):
            raise ForbiddenError(
                "EMAIL_NOT_VERIFIED",
                "Confirm your email first. We can send the link again.",
            )

        self.failures.reset(email)
        if security.needs_rehash(user.password_hash):
            user.password_hash = security.hash_password(password)
        now = self.clock.now()
        users_repo.delete_sessions(self.session, user.id, expired_before=now)
        token, token_hash = security.new_token()
        users_repo.add(
            self.session,
            AuthSession(
                user_id=user.id,
                token_hash=token_hash,
                created_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(hours=self.s.session_max_hours),
            ),
        )
        self.session.commit()
        self.notify.new_sign_in(user.email, _name(user), now, user_agent)
        return user, token

    def authenticate(self, token: str) -> User | None:
        """The signed-in user for a session token, or None if missing/expired/idle."""
        record = users_repo.session_by_token_hash(self.session, security.hash_token(token))
        if record is None:
            return None
        now = self.clock.now()
        idle_limit = record.last_seen_at + timedelta(minutes=self.s.session_idle_minutes)
        if now >= record.expires_at or now >= idle_limit:
            self.session.delete(record)
            self.session.commit()
            return None
        if now - record.last_seen_at >= _LAST_SEEN_RESOLUTION:
            record.last_seen_at = now
            self.session.commit()
        return record.user

    def logout(self, token: str) -> None:
        record = users_repo.session_by_token_hash(self.session, security.hash_token(token))
        if record is not None:
            self.session.delete(record)
            self.session.commit()

    # ---- password reset ------------------------------------------------------------

    def forgot_password(self, email: str) -> None:
        user = users_repo.by_email(self.session, email.strip().lower())
        if user is None:
            return
        token = self._issue_token(user, EmailTokenPurpose.RESET, RESET_TTL)
        self.session.commit()
        self.notify.reset_password(user.email, token)

    def reset_password(self, token: str, new_password: str) -> None:
        user = self._redeem(token, EmailTokenPurpose.RESET).user
        security.check_password_policy(new_password, user.email)
        now = self.clock.now()
        user.password_hash = security.hash_password(new_password)
        # Following the emailed link proves control of the inbox.
        user.email_verified_at = user.email_verified_at or now
        users_repo.delete_sessions(self.session, user.id)  # sign out everywhere
        self.session.commit()
        self.failures.reset(user.email)
        self.notify.password_changed(user.email, _name(user), now)

    # ---- helpers -------------------------------------------------------------------

    def _issue_token(self, user: User, purpose: str, ttl: timedelta) -> str:
        now = self.clock.now()
        users_repo.retire_tokens(self.session, user.id, purpose, now)
        token, token_hash = security.new_token()
        users_repo.add(
            self.session,
            EmailToken(
                user_id=user.id, purpose=purpose, token_hash=token_hash, expires_at=now + ttl
            ),
        )
        return token

    def _redeem(self, token: str, purpose: str) -> EmailToken:
        now = self.clock.now()
        record = users_repo.usable_token(self.session, security.hash_token(token), purpose, now)
        if record is None:
            raise BusinessRuleError(
                "INVALID_TOKEN",
                "This link is invalid, already used, or expired. Request a new one.",
            )
        record.used_at = now
        return record


def _name(user: User) -> str:
    return user.patient.full_name if user.patient else "there"
