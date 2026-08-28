from __future__ import annotations

from importlib.metadata import entry_points

import pytest
from harlequin import (
    HarlequinAdapter,
    HarlequinCompletion,
    HarlequinConnection,
    HarlequinCursor,
)
from harlequin.catalog import Catalog, CatalogItem
from harlequin.exception import (
    HarlequinConfigError,
    HarlequinConnectionError,
    HarlequinQueryError,
)
from mysql.connector.cursor import MySQLCursor
from mysql.connector.pooling import PooledMySQLConnection
from textual_fastdatatable.backend import create_backend

from harlequin_mysql.adapter import (
    HarlequinMySQLAdapter,
    HarlequinMySQLConnection,
)


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


def test_enable_cleartext_plugin_default() -> None:
    adapter = HarlequinMySQLAdapter(conn_str=tuple(), user="root", password="example")
    assert adapter.options["allow_local_infile"] is False


def test_enable_cleartext_plugin_true() -> None:
    adapter = HarlequinMySQLAdapter(
        conn_str=tuple(), user="root", password="example", enable_cleartext_plugin=True
    )
    assert adapter.options["allow_local_infile"] is True


def test_enable_cleartext_plugin_false() -> None:
    adapter = HarlequinMySQLAdapter(
        conn_str=tuple(), user="root", password="example", enable_cleartext_plugin=False
    )
    assert adapter.options["allow_local_infile"] is False


def test_enable_cleartext_plugin_string_true() -> None:
    adapter = HarlequinMySQLAdapter(
        conn_str=tuple(),
        user="root",
        password="example",
        enable_cleartext_plugin="true",
    )
    assert adapter.options["allow_local_infile"] == "true"


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


@pytest.mark.parametrize(
    "query",
    [
        "use mysql",
        "use mysql;",
        "USE mysql;\n\n",
        "use `mysql`;",
        "  use\n  mysql  ;  ",
    ],
)
def test_use_database_updates_pool(
    connection: HarlequinMySQLConnection, query: str
) -> None:
    conn, cur = connection.safe_get_mysql_cursor()
    assert conn is not None
    assert cur is not None
    assert conn.database == "test"
    cur.close()
    conn.close()

    connection.execute(query)

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


def test_use_database_script(connection: HarlequinMySQLConnection) -> None:
    """
    A script that starts with a USE statement should execute against the
    named database. See harlequin#982.
    """
    for query in [
        "use test;",
        "create table temp1 (\n    id int\n);",
        "insert into temp1 values (1);",
    ]:
        assert connection.execute(query) is None

    cur = connection.execute("select id from test.temp1")
    assert cur is not None
    assert cur.fetchall() == [(1,)]


def test_close(connection: HarlequinMySQLConnection) -> None:
    connection.close()
    # run again to test error handling.
    connection.close()


def test_implements_read_only() -> None:
    assert HarlequinMySQLAdapter.IMPLEMENTS_READ_ONLY is True


@pytest.mark.parametrize(
    "value,expected",
    [
        (False, False),
        (True, True),
        (None, False),
        ("true", True),
        ("True", True),
        ("false", False),
        ("1", True),
        ("0", False),
    ],
)
def test_read_only_option(value: bool | str | None, expected: bool) -> None:
    adapter = HarlequinMySQLAdapter(
        conn_str=tuple(), read_only=value, user="root", password="example"
    )
    assert adapter.read_only is expected
    # read_only is not a connection arg; it must not reach the pool.
    assert "read_only" not in adapter.options


def test_read_only_default() -> None:
    adapter = HarlequinMySQLAdapter(conn_str=tuple(), user="root", password="example")
    assert adapter.read_only is False
    assert "read_only" not in adapter.options


def test_read_only_bad_value_raises_config_error() -> None:
    with pytest.raises(HarlequinConfigError):
        _ = HarlequinMySQLAdapter(
            conn_str=tuple(), read_only="maybe", user="root", password="example"
        )


def test_read_only_connection_can_read(
    read_only_connection: HarlequinMySQLConnection,
) -> None:
    cur = read_only_connection.execute("select a from foo")
    assert cur is not None
    assert cur.fetchall() == [(1,)]


def test_read_only_connection_can_get_catalog(
    read_only_connection: HarlequinMySQLConnection,
) -> None:
    catalog = read_only_connection.get_catalog()
    assert any(item.label == "test_read_only" for item in catalog.items)


@pytest.mark.parametrize(
    "query",
    [
        "insert into foo values (2)",
        "update foo set a = 2",
        "delete from foo",
        "truncate table foo",
        "create table bar (a int)",
        "create temporary table bar (a int)",
        "drop table foo",
        "alter table foo add column b int",
        "create index foo_idx on foo (a)",
        "rename table foo to baz",
        "create view v as select a from foo",
        "create database test_read_only_new",
    ],
)
def test_read_only_connection_refuses_writes(
    read_only_connection: HarlequinMySQLConnection, query: str
) -> None:
    with pytest.raises(HarlequinQueryError):
        _ = read_only_connection.execute(query)

    cur = read_only_connection.execute("select a from foo")
    assert cur is not None
    assert cur.fetchall() == [(1,)]


def test_read_only_applies_to_every_pooled_connection(
    read_only_connection: HarlequinMySQLConnection,
) -> None:
    """
    The pool creates connections lazily and does not reset their sessions, so
    check that more connections than the pool holds all refuse writes.
    """
    for _ in range(read_only_connection._pool.pool_size * 2):
        with pytest.raises(HarlequinQueryError):
            _ = read_only_connection.execute("insert into foo values (2)")


def test_read_only_survives_set_transaction_read_write(
    read_only_connection: HarlequinMySQLConnection,
) -> None:
    # this statement is not itself a write, so the server allows it, but the
    # next statement gets a read-only session again.
    _ = read_only_connection.execute("set session transaction read write")
    with pytest.raises(HarlequinQueryError):
        _ = read_only_connection.execute("insert into foo values (2)")


def test_read_only_connection_refuses_multiple_statements(
    read_only_connection: HarlequinMySQLConnection,
) -> None:
    with pytest.raises(HarlequinQueryError):
        _ = read_only_connection.execute(
            "set session transaction read write; insert into foo values (2)"
        )


def test_read_only_connection_leaves_no_open_transaction(
    read_only_connection: HarlequinMySQLConnection,
) -> None:
    _ = read_only_connection.execute("start transaction")
    with pytest.raises(HarlequinQueryError):
        _ = read_only_connection.execute("insert into foo values (2)")


def test_writes_still_work_without_read_only(
    connection: HarlequinMySQLConnection,
) -> None:
    assert connection.read_only is False
    assert connection.execute("create table rw (a int)") is None
    assert connection.execute("insert into rw values (1)") is None
