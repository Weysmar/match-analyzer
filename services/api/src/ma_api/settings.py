"""The API's configuration, read once from the environment."""

import os
import secrets
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass, field

PREFIX = "/api/v1"


class SettingsError(ValueError):
    """The configuration cannot run safely."""


def _integer(env: Mapping[str, str], name: str, default: int, minimum: int = 1) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SettingsError(f"{name} must be a whole number") from None
    if value < minimum:
        raise SettingsError(f"{name} must be at least {minimum}")
    return value


def _flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    site_url: str = "http://localhost:3000"
    production: bool = False
    session_secret: str = field(default="development", repr=False)
    session_ttl_days: int = 30
    anonymous_session_ttl_days: int = 30
    rate_auth_ip_per_minute: int = 20
    trusted_proxy_count: int = 1
    epic_login: bool = False
    database_timeout_s: float = 5.0
    steam_openid_url: str = "https://steamcommunity.com/openid/login"
    epic_client_id: str = ""
    epic_client_secret: str = field(default="", repr=False)
    epic_redirect_uri: str = ""
    epic_authorize_url: str = "https://www.epicgames.com/id/authorize"
    epic_token_url: str = "https://api.epicgames.dev/epic/oauth/v2/token"
    epic_userinfo_url: str = "https://api.epicgames.dev/epic/oauth/v2/userInfo"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        values = os.environ if env is None else env
        database_url = values.get("API_DATABASE_URL", "").strip()
        if not database_url:
            raise SettingsError("API_DATABASE_URL is not set")
        production = values.get("APP_ENV", "development").strip() == "production"
        site_url = values.get("SITE_URL", "http://localhost:3000").strip().rstrip("/")
        secret = values.get("SESSION_SECRET", "").strip()
        if production:
            if len(secret) < 32:
                raise SettingsError("SESSION_SECRET needs at least 32 characters in production")
            if not site_url.startswith("https://"):
                raise SettingsError("SITE_URL must use https in production")
        epic_login = _flag(values, "FEATURE_EPIC_LOGIN")
        epic = {
            name: values.get(name, "").strip()
            for name in ("EPIC_CLIENT_ID", "EPIC_CLIENT_SECRET", "EPIC_REDIRECT_URI")
        }
        if epic_login:
            for name, value in epic.items():
                if not value:
                    raise SettingsError(f"{name} is needed with FEATURE_EPIC_LOGIN")
        return cls(
            database_url=database_url,
            site_url=site_url,
            production=production,
            # A fresh one at each start in development: nothing signed has to outlive a restart.
            session_secret=secret or secrets.token_hex(32),
            session_ttl_days=_integer(values, "SESSION_TTL_DAYS", 30),
            anonymous_session_ttl_days=_integer(values, "ANON_SESSION_TTL_DAYS", 30),
            rate_auth_ip_per_minute=_integer(values, "RATE_AUTH_IP_PER_MIN", 20),
            trusted_proxy_count=_integer(values, "TRUSTED_PROXY_COUNT", 1, minimum=0),
            epic_login=epic_login,
            epic_client_id=epic["EPIC_CLIENT_ID"],
            epic_client_secret=epic["EPIC_CLIENT_SECRET"],
            epic_redirect_uri=epic["EPIC_REDIRECT_URI"],
        )

    @property
    def secure_cookies(self) -> bool:
        """`Secure` cookies only travel over https: not on the development server."""
        return self.site_url.startswith("https://")

    @property
    def site_origin(self) -> str:
        parts = urllib.parse.urlsplit(self.site_url)
        return f"{parts.scheme}://{parts.netloc}"
