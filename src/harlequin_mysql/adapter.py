from __future__ import annotations

import re
from contextlib import suppress
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
from mysql.connector.errors import InternalError, PoolError
from mysql.connector.pooling import (
    MySQLConnectionPool,
    PooledMySQLConnection,
)
from textual_fastdatatable.backend import AutoBackendType

from harlequin_mysql.catalog import DatabaseCatalogItem
from harlequin_mysql.cli_options import MYSQLADAPTER_OPTIONS
from harlequin_mysql.completions import load_completions

USE_DATABASE_PROG = re.compile(
    r"\s*use\s+([^\\/?%*:|\"<>.]{1,64})", flags=re.IGNORECASE
)
QUERY_INTERRUPT_MSG = "1317 (70100): Query execution was interrupted"


class HarlequinMySQLCursor(HarlequinCursor):
    def __init__(
        self,
        cur: MySQLCursor,
        conn: PooledMySQLConnection,
        harlequin_conn: HarlequinMySQLConnection,
        *_: Any,
        **__: Any,
    ) -> None:
        self.cur = cur

        # copy description in case the cursor is closed before columns() is called
        assert cur.description is not None
        self.description = cur.description.copy()

        self.conn = conn
        self.harlequin_conn = harlequin_conn
        self.connection_id = conn._cnx.connection_id
        self._limit: int | None = None

    def columns(self) -> list[tuple[str, str]]:
        return [(col[0], self._get_short_type(col[1])) for col in self.description]

    def set_limit(self, limit: int) -> "HarlequinMySQLCursor":
        self._limit = limit
        return self

    def fetchall(self) -> AutoBackendType:
        try:
            if self._limit is None:
                results = self.cur.fetchall()
            else:
                results = self.cur.fetchmany(self._limit)
            return results
        except Exception as e:
            if str(e) == QUERY_INTERRUPT_MSG:
                return []
            else:
                raise HarlequinQueryError(
                    msg=str(e),
                    title="Harlequin encountered an error while executing your query.",
                ) from e
        finally:
            self.conn.consume_results()
            self.cur.close()
            self.conn.close()
            if self.connection_id:
                self.harlequin_conn._in_use_connections.discard(self.connection_id)

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
        self._in_use_connections: set[int] = set()
        try:
            self._pool: MySQLConnectionPool = MySQLConnectionPool(
                pool_name="harlequin",
                pool_reset_session=False,
                autocommit=True,
                **options,
            )
        except Exception as e:
            raise HarlequinConnectionError(
                msg=str(e), title="Harlequin could not connect to your database."
            ) from e

    def safe_get_mysql_cursor(
        self, buffered: bool = False
    ) -> tuple[PooledMySQLConnection | None, MySQLCursor | None]:
        """
        Return None if the connection pool is exhausted, to avoid getting
        in an unrecoverable state.
        """
        try:
            conn = self._pool.get_connection()
        except (InternalError, PoolError):
            # if we're out of connections, we can't raise a query error,
            # or we get in a state where we have cursors without fetched
            # results, which requires a restart of Harlequin. Instead,
            # just return None and silently fail (there isn't a sensible
            # way to show an error to the user without aborting processing
            # all the other cursors).
            return None, None

        try:
            cur: MySQLCursor = conn.cursor(buffered=buffered)
        except InternalError:
            # cursor has an unread result. Try to consume the results,
            # and try again.
            conn.consume_results()
            cur = conn.cursor(buffered=buffered)

        return conn, cur

    def set_pool_config(self, **config: Any) -> None:
        """
        Updates the config of the MySQL connection pool.
        """
        self._pool.set_config(**config)

    def execute(self, query: str) -> HarlequinCursor | None:
        retval: HarlequinCursor | None = None

        conn, cur = self.safe_get_mysql_cursor()
        if conn is None or cur is None:
            return None
        else:
            connection_id = conn._cnx.connection_id
            if connection_id:
                self._in_use_connections.add(connection_id)

        try:
            cur.execute(query)
        except Exception as e:
            cur.close()
            conn.close()
            if connection_id:
                self._in_use_connections.discard(connection_id)
            if str(e) == QUERY_INTERRUPT_MSG:
                return None
            else:
                raise HarlequinQueryError(
                    msg=str(e),
                    title="Harlequin encountered an error while executing your query.",
                ) from e
        else:
            if cur.description is not None:
                retval = HarlequinMySQLCursor(cur, conn=conn, harlequin_conn=self)
            else:
                cur.close()
                conn.close()
                if connection_id:
                    self._in_use_connections.discard(connection_id)

        # this is a hack to update all connections in the pool if the user
        # changes the database for the active connection.
        # it is impossible to check the database or other config
        # of a connection with an open cursor, and we can't use a dedicated
        # connection for user queries, since mysql only supports a single
        # (unfetched) cursor per connection.
        if match := USE_DATABASE_PROG.match(query):
            new_db = match.group(1)
            self.set_pool_config(database=new_db)
        return retval

    def cancel(self) -> None:
        # get a new cursor to execute the KILL statements
        conn, cur = self.safe_get_mysql_cursor()
        if conn is None or cur is None:
            return None

        # loop through in-use connections and kill each of them
        for connection_id in self._in_use_connections:
            try:
                cur.execute("KILL QUERY %s", (connection_id,))
            except BaseException:
                continue

        cur.close()
        conn.close()
        self._in_use_connections = set()

    def close(self) -> None:
        with suppress(PoolError):
            self._pool._remove_connections()

    def get_catalog(self) -> Catalog:
        databases = self._get_databases()
        db_items: list[CatalogItem] = [
            DatabaseCatalogItem.from_label(label=db, connection=self)
            for (db,) in databases
        ]
        return Catalog(items=db_items)

    def get_completions(self) -> list[HarlequinCompletion]:
        return load_completions()

    def _get_databases(self) -> list[tuple[str]]:
        conn, cur = self.safe_get_mysql_cursor(buffered=True)
        if conn is None or cur is None:
            raise HarlequinConnectionError(
                title="Connection pool exhausted",
                msg=(
                    "Connection pool exhausted. Try restarting Harlequin "
                    "with a larger pool or running fewer queries at once."
                ),
            )
        cur.execute(
            """
            show databases
            where `Database` not in (
                'sys', 'information_schema', 'performance_schema', 'mysql'
            )
            """
        )
        results: list[tuple[str]] = cur.fetchall()  # type: ignore
        cur.close()
        conn.close()
        return results

    def _get_relations(self, db_name: str) -> list[tuple[str, str]]:
        conn, cur = self.safe_get_mysql_cursor(buffered=True)
        if conn is None or cur is None:
            raise HarlequinConnectionError(
                title="Connection pool exhausted",
                msg=(
                    "Connection pool exhausted. Try restarting Harlequin "
                    "with a larger pool or running fewer queries at once."
                ),
            )
        cur.execute(
            f"""
            select 
                table_name, 
                table_type
            from information_schema.tables
            where table_schema = '{db_name}'
            and table_type != 'SYSTEM VIEW'
            order by table_name asc
            ;"""
        )
        results: list[tuple[str, str]] = cur.fetchall()  # type: ignore
        cur.close()
        conn.close()
        return results

    def _get_columns(self, db_name: str, rel_name: str) -> list[tuple[str, str]]:
        conn, cur = self.safe_get_mysql_cursor(buffered=True)
        if conn is None or cur is None:
            raise HarlequinConnectionError(
                title="Connection pool exhausted",
                msg=(
                    "Connection pool exhausted. Try restarting Harlequin "
                    "with a larger pool or running fewer queries at once."
                ),
            )
        cur.execute(
            f"""
            select column_name, data_type
            from information_schema.columns
            where
                table_schema = '{db_name}'
                and table_name = '{rel_name}'
                and extra not like '%INVISIBLE%'
            order by ordinal_position asc
            ;"""
        )
        results: list[tuple[str, str]] = cur.fetchall()  # type: ignore
        cur.close()
        conn.close()
        return results

    @staticmethod
    def _short_column_type(info_schema_type: str) -> str:
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
    IMPLEMENTS_CANCEL = True

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
        openid_token_file: str | None = None,
        pool_size: str | int | None = 5,
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
                "openid_token_file": openid_token_file,
                "pool_size": int(pool_size) if pool_size is not None else 5,
            }
        except (ValueError, TypeError) as e:
            raise HarlequinConfigError(
                msg=f"MySQL adapter received bad config value: {e}",
                title="Harlequin could not initialize the selected adapter.",
            ) from e

    @property
    def connection_id(self) -> str | None:
        host = self.options.get("host", "") or ""
        sock = self.options.get("unix_socket", "") or ""
        host = host if host or sock else "127.0.0.1"

        port = self.options.get("port", 3306)
        database = self.options.get("database", "") or ""

        return f"{host}{sock}:{port}/{database}"

    def connect(self) -> HarlequinMySQLConnection:
        conn = HarlequinMySQLConnection(conn_str=tuple(), options=self.options)
        return conn
