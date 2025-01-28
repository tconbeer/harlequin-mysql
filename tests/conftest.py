from __future__ import annotations

from typing import Generator

import pytest
from mysql.connector import connect

from harlequin_mysql.adapter import (
    HarlequinMySQLAdapter,
    HarlequinMySQLConnection,
)


@pytest.fixture
def connection() -> Generator[HarlequinMySQLConnection, None, None]:
    mysqlconn = connect(
        host="localhost",
        user="root",
        password="example",
        database="mysql",
        autocommit=True,
    )
    cur = mysqlconn.cursor()
    cur.execute("drop database if exists test;")
    cur.execute("drop database if exists one;")
    cur.execute("drop database if exists two;")
    cur.execute("drop database if exists three;")
    cur.execute("create database test;")
    cur.close()
    conn = HarlequinMySQLAdapter(
        conn_str=tuple(),
        host="localhost",
        user="root",
        password="example",
        database="test",
    ).connect()
    yield conn
    cur = mysqlconn.cursor()
    cur.execute("drop database if exists test;")
    cur.execute("drop database if exists one;")
    cur.execute("drop database if exists two;")
    cur.execute("drop database if exists three;")
    cur.close()
