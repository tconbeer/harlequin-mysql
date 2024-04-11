# harlequin-mysql CHANGELOG

All notable changes to this project will be documented in this file.

## [Unreleased]

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

[Unreleased]: https://github.com/tconbeer/harlequin-mysql/compare/0.2.0...HEAD

[0.2.0]: https://github.com/tconbeer/harlequin-mysql/compare/0.1.3...0.2.0

[0.1.3]: https://github.com/tconbeer/harlequin-mysql/compare/0.1.2...0.1.3

[0.1.2]: https://github.com/tconbeer/harlequin-mysql/compare/0.1.1...0.1.2

[0.1.1]: https://github.com/tconbeer/harlequin-mysql/compare/0.1.0...0.1.1

[0.1.0]: https://github.com/tconbeer/harlequin-mysql/compare/f2caef7de11e68bb2b9798fb597c3fc05044b71e...0.1.0
