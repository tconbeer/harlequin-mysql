from __future__ import annotations

from typing import Generator

import pytest
from mysql.connector import connect
from mysql.connector.abstracts import MySQLConnectionAbstract

from harlequin_mysql.quoting import (
    quote_identifier,
    quote_literal,
    quote_qualified_identifier,
)

AWKWARD_STRINGS = [
    "plain",
    "MiXeD Case",
    "with space",
    "back`tick",
    "``",
    'double"quote',
    "single'quote",
    "''",
    "close]bracket",
    "back\\slash",
    "trailing\\",
    "\\'",
    "dot.ted",
    "semi;colon",
    "per%cent_",
    "new\nline",
    "ünïcødé ☃",
]

SQL_MODES = [
    "",
    "NO_BACKSLASH_ESCAPES",
    "ANSI_QUOTES",
    "ANSI_QUOTES,NO_BACKSLASH_ESCAPES",
    "ANSI",
]


@pytest.mark.parametrize(
    "name,expected",
    [
        ("foo", "`foo`"),
        ("MiXeD", "`MiXeD`"),
        ("a b", "`a b`"),
        ("a`b", "`a``b`"),
        ('a"b', '`a"b`'),
        ("a'b", "`a'b`"),
        ("a\\b", "`a\\b`"),
        ("a.b", "`a.b`"),
        ("", "``"),
    ],
)
def test_quote_identifier(name: str, expected: str) -> None:
    assert quote_identifier(name) == expected


def test_quote_qualified_identifier() -> None:
    assert quote_qualified_identifier("a.b", "c`d") == "`a.b`.`c``d`"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("foo", "'foo'"),
        ("", "''"),
        ("it's", "'it''s'"),
        ('a"b', "'a\"b'"),
        ("a`b", "'a`b'"),
        ("a\\b", "_utf8mb4 X'615C62'"),
        ("\\'", "_utf8mb4 X'5C27'"),
    ],
)
def test_quote_literal(value: str, expected: str) -> None:
    assert quote_literal(value) == expected


@pytest.fixture(params=SQL_MODES)
def mysql_connection_in_mode(
    request: pytest.FixtureRequest,
) -> Generator[MySQLConnectionAbstract, None, None]:
    mysqlconn = connect(
        host="localhost",
        user="root",
        password="example",
        autocommit=True,
        charset="utf8mb4",
    )
    assert isinstance(mysqlconn, MySQLConnectionAbstract)
    cur = mysqlconn.cursor()
    cur.execute("set session sql_mode = %s", (request.param,))
    cur.close()
    yield mysqlconn
    mysqlconn.close()


def test_quoted_sql_means_the_same_under_every_sql_mode(
    mysql_connection_in_mode: MySQLConnectionAbstract,
) -> None:
    cur = mysql_connection_in_mode.cursor()
    for value in AWKWARD_STRINGS:
        # the column alias is the identifier, and the value is the literal
        cur.execute(f"select {quote_literal(value)} as {quote_identifier(value)}")
        assert cur.fetchall() == [(value,)], value
        assert cur.description is not None
        assert cur.description[0][0] == value
    cur.close()
