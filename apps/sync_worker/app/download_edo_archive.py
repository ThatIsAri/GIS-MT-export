from __future__ import annotations

import asyncio
import hashlib
import io
import re
import stat
import zipfile
from pathlib import Path
from typing import Any

import typer
from defusedxml.ElementTree import (
    fromstring,
)

from app.cli import (
    read_token_from_stdin,
)
from app.config import (
    get_settings,
)
from app.db import Database
from app.edo_archive_client import (
    EdoArchiveClient,
)
from app.import_edo_xml import (
    import_xml_file,
)
from app.process_edo import (
    print_result,
    process_imported_document,
)


MAX_ARCHIVE_BYTES = (
    200
    * 1024
    * 1024
)

MAX_ARCHIVE_ENTRIES = 500

MAX_ENTRY_BYTES = (
    50
    * 1024
    * 1024
)

MAX_EXTRACTED_BYTES = (
    200
    * 1024
    * 1024
)

UUID_TEXT_PATTERN = (
    r"[0-9a-f]{8}-"
    r"[0-9a-f]{4}-"
    r"[0-9a-f]{4}-"
    r"[0-9a-f]{4}-"
    r"[0-9a-f]{12}"
)

UUID_FULL_PATTERN = re.compile(
    rf"^{UUID_TEXT_PATTERN}$",
    re.IGNORECASE,
)

UUID_SEARCH_PATTERN = re.compile(
    UUID_TEXT_PATTERN,
    re.IGNORECASE,
)


def local_name(
    value: str,
) -> str:
    if "}" in value:
        return value.rsplit(
            "}",
            1,
        )[1]

    if ":" in value:
        return value.rsplit(
            ":",
            1,
        )[1]

    return value


def child(
    element: Any | None,
    name: str,
) -> Any | None:
    if element is None:
        return None

    for candidate in list(
        element
    ):
        if local_name(
            candidate.tag
        ) == name:
            return candidate

    return None


def is_upd_seller_title(
    content: bytes,
) -> bool:
    """
    Проверяет, что XML содержит
    товарную часть титула продавца УПД.
    """

    try:
        root = fromstring(
            content
        )

    except Exception:
        return False

    if local_name(
        root.tag
    ) != "Файл":
        return False

    document = child(
        root,
        "Документ",
    )

    table = child(
        document,
        "ТаблСчФакт",
    )

    if table is None:
        return False

    return any(
        local_name(
            candidate.tag
        ) == "СведТов"
        for candidate in list(
            table
        )
    )


def normalize_document_id(
    value: str,
) -> str:
    """
    Проверяет UUID, переданный пользователем.
    """

    prepared = value.strip()

    if not UUID_FULL_PATTERN.fullmatch(
        prepared
    ):
        raise ValueError(
            "Идентификатор документа ЭДО "
            "должен быть UUID."
        )

    return prepared.lower()

def extract_document_uuid(
    value: str | None,
) -> str | None:
    """
    Извлекает UUID документа ЭДО
    из составного идентификатора.

    Например:

    ON_NSCHFDOPPR_..._
    24c2940e-bba0-4871-8049-e2a2e743fcea_
    0_1_1_0_0_00
    """

    if value is None:
        return None

    prepared = str(
        value
    ).strip()

    if not prepared:
        return None

    match = UUID_SEARCH_PATTERN.search(
        prepared
    )

    if match is None:
        return None

    return match.group(
        0
    ).lower()


