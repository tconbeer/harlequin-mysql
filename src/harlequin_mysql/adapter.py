from __future__ import annotations

from typing import Any, Sequence

from harlequin import (
    HarlequinAdapter,
    HarlequinConnection,
    HarlequinCursor,
)
from harlequin.autocomplete.completion import HarlequinCompletion
from harlequin.catalog import Catalog, CatalogItem
from harlequin.exception import (
    HarlequinConfigError,
    HarlequinConnectionError,
    HarlequinQueryError,
)
from mysql.connector import FieldType
from mysql.connector.cursor import MySQLCursor
from mysql.connector.pooling import MySQLConnectionPool
from textual_fastdatatable.backend import AutoBackendType

from harlequin_mysql.cli_options import MYSQLADAPTER_OPTIONS
from harlequin_mysql.completions import load_completions


class HarlequinMySQLCursor(HarlequinCursor):
    def __init__(self, cur: MySQLCursor, *_: Any, **__: Any) -> None:
        self.cur = cur
        self._limit: int | None = None

    def columns(self) -> list[tuple[str, str]]:
        assert self.cur.description is not None
        return [(col[0], self._get_short_type(col[1])) for col in self.cur.description]

    def set_limit(self, limit: int) -> "HarlequinMySQLCursor":
        self._limit = limit
        return self

    def fetchall(self) -> AutoBackendType:
        try:
            if self._limit is None:
                return self.cur.fetchall()
            else:
                return self.cur.fetchmany(self._limit)
        except Exception as e:
            raise HarlequinQueryError(
                msg=str(e),
                title="Harlequin encountered an error while executing your query.",
            ) from e

    @staticmethod
    def _get_short_type(type_id: int) -> str:
        mapping = {
            FieldType.BIT: "010",
            FieldType.BLOB: "0b",
            FieldType.DATE: "d",
            FieldType.DATETIME: "dt",
            FieldType.DECIMAL: "#.#",
            FieldType.DOUBLE: "#.#",
            FieldType.ENUM: "enum",
            FieldType.FLOAT: "#.#",
            FieldType.GEOMETRY: "▽□",
            FieldType.INT24: "###",
            FieldType.JSON: "{}",
            FieldType.LONG: "##",
            FieldType.LONGLONG: "##",
            FieldType.LONG_BLOB: "00b",
            FieldType.MEDIUM_BLOB: "00b",
            FieldType.NEWDATE: "d",
            FieldType.NEWDECIMAL: "#.#",
            FieldType.NULL: "∅",
            FieldType.SET: "set",
            FieldType.SHORT: "#",
            FieldType.STRING: "s",
            FieldType.TIME: "t",
            FieldType.TIMESTAMP: "#ts",
            FieldType.TINY: "#",
            FieldType.TINY_BLOB: "b",
            FieldType.VARCHAR: "s",
            FieldType.VAR_STRING: "s",
            FieldType.YEAR: "y",
        }
        return mapping.get(type_id, "?")


