# harlequin-mysql

This repo provides the Harlequin adapter for MySQL/MariaDB.

## Installation

You must install the `harlequin-mysql` package into the same environment as `harlequin`. The best and easiest way to do this is to use `uv` to install Harlequin with the `mysql` extra:

```bash
uv tool install 'harlequin[mysql]'
```

## Usage and Configuration

You can open Harlequin with the MySQL/MariaDB adapter by selecting it with the `-a` option and passing connection parameters as CLI options:

```bash
harlequin -a mysql -h localhost -p 3306 -U root --password example --database dev
```

Note: use `-a mysql` for both MySQL and MariaDB servers.

The MySQL/MariaDB adapter does not accept a connection string or DSN.

### Read-only mode

This adapter supports Harlequin's `--read-only` option:

```bash
harlequin --read-only -a mysql -h localhost -U root --password example --database dev
```

Every connection runs `set session transaction read only`, so the server
refuses DML and DDL with error 1792 (tested on MySQL 8.0 and MariaDB 10.11).
Statements that do not touch data, like `set global ...`, are still allowed;
for a stronger guarantee, connect with a read-only account.

### Catalog search

This adapter supports Harlequin's `--catalog-search` option:

```bash
hsql --catalog-search customer_id -a mysql -h localhost -U root --password example
```

The term matches any part of a database, table, view, or column name,
case-insensitively; one query searches every database.

Many more options are available; to see the full list, run:

```bash
harlequin --help
```

For more information, see the [Harlequin Docs](https://harlequin.sh/docs/mysql/index).
