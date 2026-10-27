from __future__ import annotations

from typing import Callable, Generator

import pytest
from harlequin.driver import HarlequinDriver
from mysql.connector import connect

from harlequin_mysql.adapter import HarlequinMySQLConnection
from harlequin_mysql.catalog import (
    ColumnCatalogItem,
    DatabaseCatalogItem,
    TableCatalogItem,
    ViewCatalogItem,
)
from harlequin_mysql.interactions import (
    execute_drop_database_statement,
    execute_drop_table_statement,
    execute_drop_view_statement,
    execute_use_statement,
    insert_columns_at_cursor,
    show_select_star,
)
from harlequin_mysql.quoting import qualified_identifier, quote_identifier

AWKWARD_NAMES = [
    "back`tick",
    'double"quote',
    "single'quote",
    "close]bracket",
    "back\\slash",
    "dot.ted",
    "with space",
    "MiXeD Case",
    "semi;colon",
]

DECOY_NAME = "decoy"
"""A table beside the awkward ones, which no interaction on them may touch."""


class RecordingDriver(HarlequinDriver):
    """Records what an interaction asks of Harlequin, confirming every prompt."""

    def __init__(self) -> None:
        self.inserted_text: list[str] = []
        self.notifications: list[tuple[str, str]] = []

    def insert_text_at_selection(self, text: str) -> None:
        self.inserted_text.append(text)

    def insert_text_in_new_buffer(self, text: str) -> None:
        self.inserted_text.append(text)

    def confirm_and_execute(
        self, callback: Callable[[], None], instructions: str = "Are you sure?"
    ) -> None:
        callback()

    def notify(self, message: str, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def refresh_catalog(self) -> None:
        pass


def _run_admin_statements(*statements: str) -> None:
    mysqlconn = connect(
        host="localhost", user="root", password="example", autocommit=True
    )
    cur = mysqlconn.cursor()
    for statement in statements:
        cur.execute(statement)
    cur.close()
    mysqlconn.close()


def _object_exists(database_name: str, object_name: str | None = None) -> bool:
    mysqlconn = connect(
        host="localhost", user="root", password="example", autocommit=True
    )
    cur = mysqlconn.cursor()
    if object_name is None:
        cur.execute(
            "select count(*) from information_schema.schemata where schema_name = %s",
            (database_name,),
        )
    else:
        cur.execute(
            "select count(*) from information_schema.tables "
            "where table_schema = %s and table_name = %s",
            (database_name, object_name),
        )
    [(object_count,)] = cur.fetchall()
    cur.close()
    mysqlconn.close()
    return object_count == 1


@pytest.fixture(params=AWKWARD_NAMES)
def awkward_name(request: pytest.FixtureRequest) -> str:
    awkward_name: str = request.param
    return awkward_name


@pytest.fixture
def awkward_database_name(awkward_name: str) -> Generator[str, None, None]:
    """A database, table, view and column all called the awkward name."""
    database_name = f"hq1209 {awkward_name}"
    database = quote_identifier(database_name)
    table = qualified_identifier(database_name, awkward_name)
    view = qualified_identifier(database_name, f"{awkward_name} view")
    column = quote_identifier(awkward_name)
    _run_admin_statements(
        f"drop database if exists {database}",
        f"create database {database}",
        f"create table {table} ({column} varchar(20))",
        f"insert into {table} values ('the right table')",
        f"create view {view} as select {column} from {table}",
        f"create table {qualified_identifier(database_name, DECOY_NAME)} (a int)",
    )
    yield database_name
    _run_admin_statements(f"drop database if exists {database}")


def _database_item(
    connection: HarlequinMySQLConnection, database_name: str
) -> DatabaseCatalogItem:
    [database_item] = [
        item for item in connection.get_catalog().items if item.label == database_name
    ]
    assert isinstance(database_item, DatabaseCatalogItem)
    return database_item


def _relation_items(
    connection: HarlequinMySQLConnection, database_name: str, awkward_name: str
) -> tuple[TableCatalogItem, ViewCatalogItem]:
    relation_items = {
        item.label: item
        for item in _database_item(connection, database_name).fetch_children()
    }
    assert set(relation_items) == {awkward_name, f"{awkward_name} view", DECOY_NAME}
    table_item = relation_items[awkward_name]
    view_item = relation_items[f"{awkward_name} view"]
    assert isinstance(table_item, TableCatalogItem)
    assert isinstance(view_item, ViewCatalogItem)
    return table_item, view_item


def _fetch_text(connection: HarlequinMySQLConnection, query: str) -> list[tuple]:
    cur = connection.execute(query)
    assert cur is not None
    rows: list[tuple] = cur.fetchall()  # type: ignore[assignment]
    return rows


def test_catalog_loads_awkward_names(
    connection: HarlequinMySQLConnection, awkward_database_name: str, awkward_name: str
) -> None:
    table_item, view_item = _relation_items(
        connection, awkward_database_name, awkward_name
    )

    for relation_item in (table_item, view_item):
        [column_item] = relation_item.fetch_children()
        assert isinstance(column_item, ColumnCatalogItem)
        assert column_item.label == awkward_name
        assert column_item.type_name == "varchar(20)"
        # the identifiers the catalog builds name the objects they came from
        assert _fetch_text(
            connection,
            f"select {column_item.qualified_identifier} "
            f"from {relation_item.qualified_identifier}",
        ) == [("the right table",)]


def test_search_catalog_finds_awkward_names(
    connection: HarlequinMySQLConnection, awkward_database_name: str, awkward_name: str
) -> None:
    results = connection.search_catalog(awkward_name, "relations")

    assert {
        (result.parents, result.item.label)
        for result in results
        if result.parents == (awkward_database_name,)
    } == {
        ((awkward_database_name,), awkward_name),
        ((awkward_database_name,), f"{awkward_name} view"),
    }


def test_use_statement(
    connection: HarlequinMySQLConnection, awkward_database_name: str
) -> None:
    driver = RecordingDriver()

    execute_use_statement(_database_item(connection, awkward_database_name), driver)

    assert _fetch_text(connection, "select database()") == [(awkward_database_name,)]
    assert driver.notifications == [
        (f"Editor context switched to {awkward_database_name}", "information")
    ]


def test_drop_database(
    connection: HarlequinMySQLConnection, awkward_database_name: str
) -> None:
    execute_drop_database_statement(
        _database_item(connection, awkward_database_name), RecordingDriver()
    )

    assert not _object_exists(awkward_database_name)
    assert _object_exists("test")


def test_drop_table(
    connection: HarlequinMySQLConnection, awkward_database_name: str, awkward_name: str
) -> None:
    table_item, _ = _relation_items(connection, awkward_database_name, awkward_name)

    execute_drop_table_statement(table_item, RecordingDriver())

    assert not _object_exists(awkward_database_name, awkward_name)
    assert _object_exists(awkward_database_name, DECOY_NAME)


def test_drop_view(
    connection: HarlequinMySQLConnection, awkward_database_name: str, awkward_name: str
) -> None:
    _, view_item = _relation_items(connection, awkward_database_name, awkward_name)

    execute_drop_view_statement(view_item, RecordingDriver())

    assert not _object_exists(awkward_database_name, f"{awkward_name} view")
    assert _object_exists(awkward_database_name, awkward_name)


def test_show_select_star(
    connection: HarlequinMySQLConnection, awkward_database_name: str, awkward_name: str
) -> None:
    table_item, _ = _relation_items(connection, awkward_database_name, awkward_name)
    driver = RecordingDriver()

    show_select_star(table_item, driver)

    [select_star] = driver.inserted_text
    assert _fetch_text(connection, select_star) == [("the right table",)]


def test_insert_columns_at_cursor(
    connection: HarlequinMySQLConnection, awkward_database_name: str, awkward_name: str
) -> None:
    table_item, _ = _relation_items(connection, awkward_database_name, awkward_name)
    driver = RecordingDriver()

    insert_columns_at_cursor(table_item, driver)

    [column_list] = driver.inserted_text
    assert _fetch_text(
        connection, f"select {column_list} from {table_item.qualified_identifier}"
    ) == [("the right table",)]
