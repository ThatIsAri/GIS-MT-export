from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import typer
from defusedxml.ElementTree import fromstring


MAX_XML_SIZE_BYTES = 50 * 1024 * 1024

MARKING_KEYWORDS = (
    "маркир",
    "киз",
    "кигу",
    "киту",
    "агрег",
    "иденттов",
    "средидент",
    "номсредиденттов",
    "кодтов",
    "кодидентиф",
)

DOCUMENT_KEYWORDS = (
    "идфайл",
    "версформ",
    "кнд",
    "функция",
    "счфакт",
    "документ",
    "сведтов",
)


@dataclass(slots=True)
class PathStatistics:
    count: int = 0
    attribute_names: Counter[str] = field(
        default_factory=Counter
    )
    text_node_count: int = 0
    text_lengths: list[int] = field(
        default_factory=list
    )


def local_name(value: str) -> str:
    """
    Удаляет namespace из имени XML-элемента
    или атрибута.
    """

    if "}" in value:
        return value.rsplit("}", 1)[1]

    if ":" in value:
        return value.rsplit(":", 1)[1]

    return value


def find_xml_files(
    root: Path,
    recursive: bool,
) -> list[Path]:
    """
    Находит XML-файлы в стабильном порядке.
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
        key=lambda item: (
            item.stat().st_mtime_ns,
            item.as_posix().lower(),
        ),
    )


def walk_element(
    element,
    parent_path: str,
    statistics: dict[str, PathStatistics],
) -> None:
    """
    Обходит XML и собирает только структурную
    статистику, не сохраняя значения.
    """

    element_name = local_name(
        element.tag
    )

    current_path = (
        f"{parent_path}/{element_name}"
        if parent_path
        else f"/{element_name}"
    )

    current_statistics = statistics.setdefault(
        current_path,
        PathStatistics(),
    )

    current_statistics.count += 1

    for attribute_name in element.attrib:
        current_statistics.attribute_names[
            local_name(attribute_name)
        ] += 1

    text_value = (
        element.text or ""
    ).strip()

    if text_value:
        current_statistics.text_node_count += 1

        current_statistics.text_lengths.append(
            len(text_value)
        )

    for child in list(element):
        walk_element(
            child,
            current_path,
            statistics,
        )


def format_attribute_names(
    attribute_names: Counter[str],
) -> str:
    """
    Формирует список названий атрибутов
    без их значений.
    """

    if not attribute_names:
        return "-"

    return ", ".join(
        sorted(
            attribute_names.keys(),
            key=str.lower,
        )
    )


def format_text_statistics(
    statistics: PathStatistics,
) -> str:
    """
    Выводит количество текстовых узлов
    и диапазон длины значений.
    """

    if not statistics.text_lengths:
        return "text=0"

    minimum_length = min(
        statistics.text_lengths
    )

    maximum_length = max(
        statistics.text_lengths
    )

    return (
        f"text={statistics.text_node_count}, "
        f"length={minimum_length}..{maximum_length}"
    )


def is_candidate_path(
    path: str,
    statistics: PathStatistics,
    keywords: tuple[str, ...],
) -> bool:
    """
    Проверяет путь и названия атрибутов
    на наличие заданных ключевых слов.
    """

    searchable_parts = [
        path.lower(),
        *(
            attribute_name.lower()
            for attribute_name
            in statistics.attribute_names
        ),
    ]

    searchable_text = " ".join(
        searchable_parts
    )

    return any(
        keyword in searchable_text
        for keyword in keywords
    )


def analyze_xml_file(
    file_path: Path,
    sequence_number: int,
    max_paths: int,
) -> None:
    """
    Анализирует один XML без вывода содержимого.
    """

    file_size = file_path.stat().st_size

    if file_size <= 0:
        raise ValueError(
            "XML-файл пуст."
        )

    if file_size > MAX_XML_SIZE_BYTES:
        raise ValueError(
            "XML превышает допустимый размер."
        )

    content = file_path.read_bytes()

    content_sha256 = hashlib.sha256(
        content
    ).hexdigest()

    root = fromstring(content)

    statistics: dict[
        str,
        PathStatistics,
    ] = {}

    walk_element(
        root,
        "",
        statistics,
    )

    root_attribute_names = sorted(
        (
            local_name(attribute_name)
            for attribute_name
            in root.attrib
        ),
        key=str.lower,
    )

    total_elements = sum(
        item.count
        for item in statistics.values()
    )

    total_attributes = sum(
        sum(
            item.attribute_names.values()
        )
        for item in statistics.values()
    )

    typer.echo("")
    typer.echo(
        f"XML #{sequence_number}"
    )

    typer.echo(
        f"Размер: {file_size} байт"
    )

    typer.echo(
        f"SHA-256: {content_sha256[:16]}..."
    )

    typer.echo(
        "Корневой элемент: "
        f"{local_name(root.tag)}"
    )

    typer.echo(
        "Атрибуты корня: "
        + (
            ", ".join(
                root_attribute_names
            )
            if root_attribute_names
            else "-"
        )
    )

    typer.echo(
        f"Всего элементов: {total_elements}"
    )

    typer.echo(
        "Уникальных структурных путей: "
        f"{len(statistics)}"
    )

    typer.echo(
        f"Всего атрибутов: {total_attributes}"
    )

    typer.echo("")
    typer.echo(
        "Структура XML:"
    )

    sorted_paths = sorted(
        statistics.items(),
        key=lambda item: (
            item[0].count("/"),
            item[0].lower(),
        ),
    )

    for index, (
        path,
        path_statistics,
    ) in enumerate(
        sorted_paths,
        start=1,
    ):
        if index > max_paths:
            typer.echo(
                "Вывод структуры ограничен: "
                f"показано {max_paths} путей."
            )
            break

        typer.echo(
            f"{path} | "
            f"count={path_statistics.count} | "
            f"attrs={format_attribute_names(path_statistics.attribute_names)} | "
            f"{format_text_statistics(path_statistics)}"
        )

    marking_candidates = [
        (
            path,
            path_statistics,
        )
        for (
            path,
            path_statistics,
        ) in sorted_paths
        if is_candidate_path(
            path,
            path_statistics,
            MARKING_KEYWORDS,
        )
    ]

    typer.echo("")
    typer.echo(
        "Кандидаты на маркировочные данные:"
    )

    if not marking_candidates:
        typer.echo(
            "Не обнаружены."
        )

    for (
        path,
        path_statistics,
    ) in marking_candidates:
        typer.echo(
            f"{path} | "
            f"count={path_statistics.count} | "
            f"attrs={format_attribute_names(path_statistics.attribute_names)} | "
            f"{format_text_statistics(path_statistics)}"
        )

    document_candidates = [
        (
            path,
            path_statistics,
        )
        for (
            path,
            path_statistics,
        ) in sorted_paths
        if is_candidate_path(
            path,
            path_statistics,
            DOCUMENT_KEYWORDS,
        )
    ]

    typer.echo("")
    typer.echo(
        "Кандидаты на реквизиты документа:"
    )

    if not document_candidates:
        typer.echo(
            "Не обнаружены."
        )

    for (
        path,
        path_statistics,
    ) in document_candidates:
        typer.echo(
            f"{path} | "
            f"count={path_statistics.count} | "
            f"attrs={format_attribute_names(path_statistics.attribute_names)} | "
            f"{format_text_statistics(path_statistics)}"
        )


def main(
    path: Path = typer.Option(
        Path("/data/edo_inbox/bff"),
        "--path",
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Каталог с XML ЭДО.",
    ),

    recursive: bool = typer.Option(
        True,
        "--recursive/--no-recursive",
        help="Искать XML во вложенных каталогах.",
    ),

    latest_only: bool = typer.Option(
        True,
        "--latest-only/--all-files",
        help=(
            "Анализировать только последний XML "
            "или все найденные файлы."
        ),
    ),

    max_paths: int = typer.Option(
        250,
        "--max-paths",
        min=1,
        max=2000,
        help=(
            "Максимальное количество структурных "
            "путей в отчёте."
        ),
    ),
) -> None:
    """
    Показывает безопасную структуру XML УПД.

    Значения атрибутов и текстовых элементов
    не выводятся.
    """

    resolved_path = path.resolve()

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
        raise typer.Exit(
            code=1
        )

    selected_files = (
        [files[-1]]
        if latest_only
        else files
    )

    typer.echo(
        "Выбрано для анализа: "
        f"{len(selected_files)}"
    )

    failed_count = 0

    for sequence_number, file_path in enumerate(
        selected_files,
        start=1,
    ):
        try:
            analyze_xml_file(
                file_path=file_path,
                sequence_number=sequence_number,
                max_paths=max_paths,
            )

        except Exception as exc:
            failed_count += 1

            typer.echo(
                "Ошибка анализа XML "
                f"#{sequence_number}: "
                f"{type(exc).__name__}: {exc}",
                err=True,
            )

    if failed_count:
        raise typer.Exit(
            code=2
        )


if __name__ == "__main__":
    typer.run(main)