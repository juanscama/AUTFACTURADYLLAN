"""Ledger de idempotencia sobre SQLite.

Esquema::

    CREATE TABLE processed (
        msg_id      TEXT PRIMARY KEY,
        act_id      TEXT NOT NULL,
        fecha_correo TEXT NOT NULL,
        ruta        TEXT NOT NULL,
        uploaded_at TEXT NOT NULL
    )

El commit en el ledger ocurre SIEMPRE después de un upload exitoso y ANTES de
marcar el correo como leído.

FASE 1: sólo firmas y docstrings. Sin lógica.
"""

from __future__ import annotations

import sqlite3


class Ledger:
    """Registro persistente de mensajes ya procesados."""

    def __init__(self, db_path: str) -> None:
        """Abre (o crea) la base de datos del ledger.

        Args:
            db_path: Ruta del fichero SQLite. ``:memory:`` es válido en tests.
        """
        raise NotImplementedError("Fase 1: stub")

    def init_schema(self) -> None:
        """Crea la tabla ``processed`` si no existe. Idempotente."""
        raise NotImplementedError("Fase 1: stub")

    def is_processed(self, msg_id: str) -> bool:
        """Indica si un ``msg_id`` ya fue procesado.

        Args:
            msg_id: Message-ID del correo.

        Returns:
            ``True`` si existe una fila para ese ``msg_id``.
        """
        raise NotImplementedError("Fase 1: stub")

    def commit_processed(
        self,
        msg_id: str,
        act_id: str,
        fecha_correo: str,
        ruta: str,
    ) -> bool:
        """Registra un mensaje como procesado tras un upload exitoso.

        La inserción es ``INSERT OR IGNORE``: si el ``msg_id`` ya existía no
        se sobrescribe nada, de modo que una reejecución completa no genera
        escrituras nuevas.

        Args:
            msg_id: Message-ID del correo (clave primaria).
            act_id: Id de la cuenta publicitaria.
            fecha_correo: Header ``Date`` normalizado a ISO-8601.
            ruta: Ruta remota en OneDrive donde se subió el PDF.

        Returns:
            ``True`` si se insertó una fila nueva, ``False`` si ya existía.
        """
        raise NotImplementedError("Fase 1: stub")

    def count(self) -> int:
        """Devuelve el número de filas en ``processed``."""
        raise NotImplementedError("Fase 1: stub")

    def close(self) -> None:
        """Cierra la conexión SQLite."""
        raise NotImplementedError("Fase 1: stub")

    def __enter__(self) -> "Ledger":
        """Permite usar el ledger como context manager."""
        raise NotImplementedError("Fase 1: stub")

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Cierra la conexión al salir del context manager."""
        raise NotImplementedError("Fase 1: stub")


def connect(db_path: str) -> sqlite3.Connection:
    """Abre una conexión SQLite con los PRAGMA del proyecto.

    Args:
        db_path: Ruta del fichero SQLite.

    Returns:
        La conexión abierta.
    """
    raise NotImplementedError("Fase 1: stub")
