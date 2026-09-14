from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_")

    PROJECT_NAME: str = "clinic-mock"
    VERSION: str = "0.1.0"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000


class LogSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOG_")

    LEVEL: str = "INFO"
    JSON_LOGS: bool = False


class LangfuseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LANGFUSE_")

    PUBLIC_KEY: str = ""
    SECRET_KEY: str = ""
    HOST: str = "https://cloud.langfuse.com"
    ENVIRONMENT: str = "sandbox"
    TRACES_ENABLED: bool = True


class MockAuthSettings(BaseSettings):
    """Env-driven tenant/API-key registry.

    `API_KEYS` is a comma-separated list of `tenant_id:sk-xxx` entries.
    Each api_key must start with `sk-` and resolves to its tenant.
    Default seeds one tenant (`tenant_demo`) with key `sk_dev_demo` so
    the mock is usable out-of-the-box without env tweaks.
    """

    model_config = SettingsConfigDict(env_prefix="MOCK_")

    API_KEYS: str = "tenant_demo:sk-dev-demo"


class Settings:
    def __init__(self) -> None:
        self.app = AppSettings()
        self.log = LogSettings()
        self.langfuse = LangfuseSettings()
        self.mock_auth = MockAuthSettings()


settings = Settings()
