from contextlib import contextmanager
from typing import Iterator

import mysql.connector
from mysql.connector import MySQLConnection

from app.config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def connect(self) -> MySQLConnection:
        return mysql.connector.connect(
            host=self._settings.db_host,
            port=self._settings.db_port,
            database=self._settings.db_name,
            user=self._settings.db_user,
            password=self._settings.db_password,
            autocommit=False,
            connection_timeout=10,
            charset="utf8mb4",
            collation="utf8mb4_unicode_ci",
        )

    @contextmanager
    def transaction(self) -> Iterator[MySQLConnection]:
        connection = self.connect()

        try:
            yield connection
            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def ping(self) -> None:
        connection = self.connect()

        try:
            connection.ping(
                reconnect=True,
                attempts=1,
                delay=0,
            )
        finally:
            connection.close()