def load_edo_document_id(
    database: Database,
    *,
    document_id: str | None,
    core_document_id: int | None,
) -> tuple[
    str,
    int | None,
]:
    """
    Определяет UUID документа ЭДО.

    При передаче core_document_id UUID
    извлекается прежде всего из
    external_document_id.

    related_document_id используется
    только как резервный источник.
    """

    if bool(
        document_id
    ) == bool(
        core_document_id
    ):
        raise ValueError(
            "Передайте ровно один параметр: "
            "--document-id или "
            "--core-document-id."
        )

    if document_id is not None:
        return (
            normalize_document_id(
                document_id
            ),
            None,
        )

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT
                    external_document_id,
                    related_document_id
                FROM core_document
                WHERE id = %s
                LIMIT 1
                """,
                (
                    core_document_id,
                ),
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

    if row is None:
        raise ValueError(
            f"core_document.id="
            f"{core_document_id} "
            "не найден."
        )

    external_document_id = (
        str(
            row[0]
        )
        if row[0] is not None
        else None
    )

    related_document_id = (
        str(
            row[1]
        )
        if row[1] is not None
        else None
    )

    resolved_document_id = (
        extract_document_uuid(
            external_document_id
        )
        or extract_document_uuid(
            related_document_id
        )
    )

    if resolved_document_id is None:
        raise ValueError(
            f"У core_document.id="
            f"{core_document_id} "
            "UUID документа ЭДО не найден "
            "ни в external_document_id, "
            "ни в related_document_id."
        )

    return (
        resolved_document_id,
        core_document_id,
    )


def write_bytes_atomic(
    path: Path,
    content: bytes,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = (
        path.with_suffix(
            path.suffix
            + ".tmp"
        )
    )

    temporary_path.write_bytes(
        content
    )

    temporary_path.replace(
        path
    )


def unique_output_path(
    directory: Path,
    file_name: str,
    content: bytes,
) -> Path:
    safe_name = Path(
        file_name
    ).name

    if not safe_name.lower().endswith(
        ".xml"
    ):
        safe_name += ".xml"

    candidate = (
        directory
        / safe_name
    )

    if not candidate.exists():
        return candidate

    existing = (
        candidate.read_bytes()
    )

    if existing == content:
        return candidate

    digest = (
        hashlib.sha256(
            content
        )
        .hexdigest()[:12]
    )

    return (
        directory
        / (
            f"{candidate.stem}_"
            f"{digest}"
            f"{candidate.suffix}"
        )
    )


def extract_upd_xml_from_zip(
    archive_content: bytes,
    output_directory: Path,
) -> list[Path]:
    """
    Безопасно извлекает только товарные
    XML титула продавца УПД.
    """

    if (
        len(
            archive_content
        )
        > MAX_ARCHIVE_BYTES
    ):
        raise ValueError(
            "Размер архива превышает "
            "допустимый предел."
        )

    extracted_paths: list[
        Path
    ] = []

    total_uncompressed_bytes = 0

    with zipfile.ZipFile(
        io.BytesIO(
            archive_content
        )
    ) as archive:
        entries = archive.infolist()

        if (
            len(
                entries
            )
            > MAX_ARCHIVE_ENTRIES
        ):
            raise ValueError(
                "В архиве слишком "
                "много файлов."
            )

        for entry in entries:
            if entry.is_dir():
                continue

            unix_mode = (
                entry.external_attr
                >> 16
            ) & 0o170000

            if (
                unix_mode
                == stat.S_IFLNK
            ):
                raise ValueError(
                    "В архиве обнаружена "
                    "символическая ссылка."
                )

            if entry.flag_bits & 0x1:
                raise ValueError(
                    "Зашифрованные ZIP-записи "
                    "не поддерживаются."
                )

            if (
                entry.file_size
                > MAX_ENTRY_BYTES
            ):
                raise ValueError(
                    "Размер одного файла "
                    "в архиве превышает "
                    "допустимый предел."
                )

            total_uncompressed_bytes += (
                entry.file_size
            )

            if (
                total_uncompressed_bytes
                > MAX_EXTRACTED_BYTES
            ):
                raise ValueError(
                    "Суммарный размер файлов "
                    "в архиве превышает "
                    "допустимый предел."
                )

            if not entry.filename.lower().endswith(
                ".xml"
            ):
                continue

            content = archive.read(
                entry
            )

            if not is_upd_seller_title(
                content
            ):
                continue

            output_path = (
                unique_output_path(
                    output_directory,
                    Path(
                        entry.filename
                    ).name,
                    content,
                )
            )

            write_bytes_atomic(
                output_path,
                content,
            )

            extracted_paths.append(
                output_path
            )

    return sorted(
        set(
            extracted_paths
        ),
        key=lambda item: (
            item.name.lower()
        ),
    )


def extract_upd_xml(
    content: bytes,
    output_directory: Path,
    document_id: str,
) -> tuple[
    str,
    list[Path],
]:
    """
    Обрабатывает официальный ответ
    как ZIP либо как непосредственный XML.
    """

    if content.startswith(
        (
            b"PK\x03\x04",
            b"PK\x05\x06",
            b"PK\x07\x08",
        )
    ):
        archive_path = (
            output_directory
            / f"{document_id}.zip"
        )

        write_bytes_atomic(
            archive_path,
            content,
        )

        return (
            "ZIP",
            extract_upd_xml_from_zip(
                content,
                output_directory,
            ),
        )

    if is_upd_seller_title(
        content
    ):
        xml_path = (
            output_directory
            / f"{document_id}.xml"
        )

        write_bytes_atomic(
            xml_path,
            content,
        )

        return (
            "XML",
            [
                xml_path,
            ],
        )

    preview = (
        content[:200]
        .lstrip()
        .lower()
    )

    if preview.startswith(
        (
            b"<!doctype html",
            b"<html",
        )
    ):
        raise ValueError(
            "Вместо архива True API "
            "вернула HTML."
        )

    raise ValueError(
        "Ответ не является ZIP-архивом "
        "или товарным XML УПД."
    )


def update_raw_source_message_id(
    database: Database,
    *,
    raw_document_id: int,
    document_id: str,
) -> None:
    """
    Сохраняет идентификатор документа ЭДО.

    Исходный source_system не перезаписывается,
    поскольку такой же XML мог ранее поступить
    ручным способом.
    """

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE raw_edo_document
                   SET source_message_id = COALESCE(
                           source_message_id,
                           %s
                       ),
                       last_seen_at = UTC_TIMESTAMP(3)
                 WHERE id = %s
                """,
                (
                    document_id,
                    raw_document_id,
                ),
            )

        finally:
            cursor.close()


