from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from pathlib import Path
from typing import Any


AGENT_VERSION = "1.0.0"

MAX_REQUEST_BYTES = 16 * 1024

ALLOWED_POWERSHELL_EXIT_CODES = {
    0,
    2,
    3,
    4,
    10,
}


class AgentError(RuntimeError):
    pass


class RequestValidationError(AgentError):
    pass


@dataclass(
    frozen=True
)
class AgentSettings:
    host: str
    port: int
    api_key: str
    project_root: Path
    env_file: Path
    authorization_script: Path
    dkcl_path: Path
    powershell_path: str
    certificate_wait_seconds: int
    auth_timeout_seconds: int
    log_file: Path


def read_env_file(
    path: Path,
) -> dict[str, str]:
    if not path.is_file():
        raise AgentError(
            f"Файл окружения не найден: {path}"
        )

    result: dict[str, str] = {}

    for raw_line in path.read_text(
        encoding="utf-8-sig"
    ).splitlines():
        line = raw_line.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        name, value = line.split(
            "=",
            1,
        )

        name = name.strip()
        value = value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {
                "'",
                '"',
            }
        ):
            value = value[1:-1]

        if name:
            result[name] = value

    return result


def normalize_inn(
    value: Any,
) -> str:
    prepared = str(
        value
        or ""
    ).strip()

    if (
        not prepared.isdigit()
        or len(prepared)
        not in {
            10,
            12,
        }
    ):
        raise RequestValidationError(
            "ИНН должен содержать 10 или 12 цифр."
        )

    return prepared


def normalize_thumbprint(
    value: Any,
) -> str:
    prepared = (
        str(
            value
            or ""
        )
        .replace(
            " ",
            "",
        )
        .strip()
        .upper()
    )

    if (
        len(prepared) != 40
        or any(
            character
            not in "0123456789ABCDEF"
            for character
            in prepared
        )
    ):
        raise RequestValidationError(
            (
                "Отпечаток сертификата должен "
                "содержать 40 шестнадцатеричных символов."
            )
        )

    return prepared


def normalize_store_location(
    value: Any,
) -> str:
    prepared = str(
        value
        or "CurrentUser"
    ).strip()

    if prepared not in {
        "CurrentUser",
        "LocalMachine",
    }:
        raise RequestValidationError(
            (
                "Допустимые хранилища: "
                "CurrentUser или LocalMachine."
            )
        )

    return prepared


def normalize_store_name(
    value: Any,
) -> str:
    prepared = str(
        value
        or "My"
    ).strip()

    if not prepared:
        raise RequestValidationError(
            "Имя хранилища сертификатов не заполнено."
        )

    if len(prepared) > 64:
        raise RequestValidationError(
            "Имя хранилища сертификатов слишком длинное."
        )

    return prepared


def normalize_device_name(
    value: Any,
) -> str:
    prepared = str(
        value
        or ""
    ).strip()

    if not prepared:
        raise RequestValidationError(
            "Не указано точное имя устройства DiskKontrol."
        )

    if len(prepared) > 255:
        raise RequestValidationError(
            "Имя устройства DiskKontrol слишком длинное."
        )

    return prepared


def last_json_object(
    output: str,
) -> dict[str, Any]:
    for raw_line in reversed(
        output.splitlines()
    ):
        line = raw_line.strip()

        if not (
            line.startswith("{")
            and line.endswith("}")
        ):
            continue

        try:
            value = json.loads(
                line
            )

        except json.JSONDecodeError:
            continue

        if isinstance(
            value,
            dict,
        ):
            return value

    raise AgentError(
        (
            "PowerShell-сценарий авторизации "
            "не вернул итоговый JSON."
        )
    )


