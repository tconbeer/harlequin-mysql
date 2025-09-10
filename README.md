# harlequin-mysql

This repo provides the Harlequin adapter for MySQL/MariaDB.

## Installation

`harlequin-mysql` depends on `harlequin`, so installing this package will also install Harlequin.

### Using pip

To install this adapter into an activated virtual environment:
```bash
pip install harlequin-mysql
```

### Using poetry

```bash
poetry add harlequin-mysql
```

### Using pipx

If you do not already have Harlequin installed:

```bash
pip install harlequin-mysql
```

If you would like to add the Postgres adapter to an existing Harlequin installation:

```bash
pipx inject harlequin harlequin-mysql
```

### As an Extra
Alternatively, you can install Harlequin with the `mysql` extra:

```bash
pip install harlequin[mysql]
```

```bash
poetry add harlequin[mysql]
```

```bash
pipx install harlequin[mysql]
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