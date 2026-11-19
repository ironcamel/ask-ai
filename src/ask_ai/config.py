from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, read from environment variables or a local `.env` file.

    Environment variables take precedence over the `.env` file. Names are
    case-insensitive, e.g. `ANTHROPIC_API_KEY` sets `anthropic_api_key`.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    database_url: str = "sqlite:///./ask_ai.db"

    # When a key is unset, each SDK falls back to its own credential lookup.
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    # Signs login tokens. Generate one with: openssl rand -hex 32
    jwt_secret_key: SecretStr | None = None
    access_token_expire_minutes: int = 30

    claude_model: str = "claude-opus-5-5"
    gemini_model: str = "gemini-4-carbon"


settings = Settings()
