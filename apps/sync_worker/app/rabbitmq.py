from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import typer
from aio_pika import (
    DeliveryMode,
    ExchangeType,
    Message,
    connect_robust,
)
from aio_pika.abc import (
    AbstractRobustChannel,
    AbstractRobustConnection,
    AbstractRobustExchange,
    AbstractRobustQueue,
)

from app.config import Settings, get_settings


def validate_legal_entity_id(
    value: int,
) -> int:
    if value < 1:
        raise ValueError(
            "legal_entity_id должен быть больше 0."
        )

    return value


def build_entity_resource_name(
    *,
    base_name: str,
    legal_entity_id: int,
) -> str:
    prepared_base_name = base_name.strip()

    if not prepared_base_name:
        raise ValueError(
            "Базовое имя RabbitMQ "
            "не может быть пустым."
        )

    prepared_entity_id = (
        validate_legal_entity_id(
            legal_entity_id
        )
    )

    result = (
        f"{prepared_base_name}."
        f"{prepared_entity_id}"
    )

    if len(result) > 255:
        raise ValueError(
            "Итоговое имя ресурса RabbitMQ "
            "длиннее 255 символов."
        )

    return result


@dataclass(slots=True)
class RabbitMQTopology:
    """
    RabbitMQ-топология одной организации.

    Основная и retry-очереди создаются отдельно
    для каждого legal_entity_id.
    Dead-letter очередь является общей.
    """

    settings: Settings
    legal_entity_id: int

    connection: AbstractRobustConnection
    channel: AbstractRobustChannel
    exchange: AbstractRobustExchange

    sync_queue: AbstractRobustQueue
    retry_queue: AbstractRobustQueue
    dead_queue: AbstractRobustQueue

    sync_routing_key: str
    retry_routing_key: str

    async def close(self) -> None:
        if not self.connection.is_closed:
            await self.connection.close()

    async def __aenter__(
        self,
    ) -> RabbitMQTopology:
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        await self.close()

    async def publish_json(
        self,
        *,
        routing_key: str,
        payload: dict[str, Any],
        message_id: str | None = None,
        correlation_id: str | None = None,
        message_type: str | None = None,
        headers: dict[str, Any] | None = None,
    ) -> str:
        prepared_routing_key = (
            routing_key.strip()
        )

        if not prepared_routing_key:
            raise ValueError(
                "routing_key не может быть пустым."
            )

        prepared_message_id = (
            message_id.strip()
            if message_id is not None
            else str(
                uuid.uuid4()
            )
        )

        if not prepared_message_id:
            raise ValueError(
                "message_id не может быть пустым."
            )

        prepared_correlation_id = (
            correlation_id.strip()
            if correlation_id is not None
            else None
        )

        prepared_message_type = (
            message_type.strip()
            if message_type is not None
            else None
        )

        prepared_headers = (
            dict(
                headers
            )
            if headers is not None
            else {}
        )

        prepared_headers[
            "legal_entity_id"
        ] = self.legal_entity_id

        body = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        ).encode(
            "utf-8"
        )

        message = Message(
            body=body,
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=(
                DeliveryMode.PERSISTENT
            ),
            message_id=prepared_message_id,
            correlation_id=(
                prepared_correlation_id
            ),
            type=prepared_message_type,
            timestamp=datetime.now(
                timezone.utc
            ),
            headers=prepared_headers,
        )

        await self.exchange.publish(
            message,
            routing_key=prepared_routing_key,
            mandatory=True,
        )

        return prepared_message_id

    async def publish_sync_job(
        self,
        *,
        payload: dict[str, Any],
        message_id: str | None = None,
        correlation_id: str | None = None,
        headers: dict[str, Any] | None = None,
    ) -> str:
        return await self.publish_json(
            routing_key=self.sync_routing_key,
            payload=payload,
            message_id=message_id,
            correlation_id=correlation_id,
            message_type=(
                "sync_legal_entity"
            ),
            headers=headers,
        )

    async def publish_retry_job(
        self,
        *,
        payload: dict[str, Any],
        message_id: str | None = None,
        correlation_id: str | None = None,
        headers: dict[str, Any] | None = None,
    ) -> str:
        return await self.publish_json(
            routing_key=self.retry_routing_key,
            payload=payload,
            message_id=message_id,
            correlation_id=correlation_id,
            message_type=(
                "sync_legal_entity_retry"
            ),
            headers=headers,
        )

    async def publish_dead_job(
        self,
        *,
        payload: dict[str, Any],
        message_id: str | None = None,
        correlation_id: str | None = None,
        headers: dict[str, Any] | None = None,
    ) -> str:
        return await self.publish_json(
            routing_key=(
                self.settings
                .rabbitmq_dead_routing_key
            ),
            payload=payload,
            message_id=message_id,
            correlation_id=correlation_id,
            message_type=(
                "sync_legal_entity_dead"
            ),
            headers=headers,
        )


