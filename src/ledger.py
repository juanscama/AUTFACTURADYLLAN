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
marcar el correo como leído. Por eso la escritura es síncrona y duradera
(``PRAGMA synchronous=FULL``): si el proceso muere justo después del commit,
la fila ya está en disco y la siguiente ejecución saltará ese mensaje.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed (
    msg_id       TEXT PRIMARY KEY,
    act_id       TEXT NOT NULL,
    fecha_correo TEXT NOT NULL,
    ruta         TEXT NOT NULL,
    uploaded_at  TEXT NOT NULL
)
"""


def normalize_msg_id(msg_id: str) -> str:
    """Normaliza un ``Message-ID`` para usarlo como clave estable.

    Los servidores IMAP devuelven el header con o sin los ángulos y con
    espacios o saltos de línea alrededor. La clave primaria debe ser la misma
    en todos los casos, o la idempotencia se rompe.

    Args:
        msg_id: Message-ID tal como viene del correo.

    Returns:
        El Message-ID sin espacios circundantes ni ``<>``.

    Raises:
        ValueError: Si queda vacío tras normalizar.
    """
    normalized = " ".join(msg_id.split()).strip().strip("<>").strip()
    if not normalized:
        raise ValueError("msg_id vacío")
    return normalized


def connect(db_path: str) -> sqlite3.Connection:
    """Abre una conexión SQLite con los PRAGMA del proyecto.

    Args:
        db_path: Ruta del fichero SQLite.

    Returns:
        La conexión abierta.
    """
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # Durabilidad por encima de velocidad: el ledger es la fuente de verdad.
    conn.execute("PRAGMA synchronous=FULL")
    if db_path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


class Ledger:
    """Registro persistente de mensajes ya procesados."""

    def __init__(self, db_path: str) -> None:
        """Abre (o crea) la base de datos del ledger.

        Args:
            db_path: Ruta del fichero SQLite. ``:memory:`` es válido en tests.
        """
        self.db_path = db_path
        self._conn = connect(db_path)
        self.init_schema()

    def init_schema(self) -> None:
        """Crea la tabla ``processed`` si no existe. Idempotente."""
        self._conn.execute(SCHEMA)

    def is_processed(self, msg_id: str) -> bool:
        """Indica si un ``msg_id`` ya fue procesado.

        Args:
            msg_id: Message-ID del correo.

        Returns:
            ``True`` si existe una fila para ese ``msg_id``.
        """
        key = normalize_msg_id(msg_id)
        row = self._conn.execute(
            "SELECT 1 FROM processed WHERE msg_id = ? LIMIT 1", (key,)
        ).fetchone()
        return row is not None

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

        Raises:
            ValueError: Si ``msg_id``, ``act_id`` o ``ruta`` vienen vacíos.
        """
        key = normalize_msg_id(msg_id)
        if not act_id:
            raise ValueError("act_id vacío")
        if not ruta:
            raise ValueError("ruta vacía")

        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO processed"
            " (msg_id, act_id, fecha_correo, ruta, uploaded_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (key, act_id, fecha_correo, ruta, _now_iso()),
        )
        return cursor.rowcount == 1

    def count(self) -> int:
        """Devuelve el número de filas en ``processed``."""
        return int(self._conn.execute("SELECT COUNT(*) FROM processed").fetchone()[0])

    @property
    def total_changes(self) -> int:
        """Filas modificadas por esta conexión desde que se abrió.

        Sirve para comprobar que una reejecución completa no escribe nada.
        """
        return self._conn.total_changes

    def close(self) -> None:
        """Cierra la conexión SQLite."""
        self._conn.close()

    def __enter__(self) -> "Ledger":
        """Permite usar el ledger como context manager."""
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Cierra la conexión al salir del context manager."""
        self.close()


def _now_iso() -> str:
    """Devuelve el instante actual en UTC como ISO-8601."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
