from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_", env_file=".env", extra="ignore"
    )

    PROJECT_NAME: str = "clinic-mock"
    VERSION: str = "0.1.0"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000


class LogSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LOG_", env_file=".env", extra="ignore"
    )

    LEVEL: str = "INFO"
    JSON_LOGS: bool = False


class LangfuseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LANGFUSE_", env_file=".env", extra="ignore"
    )

    PUBLIC_KEY: str = ""
    SECRET_KEY: str = ""
    HOST: str = "https://cloud.langfuse.com"
    ENVIRONMENT: str = "sandbox"
    TRACES_ENABLED: bool = True


class MockAuthSettings(BaseSettings):
    """Env-driven API-key registry.

    `API_KEYS` is a comma-separated list of API keys. Each key starts with
    `sk_` and resolves to one `tenant_id`, either explicit (`tenant:key`)
    or auto-derived from the key hash. Default seeds one key for a usable
    out-of-the-box experience.
    """

    model_config = SettingsConfigDict(
        env_prefix="MOCK_", env_file=".env", extra="ignore"
    )

    API_KEYS: str = "sk_dev_demo"


class Settings:
    def __init__(self) -> None:
        self.app = AppSettings()
        self.log = LogSettings()
        self.langfuse = LangfuseSettings()
        self.mock_auth = MockAuthSettings()


settings = Settings()
