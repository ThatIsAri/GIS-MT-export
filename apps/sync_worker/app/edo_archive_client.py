from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Final
from urllib.parse import quote

import httpx

from app.client import (
    GisMtAuthError,
    GisMtError,
    GisMtHttpError,
)
from app.config import Settings


@dataclass(frozen=True, slots=True)
class EdoArchiveResult:
    document_id: str
    endpoint: str
    status_code: int
    elapsed_ms: int
    content_type: str
    content_disposition: str | None
    content: bytes


class EdoArchiveClient:
    """
    Клиент официального метода True API
    для получения входящего документа ЭДО.
    """

    RETRYABLE_STATUS_CODES: Final[set[int]] = {
        429,
        500,
        502,
        503,
        504,
    }

    def __init__(
        self,
        settings: Settings,
        token: str,
    ) -> None:
        prepared_token = token.strip()

        if not prepared_token:
            raise ValueError(
                "Токен ГИС МТ пуст."
            )

        self._settings = settings

        self._headers = {
            "Authorization": (
                f"Bearer {prepared_token}"
            ),
            "Accept": (
                "application/zip, "
                "application/octet-stream, "
                "application/xml, "
                "text/xml, "
                "application/json;q=0.9"
            ),
            "User-Agent": (
                settings.user_agent
            ),
        }

        self._client: (
            httpx.AsyncClient | None
        ) = None

    async def __aenter__(
        self,
    ) -> "EdoArchiveClient":
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(
                self
                ._settings
                .http_timeout_seconds
            ),
            follow_redirects=False,
        )

        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def download_incoming_document(
        self,
        *,
        document_id: str,
    ) -> EdoArchiveResult:
        prepared_document_id = (
            document_id.strip()
        )

        if not prepared_document_id:
            raise ValueError(
                "Идентификатор документа "
                "ЭДО пуст."
            )

        encoded_document_id = quote(
            prepared_document_id,
            safe="",
        )

        url = (
            f"{self._settings.gis_mt_true_api_v3_url}"
            "/elk/incoming-documents/"
            f"{encoded_document_id}/content"
        )

        return await self._request(
            url=url,
            document_id=(
                prepared_document_id
            ),
        )

    async def _request(
        self,
        *,
        url: str,
        document_id: str,
    ) -> EdoArchiveResult:
        if self._client is None:
            raise RuntimeError(
                "EdoArchiveClient должен "
                "использоваться через async with."
            )

        last_error: Exception | None = None

        for attempt in range(
            1,
            (
                self
                ._settings
                .http_max_attempts
                + 1
            ),
        ):
            started_at = (
                time.perf_counter()
            )

            try:
                response = (
                    await self._client.get(
                        url
                    )
                )

                elapsed_ms = round(
                    (
                        time.perf_counter()
                        - started_at
                    )
                    * 1000
                )

                if response.status_code in {
                    401,
                    403,
                }:
                    raise GisMtAuthError(
                        "True API отклонила "
                        "авторизацию: "
                        f"HTTP "
                        f"{response.status_code}."
                    )

                if (
                    response.status_code
                    in self
                    .RETRYABLE_STATUS_CODES
                ):
                    if (
                        attempt
                        == self
                        ._settings
                        .http_max_attempts
                    ):
                        raise GisMtHttpError(
                            response.status_code,
                            self
                            ._safe_error_message(
                                response
                            ),
                        )

                    await asyncio.sleep(
                        self._retry_delay(
                            response=response,
                            attempt=attempt,
                        )
                    )

                    continue

                if response.is_error:
                    raise GisMtHttpError(
                        response.status_code,
                        self._safe_error_message(
                            response
                        ),
                    )

                content = response.content

                if not content:
                    raise GisMtError(
                        "True API вернула пустое "
                        "содержимое документа ЭДО."
                    )

                content_type = (
                    response.headers
                    .get(
                        "Content-Type",
                        "",
                    )
                    .split(
                        ";",
                        1,
                    )[0]
                    .strip()
                    .lower()
                )

                if (
                    content_type
                    == "application/json"
                ):
                    raise GisMtError(
                        "True API вернула JSON "
                        "вместо файла: "
                        f"{self._safe_error_message(response)}"
                    )

                endpoint = str(
                    response
                    .request
                    .url
                    .copy_with(
                        query=None
                    )
                )

                return EdoArchiveResult(
                    document_id=(
                        document_id
                    ),
                    endpoint=endpoint,
                    status_code=(
                        response.status_code
                    ),
                    elapsed_ms=elapsed_ms,
                    content_type=content_type,
                    content_disposition=(
                        response.headers.get(
                            "Content-Disposition"
                        )
                    ),
                    content=content,
                )

            except (
                GisMtAuthError,
                GisMtHttpError,
                GisMtError,
            ):
                raise

            except (
                httpx.TimeoutException,
                httpx.NetworkError,
            ) as exc:
                last_error = exc

                if (
                    attempt
                    == self
                    ._settings
                    .http_max_attempts
                ):
                    break

                await asyncio.sleep(
                    min(
                        30.0,
                        (
                            2
                            ** (
                                attempt
                                - 1
                            )
                        )
                        + random.random(),
                    )
                )

        error_name = (
            type(
                last_error
            ).__name__
            if last_error is not None
            else "unknown error"
        )

        raise GisMtError(
            "Не удалось получить архив "
            "документа ЭДО после "
            "повторных попыток: "
            f"{error_name}."
        )

    @staticmethod
    def _safe_error_message(
        response: httpx.Response,
    ) -> str:
        content_type = (
            response.headers
            .get(
                "Content-Type",
                "",
            )
            .lower()
        )

        if not any(
            marker in content_type
            for marker in (
                "json",
                "text",
                "xml",
            )
        ):
            return (
                f"HTTP "
                f"{response.status_code}; "
                f"Content-Type="
                f"{content_type or 'unknown'}; "
                f"bytes="
                f"{len(response.content)}"
            )

        text = response.text.strip()

        if len(text) > 1000:
            text = (
                text[:1000]
                + "…"
            )

        return (
            f"HTTP "
            f"{response.status_code}: "
            f"{text or response.reason_phrase}"
        )

    @staticmethod
    def _retry_delay(
        *,
        response: httpx.Response,
        attempt: int,
    ) -> float:
        retry_after = (
            response.headers.get(
                "Retry-After"
            )
        )

        if retry_after:
            try:
                return max(
                    0.0,
                    float(
                        retry_after
                    ),
                )

            except ValueError:
                try:
                    retry_at = (
                        parsedate_to_datetime(
                            retry_after
                        )
                    )

                    return max(
                        0.0,
                        (
                            retry_at.timestamp()
                            - time.time()
                        ),
                    )

                except (
                    TypeError,
                    ValueError,
                    OverflowError,
                ):
                    pass

        return min(
            60.0,
            (
                2
                ** (
                    attempt
                    - 1
                )
            )
            + random.random(),
        )