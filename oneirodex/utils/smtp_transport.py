"""SMTP transport selection with TLS required on implicit-TLS port 465."""
from __future__ import annotations

import smtplib
import ssl


def open_smtp_connection(host: str, port: int, *, use_tls: bool, timeout: int):
    """Open SMTP or implicit-TLS SMTP while refusing plaintext on port 465."""
    if int(port) == 465:
        if not use_tls:
            raise ValueError('TLS is required for SMTP port 465')
        return smtplib.SMTP_SSL(
            host,
            port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
    return smtplib.SMTP(host, port, timeout=timeout)


def upgrade_smtp_connection(connection, port: int, *, use_tls: bool) -> None:
    """Use STARTTLS where configured; port 465 negotiates TLS at connect time."""
    if use_tls and int(port) != 465:
        connection.starttls(context=ssl.create_default_context())
