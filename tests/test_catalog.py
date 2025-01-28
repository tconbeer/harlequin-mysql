import pytest

from harlequin_mysql.adapter import HarlequinMySQLConnection
from harlequin_mysql.catalog import (
    ColumnCatalogItem,
    DatabaseCatalogItem,
    RelationCatalogItem,
    TableCatalogItem,
    ViewCatalogItem,
)


@pytest.fixture
def connection_with_objects(
    connection: HarlequinMySQLConnection,
) -> HarlequinMySQLConnection:
    connection.execute("create database one")
    connection.execute("create table one.foo as select 1 as a, '2' as b")
    connection.execute("create table one.bar as select 1 as a, '2' as b")
    connection.execute("create table one.baz as select 1 as a, '2' as b")
    connection.execute("create database two")
    connection.execute("create view two.qux as select * from one.foo")
    connection.execute("create database three")
    # the original connection fixture will clean this up.
    return connection


def test_catalog(connection_with_objects: HarlequinMySQLConnection) -> None:
    conn = connection_with_objects

    catalog = conn.get_catalog()

    # five databases: dev, test, one, two, and three.
    assert len(catalog.items) == 5

    database_items = catalog.items
    assert all(isinstance(item, DatabaseCatalogItem) for item in database_items)

    [database_one_item] = filter(lambda item: item.label == "one", database_items)
    assert isinstance(database_one_item, DatabaseCatalogItem)
    assert not database_one_item.children
    assert not database_one_item.loaded

    table_items = database_one_item.fetch_children()
    assert all(isinstance(item, RelationCatalogItem) for item in table_items)

    [foo_item] = filter(lambda item: item.label == "foo", table_items)
    assert isinstance(foo_item, TableCatalogItem)
    assert not foo_item.children
    assert not foo_item.loaded

    foo_column_items = foo_item.fetch_children()
    assert all(isinstance(item, ColumnCatalogItem) for item in foo_column_items)

    [database_two_item] = filter(lambda item: item.label == "two", database_items)
    assert isinstance(database_two_item, DatabaseCatalogItem)
    assert not database_two_item.children
    assert not database_two_item.loaded

    view_items = database_two_item.fetch_children()
    assert all(isinstance(item, ViewCatalogItem) for item in view_items)

    [qux_item] = filter(lambda item: item.label == "qux", view_items)
    assert isinstance(qux_item, ViewCatalogItem)
    assert not qux_item.children
    assert not qux_item.loaded

    qux_column_items = qux_item.fetch_children()
    assert all(isinstance(item, ColumnCatalogItem) for item in qux_column_items)

    assert [item.label for item in foo_column_items] == [
        item.label for item in qux_column_items
    ]

    # ensure calling fetch_children on cols doesn't raise
    children_items = foo_column_items[0].fetch_children()
    assert not children_items

    [database_three_item] = filter(lambda item: item.label == "three", database_items)
    assert isinstance(database_three_item, DatabaseCatalogItem)
    assert not database_three_item.children
    assert not database_three_item.loaded

    three_children = database_three_item.fetch_children()
    assert not three_children
