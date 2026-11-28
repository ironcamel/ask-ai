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

    database_url: str = "postgresql+psycopg://localhost/ask_ai"

    # When a key is unset, each SDK falls back to its own credential lookup.
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    # Signs login tokens. Generate one with: openssl rand -hex 32
    jwt_secret_key: SecretStr | None = None
    access_token_expire_minutes: int = 30
    # How long a login lasts without being used. Each refresh restarts it.
    refresh_token_expire_days: int = 14

    # Password reset emails. When SMTP_HOST is unset, they're logged instead of
    # sent, which is handy for local development.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    email_from: str = "ask-ai <noreply@localhost>"
    # The page where users choose a new password, e.g.
    # https://example.com/reset-password. The email links to it with
    # ?token=... added. When unset, the email contains just the token.
    password_reset_url: str | None = None
    password_reset_token_expire_minutes: int = 60

    claude_model: str = "claude-opus-5-5"
    gemini_model: str = "gemini-4-carbon"


settings = Settings()
