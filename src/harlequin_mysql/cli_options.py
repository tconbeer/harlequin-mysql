from __future__ import annotations

from harlequin.options import (
    FlagOption,
    PathOption,
    TextOption,
)


def _int_validator(s: str | None) -> tuple[bool, str]:
    if s is None:
        return True, ""
    try:
        _ = int(s)
    except ValueError:
        return False, f"Cannot convert {s} to an int!"
    else:
        return True, ""


host = TextOption(
    name="host",
    description=("The host name or IP address of the MySQL server."),
    short_decls=["-h"],
    default="localhost",
)


port = TextOption(
    name="port",
    description=("The TCP/IP port of the MySQL server. Must be an integer."),
    short_decls=["-p"],
    default="3306",
    validator=_int_validator,
)


unix_socket = TextOption(
    name="unix_socket",
    description=("The location of the Unix socket file."),
)


database = TextOption(
    name="database",
    description=("The database name to use when connecting with the MySQL server."),
    short_decls=["-d", "-db"],
    default="postgres",
)


user = TextOption(
    name="user",
    description=("The database name to use when connecting with the MySQL server."),
    short_decls=["-u", "--username", "-U"],
)


password = TextOption(
    name="password",
    description=("Password to be used if the server demands password authentication."),
    short_decls=["--password1"],
)


password2 = TextOption(
    name="password2",
    description=("For Multi-Factor Authentication (MFA); Added in 8.0.28."),
)


password3 = TextOption(
    name="password3",
    description=("For Multi-Factor Authentication (MFA); Added in 8.0.28."),
)


connect_timeout = TextOption(
    name="connection_timeout",
    description="Timeout for the TCP and Unix socket connections. Must be an integer.",
    short_decls=["--connect_timeout"],
    validator=_int_validator,
)


ssl_ca = PathOption(
    name="ssl-ca",
    description="File containing the SSL certificate authority.",
    exists=True,
    dir_okay=False,
)

ssl_cert = PathOption(
    name="ssl-cert",
    description="File containing the SSL certificate file.",
    exists=True,
    dir_okay=False,
    short_decls=["--sslcert"],
)

ssl_disabled = FlagOption(
    name="ssl-disabled",
    description="True disables SSL/TLS usage.",
)

ssl_key = PathOption(
    name="ssl-key",
    description="File containing the SSL key.",
    exists=True,
    dir_okay=False,
    short_decls=["--sslkey"],
)


MYSQLADAPTER_OPTIONS = [
    host,
    port,
    unix_socket,
    database,
    user,
    password,
    password2,
    password3,
    connect_timeout,
    ssl_ca,
    ssl_cert,
    ssl_disabled,
    ssl_key,
]
