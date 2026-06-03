from __future__ import annotations

import hmac
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import streamlit as st
except ModuleNotFoundError:
    st = None

from .config import ROOT

DEFAULT_TURSO_URL = "libsql://tippster-yannicklimmer.aws-eu-west-1.turso.io"


@dataclass(frozen=True)
class DatabaseSettings:
    url: str
    auth_token: str | None


@dataclass(frozen=True)
class BetfairSettings:
    app_key: str
    session_token: str | None = None
    username: str | None = None
    password: str | None = None
    cert_path: str | None = None
    key_path: str | None = None
    cert_base64: str | None = None
    key_base64: str | None = None

    @property
    def has_session_token(self) -> bool:
        return bool(self.session_token)

    @property
    def has_certificate_login(self) -> bool:
        has_cert_paths = bool(self.cert_path and self.key_path)
        has_cert_payloads = bool(self.cert_base64 and self.key_base64)
        return bool(self.username and self.password and (has_cert_paths or has_cert_payloads))


def _mapping_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): _mapping_to_dict(item) if isinstance(item, Mapping) else item for key, item in value.items()}
    return {}


def _parse_secret_text(raw: str) -> dict[str, Any]:
    raw = raw.strip()
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


def _read_dot_secrets(path: Path = ROOT / ".secrets") -> dict[str, Any]:
    if not path.exists():
        return {}
    return _parse_secret_text(path.read_text(encoding="utf-8"))


def _read_packed_env_secrets() -> dict[str, Any]:
    raw = os.getenv("TIPPNATION_SECRETS_TOML") or os.getenv("TIPPNATION_SECRETS") or ""
    return _parse_secret_text(raw)


def load_secret_sources() -> dict[str, Any]:
    merged: dict[str, Any] = {}
    merged.update(_read_dot_secrets())
    if st is not None:
        try:
            merged.update(_mapping_to_dict(st.secrets))
        except Exception:
            pass
    merged.update(_read_packed_env_secrets())
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
        or os.getenv("TURSO_TOKEN")
        or _get_nested(secrets, ("turso", "auth_token"))
        or _get_nested(secrets, ("turso", "token"))
        or _get_nested(secrets, ("database", "auth_token"))
        or _get_nested(secrets, ("database", "token"))
        or _get_nested(secrets, ("connections", "turso", "auth_token"))
        or secrets.get("TURSO_AUTH_TOKEN")
        or secrets.get("TURSO_TOKEN")
        or secrets.get("auth_token")
        or secrets.get("token")
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
        or _get_nested(secrets, ("betfair", "app_key"))
        or _get_nested(secrets, ("betfair", "token"))
        or secrets.get("BETFAIR_APP_KEY")
        or secrets.get("BF_TOKEN")
    )
    session_token = (
        os.getenv("BETFAIR_SESSION")
        or os.getenv("BF_SESSION")
        or _get_nested(secrets, ("betfair", "session"))
        or _get_nested(secrets, ("betfair", "session_token"))
        or secrets.get("BETFAIR_SESSION")
        or secrets.get("BF_SESSION")
    )
    username = (
        os.getenv("BETFAIR_USERNAME")
        or _get_nested(secrets, ("betfair", "username"))
        or secrets.get("BETFAIR_USERNAME")
        or secrets.get("BF_USERNAME")
    )
    password = (
        os.getenv("BETFAIR_PASSWORD")
        or _get_nested(secrets, ("betfair", "password"))
        or secrets.get("BETFAIR_PASSWORD")
        or secrets.get("BF_PASSWORD")
    )
    cert_path = (
        os.getenv("BETFAIR_CERT_PATH")
        or _get_nested(secrets, ("betfair", "cert_path"))
        or secrets.get("BETFAIR_CERT_PATH")
    )
    key_path = (
        os.getenv("BETFAIR_KEY_PATH")
        or _get_nested(secrets, ("betfair", "key_path"))
        or secrets.get("BETFAIR_KEY_PATH")
    )
    cert_base64 = (
        os.getenv("BETFAIR_CERT_BASE64")
        or _get_nested(secrets, ("betfair", "cert_base64"))
        or secrets.get("BETFAIR_CERT_BASE64")
    )
    key_base64 = (
        os.getenv("BETFAIR_KEY_BASE64")
        or _get_nested(secrets, ("betfair", "key_base64"))
        or secrets.get("BETFAIR_KEY_BASE64")
    )
    if not app_key:
        return None
    settings = BetfairSettings(
        app_key=str(app_key),
        session_token=str(session_token) if session_token else None,
        username=str(username) if username else None,
        password=str(password) if password else None,
        cert_path=str(cert_path) if cert_path else None,
        key_path=str(key_path) if key_path else None,
        cert_base64=str(cert_base64) if cert_base64 else None,
        key_base64=str(key_base64) if key_base64 else None,
    )
    if not settings.has_session_token and not settings.has_certificate_login:
        return None
    return settings


def get_api_football_key(source: Mapping[str, Any] | None = None) -> str | None:
    secrets = source or load_secret_sources()
    value = (
        os.getenv("API_FOOTBALL_KEY")
        or os.getenv("APISPORTS_KEY")
        or _get_nested(secrets, ("api_football", "key"))
        or _get_nested(secrets, ("api_football", "api_key"))
        or _get_nested(secrets, ("api_sports", "key"))
        or _get_nested(secrets, ("api_sports", "api_key"))
        or secrets.get("API_FOOTBALL_KEY")
        or secrets.get("APISPORTS_KEY")
    )
    return str(value) if value else None


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
