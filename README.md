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

The MySQL/MariaDB adapter supports Harlequin's `--read-only` option:

```bash
harlequin --read-only -a mysql -h localhost -U root --password example --database dev
```

The server does the enforcing: every connection Harlequin checks out of the
pool runs `set session transaction read only` first, so both DML and DDL are
refused with error 1792, `ER_CANT_EXECUTE_IN_READ_ONLY_TRANSACTION` (tested
against MySQL 8.0 and MariaDB 10.11).

Statements that do not touch table data are still allowed; a privileged
account can, for example, change server variables with `set global ...`. If you
need a stronger guarantee than "no writes to your data", connect with an
account that only has read privileges.

Many more options are available; to see the full list, run:

```bash
harlequin --help
```

For more information, see the [Harlequin Docs](https://harlequin.sh/docs/mysql/index).
