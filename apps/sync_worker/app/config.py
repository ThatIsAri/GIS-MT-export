from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        extra="ignore",
    )

    # MySQL
    db_host: str = Field(
        default="mysql",
        min_length=1,
        validation_alias="DB_HOST",
    )

    db_port: int = Field(
        default=3306,
        ge=1,
        le=65535,
        validation_alias="DB_PORT",
    )

    db_name: str = Field(
        default="gis_mt",
        min_length=1,
        validation_alias="DB_NAME",
    )

    db_user: str = Field(
        default="gis_mt_app",
        min_length=1,
        validation_alias="DB_USER",
    )

    db_password: str = Field(
        min_length=1,
        validation_alias="DB_PASSWORD",
    )

    # RabbitMQ: подключение
    rabbitmq_host: str = Field(
        default="rabbitmq",
        min_length=1,
        validation_alias="RABBITMQ_HOST",
    )

    rabbitmq_port: int = Field(
        default=5672,
        ge=1,
        le=65535,
        validation_alias="RABBITMQ_PORT",
    )

    rabbitmq_user: str = Field(
        default="gis_mt",
        min_length=1,
        validation_alias="RABBITMQ_USER",
    )

    rabbitmq_password: str = Field(
        min_length=1,
        validation_alias="RABBITMQ_PASSWORD",
    )

    rabbitmq_vhost: str = Field(
        default="/",
        min_length=1,
        validation_alias="RABBITMQ_VHOST",
    )

    rabbitmq_connection_name: str = Field(
        default="gis-mt-sync-worker",
        min_length=1,
        max_length=128,
        validation_alias=(
            "RABBITMQ_CONNECTION_NAME"
        ),
    )

    rabbitmq_heartbeat_seconds: int = Field(
        default=60,
        ge=10,
        le=3600,
        validation_alias=(
            "RABBITMQ_HEARTBEAT_SECONDS"
        ),
    )

    rabbitmq_connection_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=300,
        validation_alias=(
            "RABBITMQ_CONNECTION_TIMEOUT_SECONDS"
        ),
    )

    # RabbitMQ: обработка сообщений
    rabbitmq_prefetch_count: int = Field(
        default=1,
        ge=1,
        le=1000,
        validation_alias=(
            "RABBITMQ_PREFETCH_COUNT"
        ),
    )

    rabbitmq_consumer_count: int = Field(
        default=1,
        ge=1,
        le=32,
        validation_alias=(
            "RABBITMQ_CONSUMER_COUNT"
        ),
    )

    rabbitmq_retry_delay_seconds: int = Field(
        default=300,
        ge=1,
        le=86400,
        validation_alias=(
            "RABBITMQ_RETRY_DELAY_SECONDS"
        ),
    )

    rabbitmq_max_retries: int = Field(
        default=3,
        ge=0,
        le=100,
        validation_alias=(
            "RABBITMQ_MAX_RETRIES"
        ),
    )

    # RabbitMQ: exchange и маршрутизация
    rabbitmq_exchange_name: str = Field(
        default="gis_mt.jobs",
        min_length=1,
        max_length=255,
        validation_alias=(
            "RABBITMQ_EXCHANGE_NAME"
        ),
    )

    rabbitmq_sync_queue_name: str = Field(
        default=(
            "gis_mt.jobs.sync_legal_entity"
        ),
        min_length=1,
        max_length=255,
        validation_alias=(
            "RABBITMQ_SYNC_QUEUE_NAME"
        ),
    )

    rabbitmq_sync_routing_key: str = Field(
        default="jobs.sync_legal_entity",
        min_length=1,
        max_length=255,
        validation_alias=(
            "RABBITMQ_SYNC_ROUTING_KEY"
        ),
    )

    rabbitmq_retry_queue_name: str = Field(
        default=(
            "gis_mt.jobs.sync_legal_entity.retry"
        ),
        min_length=1,
        max_length=255,
        validation_alias=(
            "RABBITMQ_RETRY_QUEUE_NAME"
        ),
    )

    rabbitmq_retry_routing_key: str = Field(
        default=(
            "jobs.sync_legal_entity.retry"
        ),
        min_length=1,
        max_length=255,
        validation_alias=(
            "RABBITMQ_RETRY_ROUTING_KEY"
        ),
    )

    rabbitmq_dead_queue_name: str = Field(
        default=(
            "gis_mt.jobs.sync_legal_entity.dead"
        ),
        min_length=1,
        max_length=255,
        validation_alias=(
            "RABBITMQ_DEAD_QUEUE_NAME"
        ),
    )

    rabbitmq_dead_routing_key: str = Field(
        default=(
            "jobs.sync_legal_entity.dead"
        ),
        min_length=1,
        max_length=255,
        validation_alias=(
            "RABBITMQ_DEAD_ROUTING_KEY"
        ),
    )

    # ГИС МТ
    gis_mt_true_api_v3_url: str = Field(
        default=(
            "https://markirovka.crpt.ru/"
            "api/v3/true-api"
        ),
        min_length=1,
        validation_alias=(
            "GIS_MT_TRUE_API_V3_URL"
        ),
    )

    gis_mt_true_api_v4_url: str = Field(
        default=(
            "https://markirovka.crpt.ru/"
            "api/v4/true-api"
        ),
        min_length=1,
        validation_alias=(
            "GIS_MT_TRUE_API_V4_URL"
        ),
    )

    # HTTP
    http_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        le=600,
        validation_alias=(
            "HTTP_TIMEOUT_SECONDS"
        ),
    )

    http_max_attempts: int = Field(
        default=5,
        ge=1,
        le=100,
        validation_alias=(
            "HTTP_MAX_ATTEMPTS"
        ),
    )

    user_agent: str = Field(
        default=(
            "CZ-Async-Sync-Worker/0.1"
        ),
        min_length=1,
        max_length=255,
        validation_alias=(
            "GIS_MT_USER_AGENT"
        ),
    )

    # Совместимость со старыми именами настроек.
    #
    # rabbitmq_jobs.py и rabbitmq_worker.py пока используют
    # старые короткие имена. Новые модули используют имена
    # с суффиксами _name и _seconds.
    #
    # После окончательного рефакторинга RabbitMQ-модулей
    # эти свойства можно будет удалить.

    @property
    def rabbitmq_heartbeat(self) -> int:
        return self.rabbitmq_heartbeat_seconds

    @property
    def rabbitmq_timeout(self) -> float:
        return self.rabbitmq_connection_timeout_seconds

    @property
    def rabbitmq_exchange(self) -> str:
        return self.rabbitmq_exchange_name

    @property
    def rabbitmq_sync_queue(self) -> str:
        return self.rabbitmq_sync_queue_name

    @property
    def rabbitmq_retry_queue(self) -> str:
        return self.rabbitmq_retry_queue_name

    @property
    def rabbitmq_dead_queue(self) -> str:
        return self.rabbitmq_dead_queue_name


@lru_cache
def get_settings() -> Settings:
    return Settings()