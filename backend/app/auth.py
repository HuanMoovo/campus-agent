"""账号与登录会话。

- 口令散列：PBKDF2-HMAC-SHA256（标准库），格式 `pbkdf2_sha256$轮数$盐$散列`。
- 会话：不透明随机令牌（浏览器拿 HttpOnly Cookie），数据库只存令牌的 SHA-256，
  即使数据库泄露也无法直接冒充登录。
- 桌面版默认不启用（`auth_required=false`），网站部署在环境变量里打开。

失败一律返回中文提示，便于直接展示给用户。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from .config import get_settings
from .models import Session, User

log = logging.getLogger("mens.auth")

COOKIE_NAME = "mens_session"
ITERATIONS = 240_000
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
MIN_PASSWORD = 8

LOGIN_WINDOW = timedelta(minutes=5)
LOGIN_MAX_ATTEMPTS = 8
_attempts: dict[str, list[datetime]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def setting(name: str, default):
    """读取配置时容错：测试会用 SimpleNamespace 替换 get_settings()。"""
    return getattr(get_settings(), name, default)


# --------------------------------------------------------------------- 口令
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


# --------------------------------------------------------------------- 账号
def validate(username: str, password: str) -> None:
    if not USERNAME_PATTERN.match((username or "").strip()):
        raise ValueError("用户名需为 3-64 位字母、数字、点、下划线或横线，且以字母或数字开头")
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"口令至少 {MIN_PASSWORD} 位")
    if len(password) > 200:
        raise ValueError("口令过长（上限 200 位）")


def public_user(user: User) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role,
            "created_at": user.created_at.isoformat() if user.created_at else None}


def create_user(db: DbSession, username: str, password: str, role: str = "user") -> User:
    username = (username or "").strip()
    validate(username, password)
    if db.scalar(select(User).where(User.username == username)) is not None:
        raise ValueError(f"用户名已存在：{username}")
    user = User(id=str(uuid.uuid4()), username=username, password_hash=hash_password(password),
                role="admin" if role == "admin" else "user")
    db.add(user)
    db.commit()
    return user


def count_users(db: DbSession) -> int:
    return int(db.scalar(select(func.count()).select_from(User)) or 0)


def set_password(db: DbSession, user: User, password: str) -> None:
    validate(user.username, password)
    user.password_hash = hash_password(password)
    db.commit()


def authenticate(db: DbSession, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == (username or "").strip()))
    if user is None or user.disabled:
        # 即使用户不存在也做一次散列运算，避免用响应时间区分账号是否存在
        verify_password(password, hash_password("dummy-password"))
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = _now()
    db.commit()
    return user


# --------------------------------------------------------------------- 会话
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def start_session(db: DbSession, user: User) -> str:
    token = secrets.token_urlsafe(32)
    expires = _now() + timedelta(days=max(1, setting("session_days", 14)))
    db.add(Session(user_id=user.id, token_hash=_token_hash(token), expires_at=expires))
    # 顺手清掉该用户已过期的会话，避免无限增长
    db.execute(delete(Session).where(Session.user_id == user.id, Session.expires_at < _now()))
    db.commit()
    return token


def resolve_session(db: DbSession, token: str) -> User | None:
    if not token:
        return None
    row = db.scalar(select(Session).where(Session.token_hash == _token_hash(token)))
    if row is None:
        return None
    now = _now()
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < now:
        db.delete(row)
        db.commit()
        return None
    user = db.get(User, row.user_id)
    if user is None or user.disabled:
        return None
    # 每十分钟刷新一次活跃时间，写放大可控
    last_seen = row.last_seen_at if row.last_seen_at.tzinfo else row.last_seen_at.replace(tzinfo=timezone.utc)
    if (now - last_seen).total_seconds() > 600:
        row.last_seen_at = now
        db.commit()
    return user


def end_session(db: DbSession, token: str) -> None:
    if token:
        db.execute(delete(Session).where(Session.token_hash == _token_hash(token)))
        db.commit()


def end_all_sessions(db: DbSession, user: User) -> None:
    db.execute(delete(Session).where(Session.user_id == user.id))
    db.commit()


# --------------------------------------------------------------- 登录限速
def rate_limited(key: str) -> bool:
    """同一用户名/来源在窗口期内失败次数过多则拒绝，纯内存实现，重启即清零。"""
    now = _now()
    history = [stamp for stamp in _attempts.get(key, []) if now - stamp < LOGIN_WINDOW]
    _attempts[key] = history
    return len(history) >= LOGIN_MAX_ATTEMPTS


def record_attempt(key: str) -> None:
    _attempts.setdefault(key, []).append(_now())


def clear_attempts(key: str) -> None:
    _attempts.pop(key, None)


# ------------------------------------------------------------- 首次启动播种
def ensure_bootstrap_admin(db: DbSession) -> None:
    """启用登录且库里还没有账号时，按环境变量创建一个管理员。

    口令留空时生成随机口令并打印一次——只出现在服务端日志里，不写入任何接口响应。
    """
    settings = get_settings()
    if not setting("auth_required", False) or count_users(db) > 0:
        return
    password = setting("auth_admin_password", "") or secrets.token_urlsafe(12)
    username = setting("auth_admin_username", "admin")
    try:
        create_user(db, username, password, role="admin")
    except ValueError as exc:
        log.warning("初始管理员创建失败：%s", exc)
        return
    if setting("auth_admin_password", ""):
        log.info("已创建初始管理员账号：%s（口令来自环境变量）", username)
    else:
        log.warning("已创建初始管理员账号：%s，随机口令：%s —— 请登录后立即修改并妥善保存", username, password)


__all__ = ["COOKIE_NAME", "hash_password", "verify_password", "validate", "public_user", "create_user",
           "count_users", "set_password", "authenticate", "start_session", "resolve_session",
           "end_session", "end_all_sessions", "rate_limited", "record_attempt", "clear_attempts",
           "ensure_bootstrap_admin"]