class AuthorizationService:
    def __init__(
        self,
        settings: AgentSettings,
    ) -> None:
        self.settings = settings
        self._authorization_lock = (
            threading.Lock()
        )

    @property
    def busy(
        self,
    ) -> bool:
        return self._authorization_lock.locked()

    def authorize(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._authorization_lock.acquire(
            blocking=False
        ):
            return {
                "status": "SKIPPED_AGENT_BUSY",
                "message": (
                    "Windows certificate-agent уже "
                    "выполняет другую авторизацию."
                ),
            }

        try:
            return self._authorize_locked(
                payload
            )

        finally:
            self._authorization_lock.release()

    def _authorize_locked(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        legal_entity_id = int(
            payload.get(
                "legal_entity_id"
            )
            or 0
        )

        if legal_entity_id <= 0:
            raise RequestValidationError(
                "Некорректный ID организации."
            )

        device_name = normalize_device_name(
            payload.get(
                "device_name"
            )
        )

        inn = normalize_inn(
            payload.get(
                "inn"
            )
        )

        thumbprint = normalize_thumbprint(
            payload.get(
                "thumbprint"
            )
        )

        store_location = (
            normalize_store_location(
                payload.get(
                    "store_location"
                )
            )
        )

        store_name = normalize_store_name(
            payload.get(
                "store_name"
            )
        )

        command = [
            self.settings.powershell_path,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(
                self.settings.authorization_script
            ),
            "-DeviceName",
            device_name,
            "-Inn",
            inn,
            "-CertificateThumbprint",
            thumbprint,
            "-StoreLocation",
            store_location,
            "-StoreName",
            store_name,
            "-EnvFile",
            str(
                self.settings.env_file
            ),
            "-DkclPath",
            str(
                self.settings.dkcl_path
            ),
            "-CertificateWaitSeconds",
            str(
                self.settings
                .certificate_wait_seconds
            ),
            "-AuthTimeoutSeconds",
            str(
                self.settings
                .auth_timeout_seconds
            ),
            "-AllowPinPrompt",
        ]

        timeout_seconds = (
            self.settings.certificate_wait_seconds
            + self.settings.auth_timeout_seconds
            + 90
        )

        logging.info(
            (
                "Авторизация начата: "
                "entity_id=%s; device=%s."
            ),
            legal_entity_id,
            device_name,
        )

        try:
            completed = subprocess.run(
                command,
                cwd=str(
                    self.settings.project_root
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=timeout_seconds,
                env={
                    **os.environ,
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                },
            )

        except subprocess.TimeoutExpired as exc:
            logging.error(
                (
                    "Авторизация превысила тайм-аут: "
                    "entity_id=%s."
                ),
                legal_entity_id,
            )

            raise AgentError(
                (
                    "Авторизация превысила допустимое "
                    "время выполнения."
                )
            ) from exc

        try:
            result = last_json_object(
                completed.stdout
                or ""
            )

        except AgentError:
            safe_output = (
                completed.stdout
                or ""
            ).strip()

            logging.error(
                (
                    "PowerShell не вернул JSON: "
                    "entity_id=%s; exit_code=%s; "
                    "output=%s"
                ),
                legal_entity_id,
                completed.returncode,
                safe_output[-2000:],
            )

            raise

        status = str(
            result.get(
                "status"
            )
            or "ERROR"
        ).upper()

        if (
            completed.returncode
            not in ALLOWED_POWERSHELL_EXIT_CODES
        ):
            result.pop(
                "token",
                None,
            )

            logging.error(
                (
                    "Неожиданный код PowerShell: "
                    "entity_id=%s; exit_code=%s; "
                    "status=%s."
                ),
                legal_entity_id,
                completed.returncode,
                status,
            )

            return {
                "status": "ERROR",
                "error_type": (
                    "POWERSHELL_EXIT_CODE"
                ),
                "message": (
                    "Сценарий авторизации завершился "
                    "с неожиданным кодом "
                    f"{completed.returncode}."
                ),
            }

        logging.info(
            (
                "Авторизация завершена: "
                "entity_id=%s; status=%s."
            ),
            legal_entity_id,
            status,
        )

        return result


class CertificateAgentServer(
    ThreadingHTTPServer
):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[
            BaseHTTPRequestHandler
        ],
        *,
        service: AuthorizationService,
        api_key: str,
    ) -> None:
        super().__init__(
            server_address,
            handler_class,
        )

        self.service = service
        self.api_key = api_key


class CertificateAgentHandler(
    BaseHTTPRequestHandler
):
    server: CertificateAgentServer

    protocol_version = "HTTP/1.1"

    def log_message(
        self,
        format: str,
        *args: Any,
    ) -> None:
        return

    def send_json(
        self,
        status_code: int,
        payload: dict[str, Any],
    ) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        ).encode(
            "utf-8"
        )

        self.send_response(
            status_code
        )

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )

        self.send_header(
            "Content-Length",
            str(
                len(
                    body
                )
            ),
        )

        self.send_header(
            "Cache-Control",
            "no-store",
        )

        self.send_header(
            "Connection",
            "close",
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    def authorized(
        self,
    ) -> bool:
        header = self.headers.get(
            "Authorization",
            "",
        )

        prefix = "Bearer "

        if not header.startswith(
            prefix
        ):
            return False

        supplied_key = header[
            len(
                prefix
            ):
        ].strip()

        return hmac.compare_digest(
            supplied_key,
            self.server.api_key,
        )

    def do_GET(
        self,
    ) -> None:
        if self.path != "/health":
            self.send_json(
                404,
                {
                    "status": "ERROR",
                    "message": "Endpoint не найден.",
                },
            )

            return

        self.send_json(
            200,
            {
                "status": "OK",
                "service": "certificate-agent",
                "version": AGENT_VERSION,
                "busy": self.server.service.busy,
            },
        )

    def do_POST(
        self,
    ) -> None:
        if self.path != "/authorize":
            self.send_json(
                404,
                {
                    "status": "ERROR",
                    "message": "Endpoint не найден.",
                },
            )

            return

        if not self.authorized():
            self.send_json(
                401,
                {
                    "status": "ERROR",
                    "message": "Ошибка авторизации агента.",
                },
            )

            return

        content_length_value = (
            self.headers.get(
                "Content-Length",
                "",
            )
        )

        try:
            content_length = int(
                content_length_value
            )

        except ValueError:
            self.send_json(
                411,
                {
                    "status": "ERROR",
                    "message": (
                        "Не указан корректный "
                        "Content-Length."
                    ),
                },
            )

            return

        if (
            content_length <= 0
            or content_length > MAX_REQUEST_BYTES
        ):
            self.send_json(
                413,
                {
                    "status": "ERROR",
                    "message": (
                        "Некорректный размер запроса."
                    ),
                },
            )

            return

        try:
            raw_body = self.rfile.read(
                content_length
            )

            payload = json.loads(
                raw_body.decode(
                    "utf-8"
                )
            )

            if not isinstance(
                payload,
                dict,
            ):
                raise RequestValidationError(
                    (
                        "Тело запроса должно быть "
                        "JSON-объектом."
                    )
                )

            result = (
                self.server.service.authorize(
                    payload
                )
            )

            self.send_json(
                200,
                result,
            )

        except RequestValidationError as exc:
            self.send_json(
                400,
                {
                    "status": "ERROR",
                    "error_type": (
                        type(
                            exc
                        ).__name__
                    ),
                    "message": str(
                        exc
                    ),
                },
            )

        except json.JSONDecodeError:
            self.send_json(
                400,
                {
                    "status": "ERROR",
                    "error_type": (
                        "JSON_DECODE_ERROR"
                    ),
                    "message": (
                        "Некорректное JSON-тело запроса."
                    ),
                },
            )

        except Exception as exc:
            logging.exception(
                "Необработанная ошибка certificate-agent."
            )

            self.send_json(
                500,
                {
                    "status": "ERROR",
                    "error_type": (
                        type(
                            exc
                        ).__name__
                    ),
                    "message": str(
                        exc
                    ),
                },
            )


def configure_logging(
    log_file: Path,
) -> None:
    log_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "%(levelname)s "
            "%(message)s"
        ),
        handlers=[
            logging.FileHandler(
                log_file,
                encoding="utf-8",
            ),
            logging.StreamHandler(
                sys.stdout
            ),
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Windows-агент сертификатов "
            "для Docker pipeline-dispatcher."
        )
    )

    parser.add_argument(
        "--project-root",
        default="",
    )

    parser.add_argument(
        "--env-file",
        default="",
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=18771,
    )

    parser.add_argument(
        "--dkcl-path",
        default=(
            r"C:\Users\kudryavcev"
            r"\Desktop\dkcl64.exe"
        ),
    )

    parser.add_argument(
        "--powershell-path",
        default="powershell.exe",
    )

    parser.add_argument(
        "--certificate-wait-seconds",
        type=int,
        default=60,
    )

    parser.add_argument(
        "--auth-timeout-seconds",
        type=int,
        default=60,
    )

    return parser.parse_args()


