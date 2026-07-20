import asyncio
import hashlib
import json
import random
import re
import sys
import xml.etree.ElementTree as standard_element_tree
from collections import Counter
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from urllib.parse import quote

import httpx
import typer
from defusedxml.ElementTree import fromstring
from defusedxml.common import DefusedXmlException

from app.config import get_settings
from app.db import Database
from app.import_edo_xml import import_xml_file


DEFAULT_BFF_BASE_URL = (
    "https://softdrinks.crpt.ru/"
    "bff-elk-g/edo-api/api/v1"
)

DEFAULT_PORTAL_BASE_URL = (
    "https://softdrinks.crpt.ru"
)

DEFAULT_SOURCE_APP = "@crpt/lightindustry"

DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)

DEFAULT_ACCEPT_LANGUAGE = (
    "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
)

MAX_XML_SIZE_BYTES = 50 * 1024 * 1024

RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}

INVALID_FILENAME_CHARACTERS = re.compile(
    r'[<>:"/\\|?*\x00-\x1f]'
)

UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$"
)

XML_DECLARATION_ENCODING_PATTERN = re.compile(
    br"""<\?xml[^>]+encoding\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)

XML_TEXT_DECLARATION_PATTERN = re.compile(
    r"^\ufeff?\s*<\?xml\b[^?]*\?>",
    re.IGNORECASE,
)

FORBIDDEN_XML10_CONTROL_CODES = frozenset(
    [
        *range(0x00, 0x09),
        0x0B,
        0x0C,
        *range(0x0E, 0x20),
    ]
)

PRIVATE_USE_CONTROL_BASE = 0xE000


@dataclass(frozen=True, slots=True)
class BrowserCredentials:
    token: str
    cookie: str | None


@dataclass(frozen=True, slots=True)
class XmlValidationResult:
    well_formed: bool
    recoverable: bool
    detected_encoding: str | None
    parse_error: str | None
    forbidden_control_counts: tuple[
        tuple[int, int],
        ...,
    ]


@dataclass(frozen=True, slots=True)
class DownloadResult:
    content: bytes
    file_name: str
    content_type: str
    validation: XmlValidationResult


def read_browser_credentials_from_stdin(
) -> BrowserCredentials:
    """
    Читает браузерную авторизацию через stdin.

    Поддерживаются:
    - чистое значение Authorization;
    - значение с префиксом Bearer;
    - JSON с полями token и cookie.
    """

    if sys.stdin.isatty():
        raise typer.BadParameter(
            "Авторизация должна поступить через stdin."
        )

    raw_value = sys.stdin.read().strip()

    if not raw_value:
        raise typer.BadParameter(
            "stdin пуст: авторизация не получена."
        )

    token: str
    cookie: str | None = None

    if raw_value.startswith("{"):
        try:
            payload = json.loads(raw_value)

        except json.JSONDecodeError as exc:
            raise typer.BadParameter(
                "Через stdin передан некорректный JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise typer.BadParameter(
                "Данные авторизации должны быть JSON-объектом."
            )

        raw_token = payload.get("token")
        raw_cookie = payload.get("cookie")

        if not isinstance(raw_token, str):
            raise typer.BadParameter(
                "В JSON отсутствует строковое поле token."
            )

        token = raw_token.strip()

        if raw_cookie is not None:
            if not isinstance(raw_cookie, str):
                raise typer.BadParameter(
                    "Поле cookie должно быть строкой."
                )

            prepared_cookie = raw_cookie.strip()

            if prepared_cookie:
                cookie = prepared_cookie

    else:
        token = raw_value.strip()

    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    if not token:
        raise typer.BadParameter(
            "Authorization-токен пуст."
        )

    if any(
        character.isspace()
        for character in token
    ):
        raise typer.BadParameter(
            "Authorization-токен содержит "
            "пробельные символы."
        )

    if len(token) > 65536:
        raise typer.BadParameter(
            "Authorization-токен имеет "
            "недопустимую длину."
        )

    if cookie is not None:
        if "\r" in cookie or "\n" in cookie:
            raise typer.BadParameter(
                "Cookie содержит переносы строк."
            )

        if len(cookie) > 131072:
            raise typer.BadParameter(
                "Cookie имеет недопустимую длину."
            )

    return BrowserCredentials(
        token=token,
        cookie=cookie,
    )


def sanitize_file_name(
    value: str,
    fallback: str,
) -> str:
    """
    Формирует безопасное имя XML-файла.
    """

    prepared_value = INVALID_FILENAME_CHARACTERS.sub(
        "_",
        value,
    )

    prepared_value = (
        prepared_value
        .strip()
        .strip(".")
    )

    if not prepared_value:
        prepared_value = fallback

    if not prepared_value.lower().endswith(".xml"):
        prepared_value = (
            f"{prepared_value}.xml"
        )

    if len(prepared_value) > 220:
        prepared_value = (
            prepared_value[:216]
            + ".xml"
        )

    return prepared_value


def extract_file_name(
    response: httpx.Response,
    document_id: str,
) -> str:
    """
    Извлекает имя файла из Content-Disposition.
    """

    content_disposition = (
        response.headers.get(
            "Content-Disposition",
            "",
        )
    )

    file_name: str | None = None

    if content_disposition:
        message = Message()

        message[
            "content-disposition"
        ] = content_disposition

        parsed_file_name = (
            message.get_filename()
        )

        if isinstance(
            parsed_file_name,
            str,
        ):
            file_name = (
                parsed_file_name.strip()
            )

    fallback = (
        f"incoming_{document_id}.xml"
    )

    return sanitize_file_name(
        file_name or fallback,
        fallback,
    )


def extract_charset(
    content_type: str,
) -> str | None:
    """
    Извлекает charset из Content-Type.
    """

    if not content_type:
        return None

    message = Message()

    message["content-type"] = content_type

    charset = (
        message.get_content_charset()
    )

    if isinstance(charset, str):
        prepared_charset = (
            charset.strip()
        )

        if prepared_charset:
            return prepared_charset

    return None


def content_looks_like_html(
    content: bytes,
    content_type: str,
) -> bool:
    """
    Определяет, является ли ответ HTML.
    """

    if "html" in content_type.lower():
        return True

    sample = (
        content[:4096]
        .lstrip()
        .lower()
    )

    if sample.startswith(
        b"\xef\xbb\xbf"
    ):
        sample = (
            sample[3:]
            .lstrip()
        )

    html_markers = (
        b"<!doctype html",
        b"<html",
        b"<head",
        b"<body",
    )

    return any(
        sample.startswith(marker)
        for marker in html_markers
    )


def content_looks_like_xml(
    content: bytes,
    content_type: str,
) -> bool:
    """
    Выполняет предварительную проверку XML.
    """

    lowered_content_type = (
        content_type.lower()
    )

    if (
        "application/xml"
        in lowered_content_type
        or "text/xml"
        in lowered_content_type
        or "+xml"
        in lowered_content_type
    ):
        return True

    sample = (
        content[:4096]
        .lstrip()
    )

    if sample.startswith(
        b"\xef\xbb\xbf"
    ):
        sample = (
            sample[3:]
            .lstrip()
        )

    if content_looks_like_html(
        content,
        content_type,
    ):
        return False

    return (
        sample.startswith(b"<?xml")
        or sample.startswith(b"<")
    )


def detect_xml_encoding(
    content: bytes,
    encoding_hint: str | None,
) -> str | None:
    """
    Определяет кодировку XML.
    """

    bom_encodings = (
        (
            b"\xef\xbb\xbf",
            "utf-8-sig",
        ),
        (
            b"\xff\xfe\x00\x00",
            "utf-32-le",
        ),
        (
            b"\x00\x00\xfe\xff",
            "utf-32-be",
        ),
        (
            b"\xff\xfe",
            "utf-16-le",
        ),
        (
            b"\xfe\xff",
            "utf-16-be",
        ),
    )

    for prefix, encoding in bom_encodings:
        if content.startswith(prefix):
            return encoding

    match = (
        XML_DECLARATION_ENCODING_PATTERN
        .search(
            content[:1024]
        )
    )

    if match is not None:
        try:
            return (
                match
                .group(1)
                .decode(
                    "ascii",
                    errors="strict",
                )
            )

        except UnicodeDecodeError:
            pass

    if (
        encoding_hint is not None
        and encoding_hint.strip()
    ):
        return encoding_hint.strip()

    return None


def decode_xml_content(
    content: bytes,
    detected_encoding: str | None,
) -> tuple[
    str | None,
    str | None,
    str | None,
]:
    """
    Декодирует XML для восстановительной проверки.
    """

    candidates: list[str] = []

    for candidate in (
        detected_encoding,
        "utf-8-sig",
        "utf-8",
        "windows-1251",
    ):
        if not candidate:
            continue

        existing_candidates = {
            item.lower()
            for item in candidates
        }

        if (
            candidate.lower()
            not in existing_candidates
        ):
            candidates.append(candidate)

    errors: list[str] = []

    for candidate in candidates:
        try:
            return (
                content.decode(
                    candidate,
                    errors="strict",
                ),
                candidate,
                None,
            )

        except (
            LookupError,
            UnicodeDecodeError,
        ) as exc:
            errors.append(
                f"{candidate}: "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

    return (
        None,
        None,
        (
            "; ".join(errors)[:2000]
            or (
                "Не удалось определить "
                "кодировку XML."
            )
        ),
    )


def replace_forbidden_controls(
    text: str,
) -> tuple[
    str,
    tuple[tuple[int, int], ...],
]:
    """
    Обратимо заменяет запрещённые XML 1.0
    управляющие символы в рабочей копии.
    """

    counts: Counter[int] = Counter()
    result: list[str] = []

    for character in text:
        character_code = ord(character)

        if (
            character_code
            in FORBIDDEN_XML10_CONTROL_CODES
        ):
            counts[character_code] += 1

            result.append(
                chr(
                    PRIVATE_USE_CONTROL_BASE
                    + character_code
                )
            )

        else:
            result.append(character)

    return (
        "".join(result),
        tuple(
            sorted(
                counts.items()
            )
        ),
    )


def format_control_counts(
    counts: tuple[
        tuple[int, int],
        ...,
    ],
) -> str:
    """
    Формирует безопасную статистику
    управляющих символов.
    """

    return (
        ", ".join(
            f"0x{code:02X}={count}"
            for code, count in counts
        )
        or "нет"
    )


def validate_downloaded_xml(
    content: bytes,
    encoding_hint: str | None,
) -> XmlValidationResult:
    """
    Проверяет XML без изменения исходных байтов.
    """

    detected_encoding = (
        detect_xml_encoding(
            content,
            encoding_hint,
        )
    )

    try:
        fromstring(content)

    except (
        standard_element_tree.ParseError,
        DefusedXmlException,
        ValueError,
    ) as strict_exception:
        strict_error = str(
            strict_exception
        )[:2000]

    else:
        return XmlValidationResult(
            well_formed=True,
            recoverable=False,
            detected_encoding=(
                detected_encoding
            ),
            parse_error=None,
            forbidden_control_counts=(
                tuple()
            ),
        )

    (
        decoded_text,
        actual_encoding,
        decode_error,
    ) = decode_xml_content(
        content,
        detected_encoding,
    )

    if decoded_text is None:
        return XmlValidationResult(
            well_formed=False,
            recoverable=False,
            detected_encoding=(
                detected_encoding
            ),
            parse_error=(
                (
                    "Строгая проверка: "
                    f"{strict_error}. "
                    "Декодирование: "
                    f"{decode_error}."
                )[:4000]
            ),
            forbidden_control_counts=(
                tuple()
            ),
        )

    (
        prepared_text,
        control_counts,
    ) = replace_forbidden_controls(
        decoded_text
    )

    if not control_counts:
        return XmlValidationResult(
            well_formed=False,
            recoverable=False,
            detected_encoding=(
                actual_encoding
                or detected_encoding
            ),
            parse_error=(
                (
                    "Строгая проверка: "
                    f"{strict_error}. "
                    "Запрещённые управляющие "
                    "символы XML 1.0 "
                    "не обнаружены."
                )[:4000]
            ),
            forbidden_control_counts=(
                tuple()
            ),
        )

    prepared_text = (
        XML_TEXT_DECLARATION_PATTERN
        .sub(
            "",
            prepared_text,
            count=1,
        )
    )

    prepared_content = (
        prepared_text.encode(
            "utf-8",
            errors="strict",
        )
    )

    try:
        fromstring(
            prepared_content
        )

    except (
        standard_element_tree.ParseError,
        DefusedXmlException,
        ValueError,
    ) as recovery_exception:
        return XmlValidationResult(
            well_formed=False,
            recoverable=False,
            detected_encoding=(
                actual_encoding
                or detected_encoding
            ),
            parse_error=(
                (
                    "Строгая проверка: "
                    f"{strict_error}. "
                    "Управляющие символы: "
                    f"{format_control_counts(control_counts)}. "
                    "Восстановительная проверка: "
                    f"{str(recovery_exception)[:1500]}."
                )[:4000]
            ),
            forbidden_control_counts=(
                control_counts
            ),
        )

    return XmlValidationResult(
        well_formed=False,
        recoverable=True,
        detected_encoding=(
            actual_encoding
            or detected_encoding
        ),
        parse_error=(
            (
                "Строгая проверка: "
                f"{strict_error}. "
                "Обнаружены управляющие символы: "
                f"{format_control_counts(control_counts)}. "
                "Рабочая копия успешно прошла проверку."
            )[:4000]
        ),
        forbidden_control_counts=(
            control_counts
        ),
    )


def safe_http_error(
    response: httpx.Response,
) -> str:
    """
    Формирует описание HTTP-ошибки без вывода
    токена, Cookie и содержимого документа.
    """

    content_type = (
        response.headers.get(
            "Content-Type",
            "",
        )
    )

    message = response.reason_phrase

    if "json" in content_type.lower():
        try:
            payload = response.json()

        except ValueError:
            payload = None

        if isinstance(payload, dict):
            for key in (
                "message",
                "error",
                "error_description",
                "code",
            ):
                value = payload.get(key)

                if (
                    isinstance(value, str)
                    and value.strip()
                ):
                    message = (
                        value.strip()
                    )
                    break

    return (
        f"HTTP {response.status_code}: "
        f"{message}. "
        "Content-Type: "
        f"{content_type or 'не указан'}."
    )


def retry_delay(
    attempt: int,
) -> float:
    """
    Рассчитывает задержку перед повтором.
    """

    return min(
        30.0,
        (
            2 ** (attempt - 1)
        )
        + random.random(),
    )


async def download_incoming_xml(
    *,
    document_id: str,
    credentials: BrowserCredentials,
    bff_base_url: str,
    portal_base_url: str,
    source_app: str,
    browser_user_agent: str,
    accept_language: str,
) -> DownloadResult:
    """
    Загружает XML входящего УПД через BFF ЛК.

    Заголовки воспроизводят успешно проверенный
    браузерный запрос.
    """

    settings = get_settings()

    encoded_document_id = quote(
        document_id,
        safe="",
    )

    request_url = (
        f"{bff_base_url.rstrip('/')}"
        f"/incoming-documents/"
        f"{encoded_document_id}"
        f"/content"
    )

    referer_url = (
        f"{portal_base_url.rstrip('/')}"
        f"/documents/incoming/upd970/"
        f"{encoded_document_id}"
    )

    headers = {
        "Authorization": (
            f"Bearer {credentials.token}"
        ),
        "Cookie": (
            credentials.cookie or ""
        ),
        "Accept": (
            "application/json, "
            "text/plain, "
            "*/*"
        ),
        "Accept-Language": (
            accept_language
        ),
        "Referer": referer_url,
        "X-Source-App": source_app,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": browser_user_agent,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    if not credentials.cookie:
        headers.pop(
            "Cookie",
            None,
        )

    timeout = httpx.Timeout(
        settings.http_timeout_seconds
    )

    async with httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        follow_redirects=False,
    ) as client:
        for attempt in range(
            1,
            settings.http_max_attempts + 1,
        ):
            try:
                response = await client.get(
                    request_url
                )

            except (
                httpx.TimeoutException,
                httpx.NetworkError,
            ) as exc:
                if (
                    attempt
                    == settings.http_max_attempts
                ):
                    raise RuntimeError(
                        "Не удалось получить XML "
                        "после повторных попыток: "
                        f"{type(exc).__name__}."
                    ) from exc

                await asyncio.sleep(
                    retry_delay(attempt)
                )

                continue

            if response.status_code in {
                401,
                403,
            }:
                raise RuntimeError(
                    "ЛК Честного ЗНАКа отклонил "
                    "браузерную авторизацию: "
                    f"HTTP {response.status_code}."
                )

            if response.status_code == 404:
                raise RuntimeError(
                    "Входящий документ не найден: "
                    "HTTP 404. Проверьте UUID "
                    "из адреса запроса BFF."
                )

            if (
                response.status_code
                in RETRYABLE_STATUS_CODES
            ):
                if (
                    attempt
                    == settings.http_max_attempts
                ):
                    raise RuntimeError(
                        safe_http_error(
                            response
                        )
                    )

                await asyncio.sleep(
                    retry_delay(attempt)
                )

                continue

            if response.is_redirect:
                location = (
                    response.headers.get(
                        "Location",
                        "не указан",
                    )
                )

                raise RuntimeError(
                    "ЛК вернул перенаправление: "
                    f"HTTP {response.status_code}. "
                    f"Location: {location}."
                )

            if response.is_error:
                raise RuntimeError(
                    safe_http_error(
                        response
                    )
                )

            content = response.content

            if not content:
                raise RuntimeError(
                    "ЛК вернул пустой ответ."
                )

            if (
                len(content)
                > MAX_XML_SIZE_BYTES
            ):
                raise RuntimeError(
                    "Размер ответа превышает предел "
                    f"{MAX_XML_SIZE_BYTES} байт."
                )

            content_type = (
                response.headers.get(
                    "Content-Type",
                    "",
                )
            )

            if content_looks_like_html(
                content,
                content_type,
            ):
                raise RuntimeError(
                    "Сервер вернул HTML вместо XML. "
                    "Проверьте актуальность браузерного "
                    "токена и Cookie. "
                    f"Content-Type: "
                    f"{content_type or 'не указан'}, "
                    f"размер: {len(content)} байт."
                )

            if not content_looks_like_xml(
                content,
                content_type,
            ):
                raise RuntimeError(
                    "Ответ не похож на XML. "
                    f"Content-Type: "
                    f"{content_type or 'не указан'}, "
                    f"размер: {len(content)} байт."
                )

            validation = (
                validate_downloaded_xml(
                    content,
                    extract_charset(
                        content_type
                    ),
                )
            )

            if (
                not validation.well_formed
                and not validation.recoverable
            ):
                raise RuntimeError(
                    "Ответ похож на XML, но не прошёл "
                    "безопасную проверку: "
                    f"{validation.parse_error}"
                )

            return DownloadResult(
                content=content,
                file_name=extract_file_name(
                    response,
                    document_id,
                ),
                content_type=content_type,
                validation=validation,
            )

    raise RuntimeError(
        "Не удалось получить XML."
    )


def save_xml(
    *,
    output_root: Path,
    document_id: str,
    file_name: str,
    content: bytes,
) -> tuple[Path, str]:
    """
    Сохраняет исходный XML без изменений.
    """

    content_sha256 = hashlib.sha256(
        content
    ).hexdigest()

    document_directory = (
        output_root
        / "incoming"
        / document_id
    )

    document_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        document_directory
        / file_name
    )

    if output_path.exists():
        existing_sha256 = hashlib.sha256(
            output_path.read_bytes()
        ).hexdigest()

        if (
            existing_sha256
            == content_sha256
        ):
            return (
                output_path,
                content_sha256,
            )

        output_path = (
            output_path.with_name(
                f"{output_path.stem}_"
                f"{content_sha256[:12]}"
                f"{output_path.suffix}"
            )
        )

    temporary_path = (
        output_path.with_suffix(
            output_path.suffix
            + ".part"
        )
    )

    temporary_path.write_bytes(
        content
    )

    temporary_path.replace(
        output_path
    )

    return (
        output_path,
        content_sha256,
    )


def update_raw_document_metadata(
    *,
    database: Database,
    raw_document_id: int,
    bff_document_id: str,
    validation: XmlValidationResult,
) -> None:
    """
    Сохраняет BFF UUID и результат проверки XML.

    Связь с core_document будет определяться
    позднее по ИдФайл из содержимого УПД.
    """

    parse_status = (
        "RAW"
        if validation.well_formed
        else "RAW_RECOVERABLE"
    )

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE raw_edo_document
                   SET source_message_id = %s,
                       detected_encoding = COALESCE(
                           %s,
                           detected_encoding
                       ),
                       xml_well_formed = %s,
                       parse_status = %s,
                       parse_error = %s,
                       external_document_id = NULL,
                       core_document_id = NULL
                 WHERE id = %s
                """,
                (
                    bff_document_id,
                    validation.detected_encoding,
                    (
                        1
                        if validation.well_formed
                        else 0
                    ),
                    parse_status,
                    validation.parse_error,
                    raw_document_id,
                ),
            )

        finally:
            cursor.close()


