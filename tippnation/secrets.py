from __future__ import annotations

import hmac
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st

from .config import ROOT

DEFAULT_TURSO_URL = "libsql://tippster-yannicklimmer.aws-eu-west-1.turso.io"


@dataclass(frozen=True)
class DatabaseSettings:
    url: str
    auth_token: str | None


@dataclass(frozen=True)
class BetfairSettings:
    app_key: str
    session_token: str


def _mapping_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): _mapping_to_dict(item) if isinstance(item, Mapping) else item for key, item in value.items()}
    return {}


def _read_dot_secrets(path: Path = ROOT / ".secrets") -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    try:
        return tomllib.loads(raw)
    except tomllib.TOMLDecodeError:
        parsed: dict[str, Any] = {}
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            parsed[key.strip()] = value.strip().strip('"').strip("'")
        return parsed


def load_secret_sources() -> dict[str, Any]:
    merged: dict[str, Any] = {}
    merged.update(_read_dot_secrets())
    try:
        merged.update(_mapping_to_dict(st.secrets))
    except Exception:
        pass
    return merged


def _get_nested(source: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = source
    for item in path:
        if not isinstance(current, Mapping) or item not in current:
            return None
        current = current[item]
    return current


def get_database_settings(source: Mapping[str, Any] | None = None) -> DatabaseSettings:
    secrets = source or load_secret_sources()
    url = (
        os.getenv("TURSO_DATABASE_URL")
        or str(secrets.get("TURSO_DATABASE_URL", "") or "")
        or str(_get_nested(secrets, ("turso", "url")) or "")
        or str(_get_nested(secrets, ("database", "url")) or "")
        or str(_get_nested(secrets, ("connections", "turso", "url")) or "")
    )
    token = (
        os.getenv("TURSO_AUTH_TOKEN")
        or secrets.get("TURSO_AUTH_TOKEN")
        or secrets.get("auth_token")
        or secrets.get("token")
        or _get_nested(secrets, ("turso", "auth_token"))
        or _get_nested(secrets, ("turso", "token"))
        or _get_nested(secrets, ("database", "auth_token"))
        or _get_nested(secrets, ("database", "token"))
        or _get_nested(secrets, ("connections", "turso", "auth_token"))
    )
    if not url and token:
        url = DEFAULT_TURSO_URL
    if not url:
        url = "data/tippnation.sqlite3"
    return DatabaseSettings(url=str(url), auth_token=str(token) if token else None)


def get_betfair_settings(source: Mapping[str, Any] | None = None) -> BetfairSettings | None:
    secrets = source or load_secret_sources()
    app_key = (
        os.getenv("BETFAIR_APP_KEY")
        or os.getenv("BF_TOKEN")
        or secrets.get("BETFAIR_APP_KEY")
        or secrets.get("BF_TOKEN")
        or _get_nested(secrets, ("betfair", "app_key"))
        or _get_nested(secrets, ("betfair", "token"))
    )
    session_token = (
        os.getenv("BETFAIR_SESSION")
        or os.getenv("BF_SESSION")
        or secrets.get("BETFAIR_SESSION")
        or secrets.get("BF_SESSION")
        or _get_nested(secrets, ("betfair", "session"))
        or _get_nested(secrets, ("betfair", "session_token"))
    )
    if not app_key or not session_token:
        return None
    return BetfairSettings(app_key=str(app_key), session_token=str(session_token))


def get_admin_password(source: Mapping[str, Any] | None = None) -> str | None:
    secrets = source or load_secret_sources()
    value = _get_nested(secrets, ("Admin", "Password")) or _get_nested(secrets, ("admin", "password"))
    return str(value) if value else None


def list_auth_users(source: Mapping[str, Any] | None = None) -> list[str]:
    secrets = source or load_secret_sources()
    users = _get_nested(secrets, ("users",))
    if isinstance(users, Mapping):
        return sorted(str(name) for name, value in users.items() if isinstance(value, Mapping) and ("password" in value or "Password" in value))
    ignored = {
        "Admin",
        "admin",
        "turso",
        "database",
        "connections",
        "TURSO_DATABASE_URL",
        "TURSO_AUTH_TOKEN",
    }
    return sorted(
        str(name)
        for name, value in secrets.items()
        if name not in ignored and isinstance(value, Mapping) and ("Password" in value or "password" in value)
    )


def get_user_password(username: str, source: Mapping[str, Any] | None = None) -> str | None:
    secrets = source or load_secret_sources()
    value = (
        _get_nested(secrets, ("users", username, "password"))
        or _get_nested(secrets, ("users", username, "Password"))
        or _get_nested(secrets, (username, "Password"))
        or _get_nested(secrets, (username, "password"))
    )
    return str(value) if value else None


def verify_password(input_password: str, stored_password: str | None) -> bool:
    if not stored_password:
        return False
    return hmac.compare_digest(input_password, stored_password)
