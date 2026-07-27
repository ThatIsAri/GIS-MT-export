import asyncio
import json
import random
import time
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings
from app.models import ApiResult


class GisMtError(RuntimeError):
    """Базовая ошибка клиента ГИС МТ."""


class GisMtAuthError(GisMtError):
    """Токен отсутствует, истёк либо отклонён ГИС МТ."""


class GisMtHttpError(GisMtError):
    """ГИС МТ вернула HTTP-ошибку."""

    def __init__(
        self,
        status_code: int,
        message: str,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


class GisMtClient:
    RETRYABLE_STATUS_CODES = {
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
        token = token.strip()

        if not token:
            raise ValueError(
                "Токен ГИС МТ пуст."
            )

        self._settings = settings

        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": settings.user_agent,
        }

        self._client: httpx.AsyncClient | None = None

    async def __aenter__(
        self,
    ) -> "GisMtClient":
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(
                self._settings.http_timeout_seconds
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

    async def list_documents(
        self,
        *,
        product_group: str,
        date_from: str | None,
        date_to: str | None,
        limit: int | None,
        extra_params: dict[str, str] | None = None,
    ) -> ApiResult:
        if bool(date_from) != bool(date_to):
            raise ValueError(
                "dateFrom и dateTo должны "
                "передаваться вместе."
            )

        params: dict[str, Any] = {
            "pg": product_group,
        }

        if date_from and date_to:
            params["dateFrom"] = date_from
            params["dateTo"] = date_to

        if limit is not None:
            params["limit"] = limit

        if extra_params:
            params.update(
                extra_params
            )

        return await self._request(
            method="GET",
            url=(
                f"{self._settings.gis_mt_true_api_v4_url}"
                "/doc/list"
            ),
            params=params,
        )

    async def get_document(
        self,
        *,
        doc_id: str,
    ) -> ApiResult:
        doc_id = doc_id.strip()

        if not doc_id:
            raise ValueError(
                "doc_id пуст."
            )

        encoded_doc_id = quote(
            doc_id,
            safe="",
        )

        return await self._request(
            method="GET",
            url=(
                f"{self._settings.gis_mt_true_api_v4_url}"
                f"/doc/{encoded_doc_id}/info"
            ),
        )

    async def get_participants(
        self,
        *,
        inns: list[str],
    ) -> ApiResult:
        """
        Возвращает сведения об участниках
        оборота товаров по ИНН.

        При авторизации токеном участника
        True API возвращает расширенную
        карточку для совпадающего ИНН.
        """

        clean_inns: list[str] = []
        seen_inns: set[str] = set()

        for inn in inns:
            prepared_inn = inn.strip()

            if not prepared_inn:
                continue

            if (
                not prepared_inn.isdigit()
                or len(
                    prepared_inn
                )
                not in {
                    10,
                    12,
                }
            ):
                raise ValueError(
                    "ИНН участника должен "
                    "содержать 10 или 12 цифр."
                )

            if prepared_inn in seen_inns:
                continue

            clean_inns.append(
                prepared_inn
            )

            seen_inns.add(
                prepared_inn
            )

        if not clean_inns:
            raise ValueError(
                "Не передан ни один "
                "ИНН участника."
            )

        if len(clean_inns) > 100:
            raise ValueError(
                "За один запрос можно "
                "проверить не более 100 ИНН."
            )

        return await self._request(
            method="GET",
            url=(
                f"{self._settings.gis_mt_true_api_v3_url}"
                "/participants"
            ),
            params={
                "inns": clean_inns,
            },
        )

    async def get_aggregate(
        self,
        *,
        product_group: str,
        codes: list[str],
    ) -> ApiResult:
        clean_codes = [
            code.strip()
            for code in codes
            if code.strip()
        ]

        if not clean_codes:
            raise ValueError(
                "Не передан ни один "
                "код агрегации."
            )

        return await self._request(
            method="POST",
            url=(
                f"{self._settings.gis_mt_true_api_v3_url}"
                "/cises/aggregated/list"
            ),
            params={
                "pg": product_group,
            },
            json_body=clean_codes,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> ApiResult:
        if self._client is None:
            raise RuntimeError(
                "GisMtClient должен "
                "использоваться через async with."
            )

        last_error: Exception | None = None

        for attempt in range(
            1,
            self._settings.http_max_attempts + 1,
        ):
            started_at = time.perf_counter()

            try:
                response = await self._client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_body,
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
                        "ГИС МТ отклонила "
                        "авторизацию: "
                        f"HTTP {response.status_code}."
                    )

                if (
                    response.status_code
                    in self.RETRYABLE_STATUS_CODES
                ):
                    if (
                        attempt
                        == self._settings.http_max_attempts
                    ):
                        raise GisMtHttpError(
                            response.status_code,
                            self._safe_error_message(
                                response
                            ),
                        )

                    delay = self._retry_delay(
                        response=response,
                        attempt=attempt,
                    )

                    await asyncio.sleep(
                        delay
                    )

                    continue

                if response.is_error:
                    raise GisMtHttpError(
                        response.status_code,
                        self._safe_error_message(
                            response
                        ),
                    )

                response_text = response.text

                try:
                    payload: Any = response.json()

                except json.JSONDecodeError:
                    payload = {
                        "raw_text": response_text,
                    }

                endpoint = str(
                    response.request.url.copy_with(
                        query=None
                    )
                )

                return ApiResult(
                    method=method,
                    endpoint=endpoint,
                    params=params or {},
                    status_code=response.status_code,
                    elapsed_ms=elapsed_ms,
                    payload=payload,
                    response_text=response_text,
                )

            except GisMtAuthError:
                raise

            except GisMtHttpError:
                raise

            except (
                httpx.TimeoutException,
                httpx.NetworkError,
            ) as exc:
                last_error = exc

                if (
                    attempt
                    == self._settings.http_max_attempts
                ):
                    break

                delay = min(
                    30.0,
                    (
                        2 ** (
                            attempt - 1
                        )
                    )
                    + random.random(),
                )

                await asyncio.sleep(
                    delay
                )

        error_name = (
            type(
                last_error
            ).__name__
            if last_error
            else "unknown error"
        )

        raise GisMtError(
            "Не удалось выполнить запрос "
            "к ГИС МТ после повторных попыток: "
            f"{error_name}."
        )

    @staticmethod
    def _safe_error_message(
        response: httpx.Response,
    ) -> str:
        text = response.text.strip()

        if len(text) > 1000:
            text = (
                text[:1000]
                + "…"
            )

        return (
            f"HTTP {response.status_code}: "
            f"{text or response.reason_phrase}"
        )

    @staticmethod
    def _retry_delay(
        *,
        response: httpx.Response,
        attempt: int,
    ) -> float:
        retry_after = response.headers.get(
            "Retry-After"
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
                2 ** (
                    attempt - 1
                )
            )
            + random.random(),
        )