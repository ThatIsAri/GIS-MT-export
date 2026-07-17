from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        extra="ignore",
    )

    # MySQL
    db_host: str = Field(
        default="mysql",
        validation_alias="DB_HOST",
    )

    db_port: int = Field(
        default=3306,
        validation_alias="DB_PORT",
    )

    db_name: str = Field(
        default="gis_mt",
        validation_alias="DB_NAME",
    )

    db_user: str = Field(
        default="gis_mt_app",
        validation_alias="DB_USER",
    )

    db_password: str = Field(
        validation_alias="DB_PASSWORD",
    )

    # ГИС МТ
    gis_mt_true_api_v3_url: str = Field(
        default="https://markirovka.crpt.ru/api/v3/true-api",
        validation_alias="GIS_MT_TRUE_API_V3_URL",
    )

    gis_mt_true_api_v4_url: str = Field(
        default="https://markirovka.crpt.ru/api/v4/true-api",
        validation_alias="GIS_MT_TRUE_API_V4_URL",
    )

    # HTTP
    http_timeout_seconds: float = Field(
        default=60.0,
        validation_alias="HTTP_TIMEOUT_SECONDS",
    )

    http_max_attempts: int = Field(
        default=5,
        validation_alias="HTTP_MAX_ATTEMPTS",
    )

    user_agent: str = Field(
        default="CZ-Async-Sync-Worker/0.1",
        validation_alias="GIS_MT_USER_AGENT",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()