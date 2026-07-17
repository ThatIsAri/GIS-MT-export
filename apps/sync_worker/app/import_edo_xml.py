import hashlib
import re
import xml.etree.ElementTree as stdlib_element_tree
from dataclasses import dataclass
from pathlib import Path

import typer
from defusedxml.ElementTree import fromstring
from defusedxml.common import DefusedXmlException

from app.config import get_settings
from app.db import Database


XML_DECLARATION_ENCODING_PATTERN = re.compile(
    br"""<\?xml[^>]+encoding\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class XmlValidationResult:
    well_formed: bool
    detected_encoding: str | None
    parse_error: str | None


@dataclass(frozen=True, slots=True)
class FileImportResult:
    raw_document_id: int
    created: bool
    well_formed: bool


def detect_xml_encoding(
    content: bytes,
) -> str | None:
    """
    Определяет кодировку XML по BOM или XML-декларации.
    """

    if content.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"

    if content.startswith(b"\xff\xfe\x00\x00"):
        return "utf-32-le"

    if content.startswith(b"\x00\x00\xfe\xff"):
        return "utf-32-be"

    if content.startswith(b"\xff\xfe"):
        return "utf-16-le"

    if content.startswith(b"\xfe\xff"):
        return "utf-16-be"

    match = XML_DECLARATION_ENCODING_PATTERN.search(
        content[:1024]
    )

    if match is None:
        return None

    try:
        return match.group(1).decode(
            "ascii",
            errors="strict",
        )
    except UnicodeDecodeError:
        return None


def validate_xml(
    content: bytes,
) -> XmlValidationResult:
    """
    Проверяет синтаксическую корректность XML.

    defusedxml блокирует опасные XML-конструкции,
    включая внешние сущности.
    """

    detected_encoding = detect_xml_encoding(
        content
    )

    try:
        fromstring(content)

    except (
        stdlib_element_tree.ParseError,
        DefusedXmlException,
        ValueError,
    ) as exc:
        return XmlValidationResult(
            well_formed=False,
            detected_encoding=detected_encoding,
            parse_error=str(exc)[:4000],
        )

    return XmlValidationResult(
        well_formed=True,
        detected_encoding=detected_encoding,
        parse_error=None,
    )


def calculate_sha256(
    content: bytes,
) -> str:
    """
    Вычисляет SHA-256 исходного XML.
    """

    return hashlib.sha256(content).hexdigest()


def find_xml_files(
    root: Path,
    recursive: bool,
) -> list[Path]:
    """
    Возвращает XML-файлы в стабильном порядке.

    Символические ссылки не обрабатываются.
    Расширение проверяется без учёта регистра.
    """

    iterator = (
        root.rglob("*")
        if recursive
        else root.glob("*")
    )

    files: list[Path] = []

    for candidate in iterator:
        if candidate.is_symlink():
            continue

        if not candidate.is_file():
            continue

        if candidate.suffix.lower() != ".xml":
            continue

        files.append(candidate)

    return sorted(
        files,
        key=lambda path: path.as_posix().lower(),
    )


def validate_path_lengths(
    *,
    source_system: str,
    file_name: str,
    relative_path: str,
) -> None:
    """
    Проверяет соответствие ограничениям таблицы.
    """

    if len(source_system) > 64:
        raise ValueError(
            "Значение source_system превышает 64 символа."
        )

    if len(file_name) > 512:
        raise ValueError(
            "Имя XML-файла превышает 512 символов."
        )

    if len(relative_path) > 1024:
        raise ValueError(
            "Относительный путь XML превышает 1024 символа."
        )


def import_xml_file(
    *,
    database: Database,
    root: Path,
    file_path: Path,
    source_system: str,
    max_file_size_bytes: int,
) -> FileImportResult:
    """
    Импортирует один XML в raw_edo_document.

    Одинаковые файлы определяются по SHA-256.
    При повторном импорте новая строка не создаётся:
    увеличивается duplicate_count.
    """

    resolved_root = root.resolve()
    resolved_file = file_path.resolve()

    try:
        relative_path_object = (
            resolved_file.relative_to(
                resolved_root
            )
        )
    except ValueError as exc:
        raise ValueError(
            "XML-файл находится за пределами "
            "разрешённого каталога."
        ) from exc

    file_size = resolved_file.stat().st_size

    if file_size <= 0:
        raise ValueError(
            "XML-файл пуст."
        )

    if file_size > max_file_size_bytes:
        raise ValueError(
            "Размер XML превышает установленный предел: "
            f"{file_size} байт."
        )

    content = resolved_file.read_bytes()

    if len(content) != file_size:
        raise RuntimeError(
            "Размер прочитанного XML не совпадает "
            "с размером файла."
        )

    content_sha256 = calculate_sha256(
        content
    )

    validation = validate_xml(
        content
    )

    relative_path = (
        relative_path_object.as_posix()
    )

    validate_path_lengths(
        source_system=source_system,
        file_name=resolved_file.name,
        relative_path=relative_path,
    )

    parse_status = (
        "RAW"
        if validation.well_formed
        else "INVALID_XML"
    )

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO raw_edo_document (
                    source_system,
                    source_message_id,
                    original_file_name,
                    relative_path,
                    mime_type,
                    file_size_bytes,
                    content_sha256,
                    detected_encoding,
                    xml_content,
                    xml_well_formed,
                    parse_status,
                    parse_error,
                    external_document_id,
                    core_document_id,
                    duplicate_count,
                    first_imported_at,
                    last_seen_at,
                    parsed_at
                )
                VALUES (
                    %s,
                    NULL,
                    %s,
                    %s,
                    'application/xml',
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    NULL,
                    NULL,
                    0,
                    UTC_TIMESTAMP(3),
                    UTC_TIMESTAMP(3),
                    NULL
                )
                ON DUPLICATE KEY UPDATE
                    id = LAST_INSERT_ID(id),
                    duplicate_count = duplicate_count + 1,
                    last_seen_at = UTC_TIMESTAMP(3)
                """,
                (
                    source_system,
                    resolved_file.name,
                    relative_path,
                    file_size,
                    content_sha256,
                    validation.detected_encoding,
                    content,
                    1 if validation.well_formed else 0,
                    parse_status,
                    validation.parse_error,
                ),
            )

            created = cursor.rowcount == 1

            raw_document_id = int(
                cursor.lastrowid
            )

            if raw_document_id <= 0:
                raise RuntimeError(
                    "MySQL не вернула идентификатор "
                    "RAW-документа."
                )

            return FileImportResult(
                raw_document_id=raw_document_id,
                created=created,
                well_formed=validation.well_formed,
            )

        finally:
            cursor.close()


