"""Opaque revocable sessions; no browser-stored passwords or bearer tokens."""
import os
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import delete
from sqlmodel import select
from .db import DATA, identifier, now
from .collab_models import LoginAttempt, LoginSession, SecurityAudit, User

COOKIE = 'tms_collab_demo_session' if os.environ.get('TMS_COLLAB_DEMO') == '1' else 'tms_collab_session'
if os.environ.get('TMS_DESKTOP_RUNTIME') == '1':
    # Cookies are scoped by host, not port. Keep desktop spaces independent of
    # source services and of restored workspaces opened in the same browser.
    COOKIE += '_' + hashlib.sha256(str(DATA.resolve()).casefold().encode()).hexdigest()[:12]
ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS)
    return f'pbkdf2-sha256${ITERATIONS}${salt}${key.hex()}'


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt, expected = encoded.split('$')
        if scheme != 'pbkdf2-sha256' or int(rounds) != ITERATIONS:
            return False
        value = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(value, expected)
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password(secrets.token_urlsafe(24))


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def log(session, actor, action, data=None):
    session.add(SecurityAudit(id=identifier('SEC'), actor=actor, action=action, occurred_at=now(), data=data or {}))


def authenticate(session, request):
    token = request.cookies.get(COOKIE, '')
    record = session.get(LoginSession, digest(token)) if token else None
    user = session.get(User, record.user_id) if record and record.expires_at > now() else None
    if not user or not user.active:
        raise HTTPException(401, '请登录，或登录已过期')
    if request.method not in ['GET', 'HEAD']:
        csrf = request.headers.get('x-csrf-token', '')
        if not hmac.compare_digest(csrf, record.csrf):
            raise HTTPException(403, '会话校验失败，请刷新后重试')
    session.info.update(user=user, actor=user.id, mode='collaboration', login_session=record)
    return user


def start_session(session, response, user, old_token=''):
    if old_token:
        session.exec(delete(LoginSession).where(LoginSession.token_hash == digest(old_token)))
    token = secrets.token_urlsafe(48)
    record = LoginSession(token_hash=digest(token), user_id=user.id, csrf=secrets.token_urlsafe(32),
                          expires_at=(datetime.now(timezone.utc) + timedelta(hours=8)).isoformat())
    session.add(record)
    # HTTP only on loopback; hosted deployment must change cookie to Secure and enforce HTTPS.
    response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=False,
                        path='/api/collab', max_age=8 * 3600)
    return record


def login(session, request, response, username, password):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    address = request.client.host if request.client else 'unknown'
    recent = session.exec(select(LoginAttempt).where(LoginAttempt.occurred_at > cutoff)).all()
    if sum(r.username == username for r in recent) >= 8 or sum(r.address == address for r in recent) >= 40:
        raise HTTPException(429, '尝试次数过多，请15分钟后重试')
    user = session.exec(select(User).where(User.username == username)).first()
    valid = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if not valid or not user or not user.active:
        session.add(LoginAttempt(id=identifier('TRY'), username=username, address=address, occurred_at=now()))
        log(session, 'anonymous', 'login_failed')
        session.commit()
        raise HTTPException(401, '账号或密码不正确，或账号已停用')
    session.exec(delete(LoginAttempt).where(LoginAttempt.username == username))
    session.exec(delete(LoginAttempt).where(LoginAttempt.occurred_at <= cutoff))
    session.exec(delete(LoginSession).where(LoginSession.expires_at <= now()))
    record = start_session(session, response, user, request.cookies.get(COOKIE, ''))
    log(session, user.id, 'login')
    session.commit()
    return user, record


def public_user(user):
    return {key: getattr(user, key) for key in ['id', 'username', 'display_name', 'role', 'organization_id', 'active', 'must_change_password']}
