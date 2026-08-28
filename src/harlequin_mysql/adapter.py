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
from mysql.connector.constants import ClientFlag
from mysql.connector.cursor import MySQLCursor
from mysql.connector.errors import Error as MySQLError
from mysql.connector.errors import InternalError, PoolError
from mysql.connector.pooling import (
    MySQLConnectionPool,
    PooledMySQLConnection,
)
from textual_fastdatatable.backend import AutoBackendType

from harlequin_mysql.catalog import DatabaseCatalogItem
from harlequin_mysql.cli_options import MYSQLADAPTER_OPTIONS
from harlequin_mysql.completions import load_completions

USE_DATABASE_PROG = re.compile(r"\s*use\s+\S", flags=re.IGNORECASE)
QUERY_INTERRUPT_MSG = "1317 (70100): Query execution was interrupted"
READ_ONLY_STMT = "set session transaction read only"

TRUTHY_STRINGS = ("true", "t", "yes", "y", "on", "1")
FALSEY_STRINGS = ("false", "f", "no", "n", "off", "0", "")


def _parse_read_only(read_only: bool | str | None) -> bool:
    """
    Harlequin passes read_only as a bool, but a config file could set it to a
    string. An unrecognized value is an error, since silently guessing wrong
    could let writes through a session the user believes is read-only.
    """
    if read_only is None:
        return False
    if isinstance(read_only, bool):
        return read_only
    if isinstance(read_only, str):
        if read_only.strip().lower() in TRUTHY_STRINGS:
            return True
        if read_only.strip().lower() in FALSEY_STRINGS:
            return False
    raise HarlequinConfigError(
        msg=f"MySQL adapter could not interpret read_only value: {read_only!r}",
        title="Harlequin could not initialize the selected adapter.",
    )


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
        read_only: bool = False,
    ) -> None:
        self.init_message = init_message
        self.read_only = read_only
        self._in_use_connections: set[int] = set()
        if read_only:
            # the server only refuses the writes it is asked to make, one
            # statement at a time; a single execute() that sends
            # "set session transaction read write; insert ..." would slip a
            # write past it. Harlequin splits its buffers into single
            # statements, so nothing legitimate needs multiple statements
            # per execute().
            options = {**options, "client_flags": [-ClientFlag.MULTI_STATEMENTS]}
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
        except MySQLError as e:
            # the pool reconfigures and reconnects its connections lazily, so
            # a bad config (e.g., a database that has since been dropped) shows
            # up here. Raise a query error so Harlequin shows the message
            # instead of crashing.
            raise HarlequinQueryError(
                msg=str(e),
                title="Harlequin could not connect to your database.",
            ) from e

        try:
            cur: MySQLCursor = conn.cursor(buffered=buffered)
        except InternalError:
            # cursor has an unread result. Try to consume the results,
            # and try again.
            conn.consume_results()
            cur = conn.cursor(buffered=buffered)

        if self.read_only:
            self._set_session_read_only(conn, cur)

        return conn, cur

    def _set_session_read_only(
        self, conn: PooledMySQLConnection, cur: MySQLCursor
    ) -> None:
        """
        Asks the server to refuse writes (both DML and DDL) on this connection,
        with error 1792, ER_CANT_EXECUTE_IN_READ_ONLY_TRANSACTION.

        The pool creates its connections lazily and does not reset their
        sessions, so this has to run every time a connection is checked out,
        not just once per connection: that covers every connection the pool
        hands out, and undoes a `set session transaction read write` from an
        earlier query. The setting only applies to the next transaction, so a
        transaction left open by an earlier query is rolled back first; that
        cannot lose any work, since it could not have written anything.
        """
        try:
            if conn.in_transaction:
                conn.rollback()
            cur.execute(READ_ONLY_STMT)
        except MySQLError as e:
            # never hand back a connection that may accept writes
            with suppress(MySQLError):
                cur.close()
                conn.close()
            raise HarlequinQueryError(
                msg=str(e),
                title="Harlequin could not put your connection in read-only mode.",
            ) from e

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
                if USE_DATABASE_PROG.match(query):
                    self._sync_pool_database(conn)
                conn.close()
                if connection_id:
                    self._in_use_connections.discard(connection_id)

        return retval

    def _sync_pool_database(self, conn: PooledMySQLConnection) -> None:
        """
        This is a hack to update all connections in the pool if the user
        changes the database for the active connection.
        It is impossible to check the database or other config
        of a connection with an open cursor, and we can't use a dedicated
        connection for user queries, since mysql only supports a single
        (unfetched) cursor per connection.

        The active database is read back from the server, since parsing it out
        of the query is error-prone (the query may end with a semicolon, the
        name may be quoted, etc.).
        """
        with suppress(MySQLError):
            if new_db := conn.database:
                self.set_pool_config(database=new_db)

    def cancel(self) -> None:
        # get a new cursor to execute the KILL statements
        try:
            conn, cur = self.safe_get_mysql_cursor()
        except HarlequinQueryError:
            return None
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
    # enforced by the server, with `set session transaction read only`
    IMPLEMENTS_READ_ONLY = True

    def __init__(
        self,
        conn_str: Sequence[str],
        read_only: bool | str | None = False,
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
        enable_cleartext_plugin: str | bool | None = False,
        **_: Any,
    ) -> None:
        if conn_str:
            raise HarlequinConnectionError(
                f"Cannot provide a DSN to the MySQL adapter. Got:\n{conn_str}"
            )
        # read_only is not a mysql-connector connection argument, so it is kept
        # out of self.options, which is passed to the connection pool.
        self.read_only = _parse_read_only(read_only)
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
                "allow_local_infile": enable_cleartext_plugin
                if enable_cleartext_plugin is not None
                else False,
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
        conn = HarlequinMySQLConnection(
            conn_str=tuple(), options=self.options, read_only=self.read_only
        )
        return conn