def print_validation_result(
    validation: XmlValidationResult,
) -> None:
    """
    Выводит результат проверки XML.
    """

    if validation.well_formed:
        typer.echo(
            "Строгая проверка XML: успешно."
        )
        return

    typer.echo(
        "Предупреждение: XML содержит "
        "управляющие символы XML 1.0.",
        err=True,
    )

    typer.echo(
        "Обнаруженные символы: "
        f"{format_control_counts(validation.forbidden_control_counts)}.",
        err=True,
    )

    typer.echo(
        "Исходные байты сохранены без изменений.",
        err=True,
    )


def main(
    document_id: str = typer.Option(
        ...,
        "--document-id",
        help=(
            "UUID документа из адреса BFF: "
            "/incoming-documents/{UUID}/content."
        ),
    ),

    output_root: Path = typer.Option(
        Path("/data/edo_inbox"),
        "--output-root",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Корневой каталог хранения XML.",
    ),

    bff_base_url: str = typer.Option(
        DEFAULT_BFF_BASE_URL,
        "--bff-base-url",
    ),

    portal_base_url: str = typer.Option(
        DEFAULT_PORTAL_BASE_URL,
        "--portal-base-url",
    ),

    source_app: str = typer.Option(
        DEFAULT_SOURCE_APP,
        "--source-app",
    ),

    browser_user_agent: str = typer.Option(
        DEFAULT_BROWSER_USER_AGENT,
        "--browser-user-agent",
    ),

    accept_language: str = typer.Option(
        DEFAULT_ACCEPT_LANGUAGE,
        "--accept-language",
    ),

    import_to_raw: bool = typer.Option(
        True,
        "--import-to-raw/--no-import-to-raw",
    ),
) -> None:
    """
    Загружает XML входящего УПД через BFF ЛК.
    """

    prepared_document_id = (
        document_id.strip()
    )

    if not UUID_PATTERN.fullmatch(
        prepared_document_id
    ):
        raise typer.BadParameter(
            "document-id должен быть UUID "
            "из браузерного Request URL."
        )

    prepared_bff_base_url = (
        bff_base_url.strip()
    )

    prepared_portal_base_url = (
        portal_base_url.strip()
    )

    prepared_source_app = (
        source_app.strip()
    )

    prepared_browser_user_agent = (
        browser_user_agent.strip()
    )

    prepared_accept_language = (
        accept_language.strip()
    )

    if (
        not prepared_bff_base_url.startswith(
            "https://"
        )
        or not prepared_portal_base_url.startswith(
            "https://"
        )
    ):
        raise typer.BadParameter(
            "Адреса BFF и портала "
            "должны использовать HTTPS."
        )

    if not prepared_source_app:
        raise typer.BadParameter(
            "source-app не может быть пустым."
        )

    if not prepared_browser_user_agent:
        raise typer.BadParameter(
            "browser-user-agent не может быть пустым."
        )

    if not prepared_accept_language:
        raise typer.BadParameter(
            "accept-language не может быть пустым."
        )

    credentials = (
        read_browser_credentials_from_stdin()
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        download_result = asyncio.run(
            download_incoming_xml(
                document_id=prepared_document_id,
                credentials=credentials,
                bff_base_url=prepared_bff_base_url,
                portal_base_url=prepared_portal_base_url,
                source_app=prepared_source_app,
                browser_user_agent=(
                    prepared_browser_user_agent
                ),
                accept_language=(
                    prepared_accept_language
                ),
            )
        )

        (
            output_path,
            content_sha256,
        ) = save_xml(
            output_root=output_root,
            document_id=prepared_document_id,
            file_name=(
                download_result.file_name
            ),
            content=(
                download_result.content
            ),
        )

    except RuntimeError as exc:
        typer.echo(
            f"Ошибка: {exc}",
            err=True,
        )

        raise typer.Exit(
            code=2
        ) from exc

    typer.echo(
        "XML успешно получен и сохранён."
    )

    typer.echo(
        f"Файл: {output_path}"
    )

    typer.echo(
        f"Размер: {len(download_result.content)} байт"
    )

    typer.echo(
        "Content-Type: "
        f"{download_result.content_type}"
    )

    typer.echo(
        "Кодировка: "
        f"{download_result.validation.detected_encoding or 'не определена'}"
    )

    typer.echo(
        f"SHA-256: {content_sha256}"
    )

    print_validation_result(
        download_result.validation
    )

    if not import_to_raw:
        return

    settings = get_settings()
    database = Database(settings)

    try:
        import_result = import_xml_file(
            database=database,
            root=output_root,
            file_path=output_path,
            source_system=(
                "GIS_MT_EDO_LIGHT_BFF"
            ),
            max_file_size_bytes=(
                MAX_XML_SIZE_BYTES
            ),
        )

        update_raw_document_metadata(
            database=database,
            raw_document_id=(
                import_result.raw_document_id
            ),
            bff_document_id=(
                prepared_document_id
            ),
            validation=(
                download_result.validation
            ),
        )

    except Exception as exc:
        typer.echo(
            "XML сохранён, но импорт в MySQL "
            "завершился ошибкой: "
            f"{type(exc).__name__}: {exc}",
            err=True,
        )

        raise typer.Exit(
            code=3
        ) from exc

    typer.echo(
        f"RAW-документ: "
        f"{import_result.raw_document_id}"
    )

    typer.echo(
        "Результат импорта: "
        + (
            "создан"
            if import_result.created
            else "найден ранее"
        )
    )

    typer.echo(
        "Связь с core_document: "
        "будет определена по ИдФайл."
    )


if __name__ == "__main__":
    typer.run(main)