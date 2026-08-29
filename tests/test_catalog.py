import pytest
from harlequin.catalog import CatalogSearchKind, CatalogSearchResult

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


@pytest.fixture
def connection_with_typed_objects(
    connection: HarlequinMySQLConnection,
) -> HarlequinMySQLConnection:
    connection.execute("create database one")
    connection.execute(
        "create table one.customers ("
        "    customer_id int,"
        "    amount decimal(18, 2),"
        "    name varchar(20),"
        "    customerxid int,"
        "    secret int invisible"
        ")"
    )
    connection.execute("create database two")
    connection.execute("create view two.customers_v as select * from one.customers")
    # the original connection fixture will clean this up.
    return connection


def _result(
    results: list[CatalogSearchResult],
    label: str,
    parents: tuple[str, ...] | None = None,
) -> CatalogSearchResult | None:
    """The one result for an item, identified by its label and its path."""
    matches = [
        result
        for result in results
        if result.item.label == label and (parents is None or result.parents == parents)
    ]
    assert len(matches) <= 1, f"{label} matched more than once"
    return matches[0] if matches else None


def test_catalog_type_names(
    connection_with_typed_objects: HarlequinMySQLConnection,
) -> None:
    conn = connection_with_typed_objects

    database_items = conn.get_catalog().items
    [database_one_item] = filter(lambda item: item.label == "one", database_items)
    assert database_one_item.type_name == "database"

    assert isinstance(database_one_item, DatabaseCatalogItem)
    [table_item] = database_one_item.fetch_children()
    assert table_item.type_name == "BASE TABLE"

    column_items = table_item.fetch_children()
    # the full type, not the shortened type_label, and not the invisible column
    assert [(item.label, item.type_label, item.type_name) for item in column_items] == [
        ("customer_id", "##", "int"),
        ("amount", "#.#", "decimal(18,2)"),
        ("name", "s", "varchar(20)"),
        ("customerxid", "##", "int"),
    ]

    [database_two_item] = filter(lambda item: item.label == "two", database_items)
    assert isinstance(database_two_item, DatabaseCatalogItem)
    [view_item] = database_two_item.fetch_children()
    assert view_item.type_name == "VIEW"


def test_search_catalog_finds_every_level(
    connection_with_typed_objects: HarlequinMySQLConnection,
) -> None:
    conn = connection_with_typed_objects

    results = conn.search_catalog("customer")

    # the database "one" does not contain the term, but its relation and
    # columns do
    assert _result(results, "one") is None

    table_result = _result(results, "customers")
    assert table_result is not None
    assert isinstance(table_result.item, TableCatalogItem)
    assert table_result.parents == ("one",)
    assert table_result.item.type_name == "BASE TABLE"

    view_result = _result(results, "customers_v")
    assert view_result is not None
    assert isinstance(view_result.item, ViewCatalogItem)
    assert view_result.parents == ("two",)

    column_result = _result(results, "customer_id", ("one", "customers"))
    assert column_result is not None
    assert isinstance(column_result.item, ColumnCatalogItem)
    assert column_result.item.type_label == "##"
    assert column_result.item.type_name == "int"

    # the same column of the view is its own result, under its own path
    assert _result(results, "customer_id", ("two", "customers_v")) is not None


def test_search_catalog_matches_databases(
    connection_with_typed_objects: HarlequinMySQLConnection,
) -> None:
    conn = connection_with_typed_objects

    results = conn.search_catalog("ne")

    database_result = _result(results, "one")
    assert database_result is not None
    assert isinstance(database_result.item, DatabaseCatalogItem)
    assert database_result.parents == ()
    assert database_result.item.type_name == "database"
    assert database_result.item.query_name == "`one`"


def test_search_catalog_builds_the_items_the_catalog_shows(
    connection_with_typed_objects: HarlequinMySQLConnection,
) -> None:
    conn = connection_with_typed_objects

    database_items = conn.get_catalog().items
    [database_one_item] = filter(lambda item: item.label == "one", database_items)
    assert isinstance(database_one_item, DatabaseCatalogItem)
    [table_item] = database_one_item.fetch_children()
    [column_item, *_] = table_item.fetch_children()

    table_result = _result(
        conn.search_catalog("customers", "relations"), "customers", ("one",)
    )
    assert table_result is not None
    assert table_result.item == table_item

    column_result = _result(
        conn.search_catalog("customer_id", "columns"),
        "customer_id",
        ("one", "customers"),
    )
    assert column_result is not None
    assert column_result.item == column_item


@pytest.mark.parametrize("term", ["CUSTOMERS", "Customers", "customers"])
def test_search_catalog_is_case_insensitive(
    connection_with_typed_objects: HarlequinMySQLConnection, term: str
) -> None:
    conn = connection_with_typed_objects

    results = conn.search_catalog(term, "relations")

    assert [result.item.label for result in results] == ["customers", "customers_v"]


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("relations", ["customers", "customers_v"]),
        ("columns", ["customer_id", "customerxid", "customer_id", "customerxid"]),
        (
            "all",
            [
                "customers",
                "customer_id",
                "customerxid",
                "customers_v",
                "customer_id",
                "customerxid",
            ],
        ),
    ],
)
def test_search_catalog_kinds(
    connection_with_typed_objects: HarlequinMySQLConnection,
    kind: CatalogSearchKind,
    expected: list[str],
) -> None:
    conn = connection_with_typed_objects

    results = conn.search_catalog("customer", kind)

    # a parent arrives before its own children
    assert [result.item.label for result in results] == expected


def test_search_catalog_escapes_like_metacharacters(
    connection_with_typed_objects: HarlequinMySQLConnection,
) -> None:
    conn = connection_with_typed_objects

    # the underscore is a character to match, not a wildcard
    results = conn.search_catalog("customer_id", "columns")
    assert {result.item.label for result in results} == {"customer_id"}

    assert conn.search_catalog("%", "all") == []
    assert conn.search_catalog("!", "all") == []
    assert conn.search_catalog("\\", "all") == []


def test_search_catalog_excludes_system_databases(
    connection_with_typed_objects: HarlequinMySQLConnection,
) -> None:
    conn = connection_with_typed_objects

    # information_schema.tables and mysql.user exist, but the catalog does not
    # show the databases that hold them
    results = conn.search_catalog("user")

    assert all(result.parents[:1] != ("mysql",) for result in results)
    assert _result(results, "mysql") is None
    assert _result(results, "information_schema") is None


def test_search_catalog_excludes_invisible_columns(
    connection_with_typed_objects: HarlequinMySQLConnection,
) -> None:
    conn = connection_with_typed_objects

    assert conn.search_catalog("secret", "columns") == []


def test_search_catalog_no_matches(
    connection_with_typed_objects: HarlequinMySQLConnection,
) -> None:
    conn = connection_with_typed_objects

    assert conn.search_catalog("no_such_object_anywhere") == []


def test_search_catalog_returns_its_connection_to_the_pool(
    connection_with_typed_objects: HarlequinMySQLConnection,
) -> None:
    conn = connection_with_typed_objects

    for _ in range(conn._pool.pool_size * 2):
        assert conn.search_catalog("customers", "relations")
