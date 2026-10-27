"""Quoting for SQL text that cannot take a bound parameter."""

from __future__ import annotations


def quote_identifier(name: str) -> str:
    """A name as a MySQL identifier: in backticks, with each backtick doubled.

    Backticks quote an identifier under every sql_mode, including ANSI_QUOTES,
    and nothing else is special inside them.
    """
    return "`" + name.replace("`", "``") + "`"


def quote_qualified_identifier(*names: str) -> str:
    """Names joined into one dotted identifier, each quoted on its own."""
    return ".".join(quote_identifier(name) for name in names)


def quote_literal(value: str) -> str:
    """A string as a MySQL literal that means the same under every sql_mode.

    A backslash is an escape unless NO_BACKSLASH_ESCAPES is set, so no spelling
    of one inside quotes is right under both; a value holding one is written as
    a utf8mb4 hex literal instead. ANSI_QUOTES makes `"` quote identifiers, so
    the quote is always `'`, and a doubled `'` means one under every mode.
    """
    if "\\" in value:
        return f"_utf8mb4 X'{value.encode('utf-8').hex().upper()}'"
    return "'" + value.replace("'", "''") + "'"