async def connect_rabbitmq(
    *,
    legal_entity_id: int,
    settings: Settings | None = None,
) -> RabbitMQTopology:
    """
    Подключается к RabbitMQ и объявляет очереди
    конкретной организации.
    """

    prepared_entity_id = (
        validate_legal_entity_id(
            legal_entity_id
        )
    )

    active_settings = (
        settings
        if settings is not None
        else get_settings()
    )

    sync_queue_name = (
        build_entity_resource_name(
            base_name=(
                active_settings
                .rabbitmq_sync_queue_name
            ),
            legal_entity_id=(
                prepared_entity_id
            ),
        )
    )

    retry_queue_name = (
        build_entity_resource_name(
            base_name=(
                active_settings
                .rabbitmq_retry_queue_name
            ),
            legal_entity_id=(
                prepared_entity_id
            ),
        )
    )

    sync_routing_key = (
        build_entity_resource_name(
            base_name=(
                active_settings
                .rabbitmq_sync_routing_key
            ),
            legal_entity_id=(
                prepared_entity_id
            ),
        )
    )

    retry_routing_key = (
        build_entity_resource_name(
            base_name=(
                active_settings
                .rabbitmq_retry_routing_key
            ),
            legal_entity_id=(
                prepared_entity_id
            ),
        )
    )

    retry_ttl_ms = (
        active_settings
        .rabbitmq_retry_delay_seconds
        * 1000
    )

    connection = await connect_robust(
        host=active_settings.rabbitmq_host,
        port=active_settings.rabbitmq_port,
        login=active_settings.rabbitmq_user,
        password=(
            active_settings.rabbitmq_password
        ),
        virtualhost=(
            active_settings.rabbitmq_vhost
        ),
        timeout=(
            active_settings
            .rabbitmq_connection_timeout_seconds
        ),
        heartbeat=(
            active_settings
            .rabbitmq_heartbeat_seconds
        ),
        reconnect_interval=5.0,
        fail_fast="1",
        client_properties={
            "connection_name": (
                active_settings
                .rabbitmq_connection_name
                + "-"
                + str(
                    prepared_entity_id
                )
            ),
        },
    )

    try:
        channel = await connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )

        await channel.set_qos(
            prefetch_count=(
                active_settings
                .rabbitmq_prefetch_count
            )
        )

        exchange = await channel.declare_exchange(
            name=(
                active_settings
                .rabbitmq_exchange_name
            ),
            type=ExchangeType.DIRECT,
            durable=True,
            auto_delete=False,
            robust=True,
        )

        sync_queue = await channel.declare_queue(
            name=sync_queue_name,
            durable=True,
            exclusive=False,
            auto_delete=False,
            arguments={
                "x-dead-letter-exchange": (
                    active_settings
                    .rabbitmq_exchange_name
                ),
                "x-dead-letter-routing-key": (
                    active_settings
                    .rabbitmq_dead_routing_key
                ),
            },
            robust=True,
        )

        retry_queue = await channel.declare_queue(
            name=retry_queue_name,
            durable=True,
            exclusive=False,
            auto_delete=False,
            arguments={
                "x-message-ttl": (
                    retry_ttl_ms
                ),
                "x-dead-letter-exchange": (
                    active_settings
                    .rabbitmq_exchange_name
                ),
                "x-dead-letter-routing-key": (
                    sync_routing_key
                ),
            },
            robust=True,
        )

        dead_queue = await channel.declare_queue(
            name=(
                active_settings
                .rabbitmq_dead_queue_name
            ),
            durable=True,
            exclusive=False,
            auto_delete=False,
            robust=True,
        )

        await sync_queue.bind(
            exchange=exchange,
            routing_key=sync_routing_key,
            robust=True,
        )

        await retry_queue.bind(
            exchange=exchange,
            routing_key=retry_routing_key,
            robust=True,
        )

        await dead_queue.bind(
            exchange=exchange,
            routing_key=(
                active_settings
                .rabbitmq_dead_routing_key
            ),
            robust=True,
        )

        return RabbitMQTopology(
            settings=active_settings,
            legal_entity_id=(
                prepared_entity_id
            ),
            connection=connection,
            channel=channel,
            exchange=exchange,
            sync_queue=sync_queue,
            retry_queue=retry_queue,
            dead_queue=dead_queue,
            sync_routing_key=(
                sync_routing_key
            ),
            retry_routing_key=(
                retry_routing_key
            ),
        )

    except Exception:
        await connection.close()
        raise


async def declare_topology(
    *,
    legal_entity_id: int,
) -> None:
    topology = await connect_rabbitmq(
        legal_entity_id=legal_entity_id
    )

    try:
        result = {
            "legal_entity_id": (
                topology.legal_entity_id
            ),
            "exchange": (
                topology.exchange.name
            ),
            "sync_queue": (
                topology.sync_queue.name
            ),
            "sync_routing_key": (
                topology.sync_routing_key
            ),
            "retry_queue": (
                topology.retry_queue.name
            ),
            "retry_routing_key": (
                topology.retry_routing_key
            ),
            "retry_delay_seconds": (
                topology.settings
                .rabbitmq_retry_delay_seconds
            ),
            "dead_queue": (
                topology.dead_queue.name
            ),
            "dead_routing_key": (
                topology.settings
                .rabbitmq_dead_routing_key
            ),
            "prefetch_count": (
                topology.settings
                .rabbitmq_prefetch_count
            ),
        }

        typer.echo(
            json.dumps(
                result,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            )
        )

    finally:
        await topology.close()


def main(
    legal_entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
        help=(
            "ID карточки организации, "
            "для которой создаются очереди."
        ),
    ),
) -> None:
    try:
        asyncio.run(
            declare_topology(
                legal_entity_id=(
                    legal_entity_id
                )
            )
        )

    except Exception as exc:
        typer.echo(
            "ERROR: "
            f"{type(exc).__name__}: "
            f"{exc}",
            err=True,
        )

        raise typer.Exit(
            code=1
        ) from exc


if __name__ == "__main__":
    typer.run(
        main
    )