async def download_document(
    *,
    token: str,
    document_id: str,
):
    settings = get_settings()

    async with EdoArchiveClient(
        settings=settings,
        token=token,
    ) as client:
        return (
            await client
            .download_incoming_document(
                document_id=(
                    document_id
                )
            )
        )


def main(
    document_id: str | None = typer.Option(
        None,
        "--document-id",
        help=(
            "Идентификатор документа "
            "в ЭДО. Не используется вместе "
            "с --core-document-id."
        ),
    ),

    core_document_id: int | None = (
        typer.Option(
            None,
            "--core-document-id",
            min=1,
            help=(
                "ID core_document. "
                "Идентификатор ЭДО будет "
                "взят из related_document_id."
            ),
        )
    ),

    output_root: Path = typer.Option(
        Path(
            "/data/edo_inbox/official"
        ),
        "--output-root",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help=(
            "Каталог официально "
            "загруженных документов ЭДО."
        ),
    ),
) -> None:
    """
    Скачивает входящий документ ЭДО
    официальным методом True API,
    извлекает УПД, импортирует, разбирает
    и сопоставляет его с CORE.
    """

    database = Database(
        get_settings()
    )

    try:
        (
            resolved_document_id,
            resolved_core_document_id,
        ) = load_edo_document_id(
            database,
            document_id=document_id,
            core_document_id=(
                core_document_id
            ),
        )

    except ValueError as exc:
        raise typer.BadParameter(
            str(
                exc
            )
        ) from exc

    token = (
        read_token_from_stdin()
    )

    typer.echo(
        "Официальная загрузка "
        "документа ЭДО через True API."
    )

    typer.echo(
        f"document_id: "
        f"{resolved_document_id}"
    )

    if (
        resolved_core_document_id
        is not None
    ):
        typer.echo(
            f"core_document_id: "
            f"{resolved_core_document_id}"
        )

    result = asyncio.run(
        download_document(
            token=token,
            document_id=(
                resolved_document_id
            ),
        )
    )

    typer.echo(
        f"HTTP: "
        f"{result.status_code}; "
        f"Content-Type: "
        f"{result.content_type or '-'}; "
        f"bytes: "
        f"{len(result.content)}; "
        f"elapsed_ms: "
        f"{result.elapsed_ms}"
    )

    document_directory = (
        output_root
        / resolved_document_id
    )

    (
        response_format,
        xml_paths,
    ) = extract_upd_xml(
        content=result.content,
        output_directory=(
            document_directory
        ),
        document_id=(
            resolved_document_id
        ),
    )

    typer.echo(
        f"Формат ответа: "
        f"{response_format}"
    )

    typer.echo(
        "Подходящих XML "
        "титула продавца: "
        f"{len(xml_paths)}"
    )

    if not xml_paths:
        raise RuntimeError(
            "В официальном архиве "
            "не найден товарный XML "
            "титула продавца УПД."
        )

    for index, xml_path in enumerate(
        xml_paths,
        start=1,
    ):
        import_result = (
            import_xml_file(
                database=database,
                root=(
                    document_directory
                ),
                file_path=xml_path,
                source_system=(
                    "TRUE_API_EDO"
                ),
                max_file_size_bytes=(
                    MAX_ENTRY_BYTES
                ),
            )
        )

        update_raw_source_message_id(
            database,
            raw_document_id=(
                import_result
                .raw_document_id
            ),
            document_id=(
                resolved_document_id
            ),
        )

        processing_result = (
            process_imported_document(
                database=database,
                file_path=xml_path,
                import_result=(
                    import_result
                ),
            )
        )

        print_result(
            index=index,
            total=len(
                xml_paths
            ),
            result=(
                processing_result
            ),
        )

    typer.echo("")

    typer.echo(
        "Официальная загрузка "
        "и обработка документа "
        "ЭДО завершены."
    )


if __name__ == "__main__":
    typer.run(
        main
    )