class HarlequinMySQLConnection(HarlequinConnection):
    def __init__(
        self,
        conn_str: Sequence[str],
        *_: Any,
        init_message: str = "",
        options: dict[str, Any],
    ) -> None:
        self.init_message = init_message
        try:
            self.pool: MySQLConnectionPool = MySQLConnectionPool(
                pool_size=5, pool_reset_session=False, **options, autocommit=True
            )
        except Exception as e:
            raise HarlequinConnectionError(
                msg=str(e), title="Harlequin could not connect to your database."
            ) from e

    def execute(self, query: str) -> HarlequinCursor | None:
        try:
            conn = self.pool.get_connection()
            cur = conn.cursor()
            cur.execute(query)
        except Exception as e:
            raise HarlequinQueryError(
                msg=str(e),
                title="Harlequin encountered an error while executing your query.",
            ) from e
        else:
            if cur.description is not None:
                return HarlequinMySQLCursor(cur)
            else:
                return None
        finally:
            conn.close()

    def get_catalog(self) -> Catalog:
        databases = self._get_databases()
        db_items: list[CatalogItem] = []
        for (db,) in databases:
            relations = self._get_relations(db)
            rel_items: list[CatalogItem] = []
            for rel, rel_type in relations:
                cols = self._get_columns(db, rel)
                col_items = [
                    CatalogItem(
                        qualified_identifier=f"`{db}`.`{rel}`.`{col}`",
                        query_name=f"`{col}`",
                        label=col,
                        type_label=self._get_short_col_type(col_type),
                    )
                    for col, col_type in cols
                ]
                rel_items.append(
                    CatalogItem(
                        qualified_identifier=f"`{db}`.`{rel}`",
                        query_name=f"`{db}`.`{rel}`",
                        label=rel,
                        type_label=rel_type,
                        children=col_items,
                    )
                )
            db_items.append(
                CatalogItem(
                    qualified_identifier=f"`{db}`",
                    query_name=f"`{db}`",
                    label=db,
                    type_label="db",
                    children=rel_items,
                )
            )
        return Catalog(items=db_items)

    def get_completions(self) -> list[HarlequinCompletion]:
        return load_completions()

    def _get_databases(self) -> list[tuple[str]]:
        conn = self.pool.get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            show databases
            where `Database` not in (
                'sys', 'information_schema', 'performance_schema', 'mysql'
            )
            """
        )
        results: list[tuple[str]] = cur.fetchall()
        conn.close()
        return results

    def _get_relations(self, db_name: str) -> list[tuple[str, str]]:
        conn = self.pool.get_connection()
        cur = conn.cursor()
        cur.execute(
            f"""
            select 
                table_name, 
                case 
                    when table_type like '%TABLE' then 't' 
                    else 'v' 
                end as table_type
            from information_schema.tables
            where table_schema = '{db_name}'
            ;"""
        )
        results: list[tuple[str, str]] = cur.fetchall()
        conn.close()
        return results

    def _get_columns(self, db_name: str, rel_name: str) -> list[tuple[str, str]]:
        conn = self.pool.get_connection()
        cur = conn.cursor()
        cur.execute(
            f"""
            select column_name, data_type
            from information_schema.columns
            where
                table_schema = '{db_name}'
                and table_name = '{rel_name}'
            ;"""
        )
        results: list[tuple[str, str]] = cur.fetchall()
        conn.close()
        return results

    @staticmethod
    def _get_short_col_type(info_schema_type: str) -> str:
        mapping = {
            "bigint": "###",
            "binary": "010",
            "blob": "0b",
            "char": "c",
            "datetime": "dt",
            "decimal": "#.#",
            "double": "#.#",
            "enum": "enum",
            "float": "#.#",
            "int": "##",
            "json": "{}",
            "longblob": "00b",
            "longtext": "ss",
            "mediumblob": "00b",
            "mediumint": "##",
            "mediumtext": "s",
            "set": "set",
            "smallint": "#",
            "text": "s",
            "time": "t",
            "timestamp": "ts",
            "tinyint": "#",
            "varbinary": "010",
            "varchar": "s",
        }
        return mapping.get(info_schema_type, "?")


class HarlequinMySQLAdapter(HarlequinAdapter):
    ADAPTER_OPTIONS = MYSQLADAPTER_OPTIONS

    def __init__(
        self,
        conn_str: Sequence[str],
        host: str | None = None,
        port: str | int | None = 3306,
        unix_socket: str | None = None,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        password2: str | None = None,
        password3: str | None = None,
        connection_timeout: str | int | None = None,
        ssl_ca: str | None = None,
        ssl_cert: str | None = None,
        ssl_disabled: str | bool | None = False,
        ssl_key: str | None = None,
        **_: Any,
    ) -> None:
        if conn_str:
            raise HarlequinConnectionError(
                f"Cannot provide a DSN to the MySQL adapter. Got:\n{conn_str}"
            )
        try:
            self.options = {
                "host": host,
                "port": int(port) if port is not None else 3306,
                "unix_socket": unix_socket,
                "database": database,
                "user": user,
                "password": password,
                "password2": password2,
                "password3": password3,
                "connection_timeout": int(connection_timeout)
                if connection_timeout is not None
                else None,
                "ssl_ca": ssl_ca,
                "ssl_cert": ssl_cert,
                "ssl_disabled": ssl_disabled if ssl_disabled is not None else False,
                "ssl_key": ssl_key,
            }
        except (ValueError, TypeError) as e:
            raise HarlequinConfigError(
                msg=f"MySQL adapter received bad config value: {e}",
                title="Harlequin could not initialize the selected adapter.",
            ) from e

    def connect(self) -> HarlequinMySQLConnection:
        conn = HarlequinMySQLConnection(conn_str=tuple(), options=self.options)
        return conn
