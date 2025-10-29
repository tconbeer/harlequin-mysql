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

Many more options are available; to see the full list, run:

```bash
harlequin --help
```

For more information, see the [Harlequin Docs](https://harlequin.sh/docs/mysql/index).
