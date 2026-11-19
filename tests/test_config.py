from pathlib import Path

import pytest

from ask_ai.config import Settings


def test_reads_keys_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for name in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "CLAUDE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ANTHROPIC_API_KEY=sk-ant-test\nGEMINI_API_KEY=gm-test\nCLAUDE_MODEL=other\n"
    )

    settings = Settings(_env_file=env_file)

    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-test"
    assert settings.gemini_api_key.get_secret_value() == "gm-test"
    assert settings.claude_model == "other"
    assert "sk-ant-test" not in repr(settings)


def test_environment_overrides_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=from-file\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")

    settings = Settings(_env_file=env_file)

    assert settings.anthropic_api_key.get_secret_value() == "from-env"


def test_keys_default_to_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for name in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=tmp_path / "missing.env")

    assert settings.anthropic_api_key is None
    assert settings.gemini_api_key is None


def test_empty_values_count_as_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for name in ("ANTHROPIC_API_KEY", "JWT_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=\nJWT_SECRET_KEY=\n")

    settings = Settings(_env_file=env_file)

    assert settings.anthropic_api_key is None
    assert settings.jwt_secret_key is None
