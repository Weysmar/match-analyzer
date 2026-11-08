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
            "S3_ENDPOINT": "https://store.example.test",
            "S3_BUCKET": "a-bucket",
            "S3_ACCESS_KEY_ID": "a",
            "S3_SECRET_ACCESS_KEY": "b",
            "FEATURE_EPIC_LOGIN": "true",
            "EPIC_CLIENT_ID": "a",
            "EPIC_CLIENT_SECRET": "b",
            "EPIC_REDIRECT_URI": "https://example.test/callback",
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


def test_a_stand_in_for_steam_serves_tests_only() -> None:
    """End-to-end tests sign in through a fake provider (A70): production refuses one."""
    fake = "http://127.0.0.1:8090/openid/login"
    assert Settings.from_env({"API_DATABASE_URL": URL}).steam_openid_url.startswith(
        "https://steamcommunity.com/"
    )
    assert (
        Settings.from_env({"API_DATABASE_URL": URL, "STEAM_OPENID_URL": fake}).steam_openid_url
        == fake
    )
    env = {
        "API_DATABASE_URL": URL,
        "APP_ENV": "production",
        "SITE_URL": "https://example.test",
        "SESSION_SECRET": SECRET,
        "S3_ENDPOINT": "https://store.example.test",
        "S3_BUCKET": "a-bucket",
        "S3_ACCESS_KEY_ID": "a",
        "S3_SECRET_ACCESS_KEY": "b",
        "STEAM_OPENID_URL": fake,
    }
    with pytest.raises(SettingsError, match="STEAM_OPENID_URL"):
        Settings.from_env(env)


def test_production_needs_an_object_store() -> None:
    env = {
        "API_DATABASE_URL": URL,
        "APP_ENV": "production",
        "SITE_URL": "https://example.test",
        "SESSION_SECRET": SECRET,
    }
    with pytest.raises(SettingsError, match="S3_ENDPOINT"):
        Settings.from_env(env)


def test_upload_limits_come_from_the_environment() -> None:
    settings = Settings.from_env(
        {
            "API_DATABASE_URL": URL,
            "UPLOAD_MAX_BYTES": "10",
            "UPLOAD_MAX_FILES_PER_BATCH": "2",
            "UPLOAD_URL_TTL_S": "30",
            "RATE_UPLOAD_ANON_PER_DAY": "3",
            "RATE_UPLOAD_IP_PER_DAY": "4",
            "RATE_UPLOAD_USER_PER_DAY": "5",
            "S3_SECRET_ACCESS_KEY": "the-secret-key",
        }
    )
    assert settings.upload_max_bytes == 10
    assert settings.upload_max_files == 2
    assert settings.upload_url_ttl_s == 30
    assert settings.rate_upload_anon_per_day == 3
    assert settings.rate_upload_ip_per_day == 4
    assert settings.rate_upload_user_per_day == 5
    assert "the-secret-key" not in repr(settings)
