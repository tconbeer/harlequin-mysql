from __future__ import annotations

import sys

import pytest
from harlequin import (
    HarlequinAdapter,
    HarlequinCompletion,
    HarlequinConnection,
    HarlequinCursor,
)
from harlequin.catalog import Catalog, CatalogItem
from harlequin.exception import HarlequinConnectionError, HarlequinQueryError
from mysql.connector.cursor import MySQLCursor
from mysql.connector.pooling import PooledMySQLConnection
from textual_fastdatatable.backend import create_backend

from harlequin_mysql.adapter import (
    HarlequinMySQLAdapter,
    HarlequinMySQLConnection,
)

if sys.version_info < (3, 10):
    from importlib_metadata import entry_points
else:
    from importlib.metadata import entry_points


def test_plugin_discovery() -> None:
    PLUGIN_NAME = "mysql"
    eps = entry_points(group="harlequin.adapter")
    assert eps[PLUGIN_NAME]
    adapter_cls = eps[PLUGIN_NAME].load()
    assert issubclass(adapter_cls, HarlequinAdapter)
    assert adapter_cls == HarlequinMySQLAdapter


def test_connect() -> None:
    conn = HarlequinMySQLAdapter(
        conn_str=tuple(), user="root", password="example"
    ).connect()
    assert isinstance(conn, HarlequinConnection)


def test_init_extra_kwargs() -> None:
    assert HarlequinMySQLAdapter(
        conn_str=tuple(), user="root", password="example", foo=1, bar="baz"
    ).connect()


def test_connect_raises_connection_error() -> None:
    with pytest.raises(HarlequinConnectionError):
        _ = HarlequinMySQLAdapter(conn_str=("foo",)).connect()


@pytest.mark.parametrize(
    "options,expected",
    [
        ({}, "127.0.0.1:3306/"),
        ({"host": "foo.bar"}, "foo.bar:3306/"),
        ({"host": "foo.bar", "port": "3305"}, "foo.bar:3305/"),
        ({"unix_socket": "/foo/bar"}, "/foo/bar:3306/"),
        ({"unix_socket": "/foo/bar", "database": "baz"}, "/foo/bar:3306/baz"),
    ],
)
def test_connection_id(options: dict[str, str | int | None], expected: str) -> None:
    adapter = HarlequinMySQLAdapter(
        conn_str=tuple(),
        **options,  # type: ignore[arg-type]
    )
    assert adapter.connection_id == expected


def test_get_catalog(connection: HarlequinMySQLConnection) -> None:
    catalog = connection.get_catalog()
    assert isinstance(catalog, Catalog)
    assert catalog.items
    assert isinstance(catalog.items[0], CatalogItem)
    assert any(
        item.label == "test" and item.type_label == "db" for item in catalog.items
    )


def test_get_completions(connection: HarlequinMySQLConnection) -> None:
    completions = connection.get_completions()
    assert completions
    assert isinstance(completions[0], HarlequinCompletion)
    expected = ["action", "var_pop"]
    filtered = list(filter(lambda x: x.label in expected, completions))
    assert len(filtered) == len(expected)


def test_execute_ddl(connection: HarlequinMySQLConnection) -> None:
    cur = connection.execute("create table foo (a int)")
    assert cur is None


def test_execute_select(connection: HarlequinMySQLConnection) -> None:
    cur = connection.execute("select 1 as a")
    assert isinstance(cur, HarlequinCursor)
    assert cur.columns() == [("a", "##")]
    data = cur.fetchall()
    backend = create_backend(data)
    assert backend.column_count == 1
    assert backend.row_count == 1


def test_execute_select_no_records(connection: HarlequinMySQLConnection) -> None:
    cur = connection.execute("select 1 as a where false")
    assert isinstance(cur, HarlequinCursor)
    assert cur.columns() == [("a", "##")]
    data = cur.fetchall()
    backend = create_backend(data)
    assert backend.row_count == 0


def test_execute_select_dupe_cols(connection: HarlequinMySQLConnection) -> None:
    cur = connection.execute("select 1 as a, 2 as a, 3 as a")
    assert isinstance(cur, HarlequinCursor)
    assert len(cur.columns()) == 3
    data = cur.fetchall()
    backend = create_backend(data)
    assert backend.column_count == 3
    assert backend.row_count == 1


def test_set_limit(connection: HarlequinMySQLConnection) -> None:
    cur = connection.execute("select 1 as a union all select 2 union all select 3")
    assert isinstance(cur, HarlequinCursor)
    cur = cur.set_limit(2)
    assert isinstance(cur, HarlequinCursor)
    data = cur.fetchall()
    backend = create_backend(data)
    assert backend.column_count == 1
    assert backend.row_count == 2


def test_execute_raises_query_error(connection: HarlequinMySQLConnection) -> None:
    with pytest.raises(HarlequinQueryError):
        _ = connection.execute("selec;")


def test_can_execute_pool_size_queries(connection: HarlequinMySQLConnection) -> None:
    pool_size = connection._pool.pool_size
    cursors: list[HarlequinCursor] = []
    for _ in range(pool_size):
        cur = connection.execute("select 1")
        assert cur is not None
        cursors.append(cur)
    assert len(cursors) == pool_size


def test_can_execute_pool_size_ddl(connection: HarlequinMySQLConnection) -> None:
    pool_size = connection._pool.pool_size
    cursors: list[None] = []
    for i in range(pool_size):
        cur = connection.execute(f"create table t_{i} as select {i}")
        assert cur is None
        cursors.append(cur)
    assert len(cursors) == pool_size


def test_execute_more_than_pool_size_queries_does_not_raise(
    connection: HarlequinMySQLConnection,
) -> None:
    pool_size = connection._pool.pool_size
    cursors: list[HarlequinCursor] = []
    for _ in range(pool_size * 2):
        cur = connection.execute("select 1")
        if cur is not None:
            cursors.append(cur)
    assert len(cursors) == pool_size


def test_execute_more_than_pool_size_ddl_does_not_raise(
    connection: HarlequinMySQLConnection,
) -> None:
    pool_size = connection._pool.pool_size
    number_of_ddl_queries = pool_size * 2
    cursors: list[None] = []
    for i in range(number_of_ddl_queries):
        cur = connection.execute(f"create table t_{i} as select {i}")
        assert cur is None
        cursors.append(cur)
    assert len(cursors) == number_of_ddl_queries


def test_use_database_updates_pool(connection: HarlequinMySQLConnection) -> None:
    conn, cur = connection.safe_get_mysql_cursor()
    assert conn is not None
    assert cur is not None
    assert conn.database == "test"
    cur.close()
    conn.close()

    connection.execute("use mysql")

    pool_size = connection._pool.pool_size

    conns: list[PooledMySQLConnection] = []
    curs: list[MySQLCursor] = []
    for _ in range(pool_size):
        conn, cur = connection.safe_get_mysql_cursor()
        assert conn is not None
        assert cur is not None
        assert conn.database == "mysql"
        conns.append(conn)
        curs.append(cur)

    assert len(conns) == pool_size
    for cur in curs:
        cur.close()
    for conn in conns:
        conn.close()


def test_close(connection: HarlequinMySQLConnection) -> None:
    connection.close()
    # run again to test error handling.
    connection.close()