def build_settings(
    args: argparse.Namespace,
) -> AgentSettings:
    script_path = Path(
        __file__
    ).resolve()

    project_root = (
        Path(
            args.project_root
        ).resolve()
        if args.project_root
        else script_path.parent.parent
    )

    env_file = (
        Path(
            args.env_file
        ).resolve()
        if args.env_file
        else project_root / ".env"
    )

    env_values = read_env_file(
        env_file
    )

    api_key = (
        os.getenv(
            "CERTIFICATE_AGENT_API_KEY",
            "",
        ).strip()
        or env_values.get(
            "CERTIFICATE_AGENT_API_KEY",
            "",
        ).strip()
    )

    if len(api_key) < 32:
        raise AgentError(
            (
                "CERTIFICATE_AGENT_API_KEY "
                "не задан или слишком короткий."
            )
        )

    authorization_script = (
        project_root
        / "tools"
        / "authorize_pipeline_entity.ps1"
    )

    dkcl_path = Path(
        args.dkcl_path
    ).resolve()

    log_file = (
        project_root
        / "logs"
        / "certificate_agent"
        / "certificate_agent.log"
    )

    settings = AgentSettings(
        host=str(
            args.host
        ),
        port=int(
            args.port
        ),
        api_key=api_key,
        project_root=project_root,
        env_file=env_file,
        authorization_script=(
            authorization_script
        ),
        dkcl_path=dkcl_path,
        powershell_path=str(
            args.powershell_path
        ),
        certificate_wait_seconds=int(
            args.certificate_wait_seconds
        ),
        auth_timeout_seconds=int(
            args.auth_timeout_seconds
        ),
        log_file=log_file,
    )

    required_paths = {
        "project root":
            settings.project_root,
        ".env":
            settings.env_file,
        "authorization script":
            settings.authorization_script,
        "dkcl64.exe":
            settings.dkcl_path,
    }

    for name, path in required_paths.items():
        if not path.exists():
            raise AgentError(
                f"Не найден {name}: {path}"
            )

    if not 1 <= settings.port <= 65535:
        raise AgentError(
            "Некорректный TCP-порт."
        )

    if settings.certificate_wait_seconds <= 0:
        raise AgentError(
            (
                "certificate_wait_seconds "
                "должен быть больше нуля."
            )
        )

    if settings.auth_timeout_seconds <= 0:
        raise AgentError(
            (
                "auth_timeout_seconds "
                "должен быть больше нуля."
            )
        )

    return settings


def main() -> int:
    args = parse_args()

    settings = build_settings(
        args
    )

    configure_logging(
        settings.log_file
    )

    service = AuthorizationService(
        settings
    )

    server = CertificateAgentServer(
        (
            settings.host,
            settings.port,
        ),
        CertificateAgentHandler,
        service=service,
        api_key=settings.api_key,
    )

    logging.info(
        (
            "Certificate-agent запущен. "
            "Host=%s; port=%s; version=%s."
        ),
        settings.host,
        settings.port,
        AGENT_VERSION,
    )

    try:
        server.serve_forever(
            poll_interval=0.5
        )

    except KeyboardInterrupt:
        logging.info(
            "Certificate-agent остановлен пользователем."
        )

    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )

    except Exception as exc:
        print(
            (
                "ERROR: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            file=sys.stderr,
            flush=True,
        )

        raise SystemExit(
            1
        ) from exc