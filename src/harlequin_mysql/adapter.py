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
from harlequin.catalog import (
    Catalog,
    CatalogItem,
    CatalogSearchKind,
    CatalogSearchResult,
)
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

from harlequin_mysql.catalog import (
    ColumnCatalogItem,
    DatabaseCatalogItem,
    RelationCatalogItem,
    relation_catalog_item,
)
from harlequin_mysql.cli_options import MYSQLADAPTER_OPTIONS
from harlequin_mysql.completions import load_completions

USE_DATABASE_PROG = re.compile(r"\s*use\s+\S", flags=re.IGNORECASE)
QUERY_INTERRUPT_MSG = "1317 (70100): Query execution was interrupted"
READ_ONLY_STMT = "set session transaction read only"

POOL_EXHAUSTED_MSG = (
    "Connection pool exhausted. Try restarting Harlequin "
    "with a larger pool or running fewer queries at once."
)

_SYSTEM_DATABASES = "'sys', 'information_schema', 'performance_schema', 'mysql'"
"""The databases the catalog does not show, as a list for an `in` predicate."""

_LIKE_ESCAPE = "!"
"""What escapes a LIKE metacharacter in a term the caller typed.

Not a backslash, whose meaning inside a string literal depends on the server's
sql_mode: with NO_BACKSLASH_ESCAPES set, `escape '\\\\'` is two characters and
the server rejects it.
"""

_SEARCH_DATABASES = f"""
select s.schema_name, null, null, null, null, null
from information_schema.schemata s
where s.schema_name not in ({_SYSTEM_DATABASES})
    and lower(s.schema_name) like lower(%s) escape '{_LIKE_ESCAPE}'
"""

_SEARCH_RELATIONS = f"""
select t.table_schema, t.table_name, t.table_type, null, null, null
from information_schema.tables t
where t.table_schema not in ({_SYSTEM_DATABASES})
    and t.table_type != 'SYSTEM VIEW'
    and lower(t.table_name) like lower(%s) escape '{_LIKE_ESCAPE}'
"""

_SEARCH_COLUMNS = f"""
select
    c.table_schema, c.table_name, t.table_type,
    c.column_name, c.data_type, c.column_type
from information_schema.columns c
join information_schema.tables t
    on t.table_schema = c.table_schema
    and t.table_name = c.table_name
where c.table_schema not in ({_SYSTEM_DATABASES})
    and t.table_type != 'SYSTEM VIEW'
    and c.extra not like '%%INVISIBLE%%'
    and lower(c.column_name) like lower(%s) escape '{_LIKE_ESCAPE}'
"""

_SEARCH_BRANCHES = {
    "relations": (_SEARCH_RELATIONS,),
    "columns": (_SEARCH_COLUMNS,),
    "all": (_SEARCH_DATABASES, _SEARCH_RELATIONS, _SEARCH_COLUMNS),
}
"""Which levels each kind unions, every branch in the same six columns.

A row names one item by filling in the levels above it and leaving the rest
null, so `all` is every level of the catalog rather than the two below a
database. `information_schema` is server-wide, so one query finds everything in
every database.

The predicates match what `_get_databases()`, `_get_relations()` and
`_get_columns()` ask for, so that a search and the catalog tree agree about
which objects exist. `%` is doubled because these queries are parameterized:
the connector interpolates the parameters with Python's own %-formatting.
"""

_SEARCH_SQL = {
    # MySQL sorts nulls first ascending, so an item arrives before its children
    kind: " union all ".join(branches) + " order by 1, 2, 4"
    for kind, branches in _SEARCH_BRANCHES.items()
}
"""One query per kind, ordered so that an item arrives before its children."""


