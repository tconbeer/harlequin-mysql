# harlequin-mysql CHANGELOG

All notable changes to this project will be documented in this file.

## [Unreleased]

## [1.1.0] - 2025-01-28

-   Bumps the MySQL Connector Python version to >=9.1
-   Bumps the required Harlequin version to >= 1.25.0
-   Adds support for the `openid_token_file` connection option introduced with MySQL Connector 9.1
-   This adapter now lazy-loads the catalog, which will dramatically improve the catalog performance for large databases with thousands of objects.
-   This adapter now implements interactions for catalog items, like dropping tables, inserting columns at the cursor, etc.

## [1.0.0] - 2025-01-07

-   Drops support for Python 3.8
-   Adds support for Python 3.13
-   Adds support for Harlequin 2.X

## [0.3.0] - 2024-08-20

-   Implements `connection_id` for better persistence.
-   Implements the `cancel()` protocol to cancel in-flight queries.
-   Implements `close()`
-   Fixes a bug where a race condition could cause a crash with an `AssertionError` ([#14](https://github.com/tconbeer/harlequin-mysql/issues/14) - thank you [@blasferna](https://github.com/blasferna)!).

## [0.2.0] - 2024-04-11

### Features

-   Adds a `pool-size` CLI option to set the size of the MySQL connection pool. Defaults to 5.

### Bug Fixes

-   Updates the connection pool config to keep all connections in sync after running a `use database` command ([#11](https://github.com/tconbeer/harlequin-mysql/issues/11) - thank you [@mlopezgva](https://github.com/mlopezgva)!).
-   Handles several issues caused by running too many concurrent queries and not fetching results.

## [0.1.3] - 2024-01-29

### Fixes

-   Fixes a typo in the help text for the `--user` option (thank you [@alexmalins](https://github.com/alexmalins)!).

## [0.1.2] - 2024-01-25

### Fixes

-   Sets the `pool_name` property on the MySQL connection to prevent auto-generated pool names from being too long ([#6](https://github.com/tconbeer/harlequin-mysql/issues/6) - thank you [sondeokhyeon](https://github.com/sondeokhyeon)!).

## [0.1.1] - 2024-01-09

### Fixes

-   Sorts relation names alphabetically and columns by ordinal position.

## [0.1.0] - 2023-12-14

### Features

-   Adds a basic MySQL adapter with most common connection options.

[Unreleased]: https://github.com/tconbeer/harlequin-mysql/compare/1.1.0...HEAD

[1.1.0]: https://github.com/tconbeer/harlequin-mysql/compare/1.0.0...1.1.0

[1.0.0]: https://github.com/tconbeer/harlequin-mysql/compare/0.3.0...1.0.0

[0.3.0]: https://github.com/tconbeer/harlequin-mysql/compare/0.2.0...0.3.0

[0.2.0]: https://github.com/tconbeer/harlequin-mysql/compare/0.1.3...0.2.0

[0.1.3]: https://github.com/tconbeer/harlequin-mysql/compare/0.1.2...0.1.3

[0.1.2]: https://github.com/tconbeer/harlequin-mysql/compare/0.1.1...0.1.2

[0.1.1]: https://github.com/tconbeer/harlequin-mysql/compare/0.1.0...0.1.1

[0.1.0]: https://github.com/tconbeer/harlequin-mysql/compare/f2caef7de11e68bb2b9798fb597c3fc05044b71e...0.1.0
