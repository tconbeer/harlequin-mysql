# harlequin-mysql CHANGELOG

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixes

-   Sets the `pool_name` property on the MySQL connection to prevent auto-generated pool names from being too long ([#6](https://github.com/tconbeer/harlequin-mysql/issues/6) - thank you [sondeokhyeon](https://github.com/sondeokhyeon)!).

## [0.1.1] - 2024-01-09

### Fixes

-   Sorts relation names alphabetically and columns by ordinal position.

## [0.1.0] - 2023-12-14

### Features

-   Adds a basic MySQL adapter with most common connection options.

[Unreleased]: https://github.com/tconbeer/harlequin-mysql/compare/0.1.1...HEAD

[0.1.1]: https://github.com/tconbeer/harlequin-mysql/compare/0.1.0...0.1.1

[0.1.0]: https://github.com/tconbeer/harlequin-mysql/compare/f2caef7de11e68bb2b9798fb597c3fc05044b71e...0.1.0