def main(
    path: Path = typer.Option(
        Path("/data/edo_inbox"),
        "--path",
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Каталог с исходными XML ЭДО.",
    ),

    source_system: str = typer.Option(
        "EDO_MANUAL",
        "--source-system",
        help="Код источника XML.",
    ),

    recursive: bool = typer.Option(
        True,
        "--recursive/--no-recursive",
        help=(
            "Искать XML также во вложенных "
            "каталогах."
        ),
    ),

    max_file_size_mb: int = typer.Option(
        50,
        "--max-file-size-mb",
        min=1,
        max=500,
        help="Максимальный размер одного XML.",
    ),
) -> None:
    """
    Сохраняет исходные XML в неизменяемый RAW-слой.

    Товарные строки и коды на этом этапе
    не извлекаются.
    """

    prepared_source_system = (
        source_system.strip()
    )

    if not prepared_source_system:
        raise typer.BadParameter(
            "Значение source-system не может быть пустым."
        )

    if len(prepared_source_system) > 64:
        raise typer.BadParameter(
            "Значение source-system превышает 64 символа."
        )

    resolved_path = path.resolve()

    typer.echo(
        f"Каталог импорта: {resolved_path}"
    )

    if not resolved_path.exists():
        raise typer.BadParameter(
            f"Каталог не найден: {resolved_path}"
        )

    if not resolved_path.is_dir():
        raise typer.BadParameter(
            f"Путь не является каталогом: {resolved_path}"
        )

    files = find_xml_files(
        resolved_path,
        recursive,
    )

    typer.echo(
        f"Найдено XML-файлов: {len(files)}"
    )

    if not files:
        typer.echo(
            "Импорт не требуется: каталог пуст."
        )
        return

    settings = get_settings()
    database = Database(settings)

    max_file_size_bytes = (
        max_file_size_mb
        * 1024
        * 1024
    )

    created_count = 0
    duplicate_count = 0
    invalid_xml_count = 0
    failed_count = 0

    for index, file_path in enumerate(
        files,
        start=1,
    ):
        try:
            result = import_xml_file(
                database=database,
                root=resolved_path,
                file_path=file_path,
                source_system=prepared_source_system,
                max_file_size_bytes=max_file_size_bytes,
            )

            if result.created:
                created_count += 1
            else:
                duplicate_count += 1

            if not result.well_formed:
                invalid_xml_count += 1

        except Exception as exc:
            failed_count += 1

            typer.echo(
                f"Файл {index}: "
                f"{type(exc).__name__}: {exc}",
                err=True,
            )

        if (
            index % 50 == 0
            or index == len(files)
        ):
            typer.echo(
                f"Обработано: {index}/{len(files)}"
            )

    typer.echo("")
    typer.echo("Импорт XML завершён.")

    typer.echo(
        f"Новых RAW-документов: {created_count}"
    )

    typer.echo(
        f"Повторных файлов: {duplicate_count}"
    )

    typer.echo(
        f"Некорректных XML: {invalid_xml_count}"
    )

    typer.echo(
        "Ошибок чтения или записи: "
        f"{failed_count}"
    )

    if failed_count > 0:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    typer.run(main)