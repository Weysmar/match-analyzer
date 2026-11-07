"""The configuration refuses what could not run safely. No database needed."""

import pytest

from ma_api.settings import Settings, SettingsError

URL = "postgresql://x@localhost/x"
SECRET = "x" * 32


def test_development_defaults() -> None:
    settings = Settings.from_env({"API_DATABASE_URL": URL})
    assert not settings.production
    assert not settings.secure_cookies
    assert not settings.epic_login
    assert settings.trusted_proxy_count == 1
    assert settings.site_origin == "http://localhost:3000"


def test_a_development_secret_is_random() -> None:
    first = Settings.from_env({"API_DATABASE_URL": URL})
    second = Settings.from_env({"API_DATABASE_URL": URL})
    assert len(first.session_secret) >= 32
    assert first.session_secret != second.session_secret


def test_the_database_url_is_required() -> None:
    with pytest.raises(SettingsError, match="API_DATABASE_URL"):
        Settings.from_env({})


@pytest.mark.parametrize("secret", ["", "short"])
def test_production_needs_a_real_secret(secret: str) -> None:
    env = {
        "API_DATABASE_URL": URL,
        "APP_ENV": "production",
        "SITE_URL": "https://example.test",
        "SESSION_SECRET": secret,
    }
    with pytest.raises(SettingsError, match="SESSION_SECRET"):
        Settings.from_env(env)


def test_production_needs_https() -> None:
    env = {
        "API_DATABASE_URL": URL,
        "APP_ENV": "production",
        "SITE_URL": "http://example.test",
        "SESSION_SECRET": SECRET,
    }
    with pytest.raises(SettingsError, match="https"):
        Settings.from_env(env)


def test_production_values() -> None:
    settings = Settings.from_env(
        {
            "API_DATABASE_URL": URL,
            "APP_ENV": "production",
            "SITE_URL": "https://example.test/",
            "SESSION_SECRET": SECRET,
            "FEATURE_EPIC_LOGIN": "true",
            "TRUSTED_PROXY_COUNT": "0",
        }
    )
    assert settings.production
    assert settings.secure_cookies
    assert settings.epic_login
    assert settings.trusted_proxy_count == 0
    assert settings.site_origin == "https://example.test"


@pytest.mark.parametrize(
    ("name", "value"), [("SESSION_TTL_DAYS", "soon"), ("SESSION_TTL_DAYS", "0")]
)
def test_invalid_numbers_are_refused(name: str, value: str) -> None:
    with pytest.raises(SettingsError, match=name):
        Settings.from_env({"API_DATABASE_URL": URL, name: value})