def _contains_pattern(term: str) -> str:
    """A term as the LIKE pattern that matches any label containing it."""
    escaped = term
    for character in (_LIKE_ESCAPE, "%", "_"):
        escaped = escaped.replace(character, f"{_LIKE_ESCAPE}{character}")
    return f"%{escaped}%"


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

    def search_catalog(
        self, term: str, kind: CatalogSearchKind = "all"
    ) -> list[CatalogSearchResult]:
        conn, cur = self.safe_get_mysql_cursor(buffered=True)
        if conn is None or cur is None:
            raise HarlequinConnectionError(
                title="Connection pool exhausted",
                msg=POOL_EXHAUSTED_MSG,
            )
        try:
            cur.execute(
                _SEARCH_SQL[kind],
                [_contains_pattern(term)] * len(_SEARCH_BRANCHES[kind]),
            )
            # a row is (database, relation, relation_type, column, data_type,
            # column_type), null below the level it names
            found: list[tuple[Any, ...]] = cur.fetchall()
        except MySQLError as e:
            raise HarlequinQueryError(
                msg=str(e),
                title="MySQL raised an error searching the catalog:",
            ) from e
        finally:
            cur.close()
            conn.close()

        databases: dict[str, DatabaseCatalogItem] = {}
        relations: dict[tuple[str, str], RelationCatalogItem] = {}
        results: list[CatalogSearchResult] = []
        # a row names the deepest level it fills in, and carries its ancestors
        # so that each one is built once and the match knows its own path
        for database, relation, relation_type, column, data_type, column_type in found:
            database_item = databases.setdefault(
                database,
                DatabaseCatalogItem.from_label(label=database, connection=self),
            )
            if relation is None:
                results.append(CatalogSearchResult(item=database_item))
                continue
            relation_item = relations.setdefault(
                (database, relation),
                relation_catalog_item(
                    parent=database_item, label=relation, type_name=relation_type
                ),
            )
            if column is None:
                results.append(
                    CatalogSearchResult(item=relation_item, parents=(database,))
                )
                continue
            results.append(
                CatalogSearchResult(
                    item=ColumnCatalogItem.from_parent(
                        parent=relation_item,
                        label=column,
                        type_label=self._short_column_type(data_type),
                        type_name=column_type,
                    ),
                    parents=(database, relation),
                )
            )
        return results

    def get_completions(self) -> list[HarlequinCompletion]:
        return load_completions()

    def _get_databases(self) -> list[tuple[str]]:
        conn, cur = self.safe_get_mysql_cursor(buffered=True)
        if conn is None or cur is None:
            raise HarlequinConnectionError(
                title="Connection pool exhausted",
                msg=POOL_EXHAUSTED_MSG,
            )
        cur.execute(
            f"""
            show databases
            where `Database` not in ({_SYSTEM_DATABASES})
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
                msg=POOL_EXHAUSTED_MSG,
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

    def _get_columns(self, db_name: str, rel_name: str) -> list[tuple[str, str, str]]:
        conn, cur = self.safe_get_mysql_cursor(buffered=True)
        if conn is None or cur is None:
            raise HarlequinConnectionError(
                title="Connection pool exhausted",
                msg=POOL_EXHAUSTED_MSG,
            )
        cur.execute(
            f"""
            select column_name, data_type, column_type
            from information_schema.columns
            where
                table_schema = '{db_name}'
                and table_name = '{rel_name}'
                and extra not like '%INVISIBLE%'
            order by ordinal_position asc
            ;"""
        )
        results: list[tuple[str, str, str]] = cur.fetchall()  # type: ignore
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
    # information_schema is server-wide, so one query searches every database
    IMPLEMENTS_CATALOG_SEARCH = True
    # enforced by the server, with `set session transaction read only`
    IMPLEMENTS_READ_ONLY = True

    def __init__(
        self,
        conn_str: Sequence[str],
        read_only: bool = False,
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
        # Harlequin casts read_only to a bool before passing it here. It is
        # not a mysql-connector connection argument, so it is kept out of
        # self.options, which is passed to the connection pool.
        self.read_only = bool(read_only)
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
