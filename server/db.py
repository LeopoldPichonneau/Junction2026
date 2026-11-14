"""Single place that opens MariaDB connections (credentials come from .env)."""
import os

import pymysql
import pymysql.cursors


def connect(dict_rows: bool = True) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "db"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "timeproof"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "timeproof"),
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor if dict_rows else pymysql.cursors.Cursor,
        # Wikipedia timestamps are UTC; without this, "as of" dates shift by the server's zone.
        init_command="SET time_zone = '+00:00'",
    )
