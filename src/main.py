"""Orquestador: correo -> OneDrive, secuencial e idempotente.

Flujo por ítem (estrictamente secuencial, ordenado por ``Date`` ascendente):

1. Consultar el ledger por ``msg_id``; si existe, loguear ``"skipped"`` y seguir.
2. Descargar el adjunto PDF.
3. Subir a OneDrive con ``conflictBehavior=fail`` (409 == éxito).
4. Commitear en el ledger.
5. Marcar el correo como leído.

FASE 1: sólo firmas y docstrings. Sin lógica.
"""

from __future__ import annotations

from datetime import datetime


def build_remote_path(
    onedrive_root: str,
    folder_name: str,
    date: datetime,
    act_id: str,
    msg_id: str,
) -> str:
    """Construye la ruta destino en OneDrive.

    Formato::

        {onedrive_root}/{folder_name}/{YYYY-MM}/{YYYYMMDD-HHMMSS}_{act_id}_{msg_id_corto}.pdf

    El prefijo timestamp garantiza que el orden lexicográfico coincida con el
    cronológico.

    Args:
        onedrive_root: Carpeta raíz (p. ej. ``/Facturas Meta``).
        folder_name: Nombre de carpeta de la cuenta, según ``ACCOUNT_MAP``.
        date: Fecha del correo (header ``Date``).
        act_id: Id de la cuenta publicitaria.
        msg_id: Message-ID completo; se acorta para el nombre de fichero.

    Returns:
        La ruta remota completa.
    """
    raise NotImplementedError("Fase 6: stub")


def short_msg_id(msg_id: str) -> str:
    """Reduce un ``Message-ID`` a un identificador corto y seguro para rutas.

    Args:
        msg_id: Message-ID completo, con o sin ``<>``.

    Returns:
        Un sufijo corto, estable y compuesto sólo por ``[a-z0-9]``.
    """
    raise NotImplementedError("Fase 6: stub")


def process_all() -> int:
    """Ejecuta una pasada completa del pipeline.

    Returns:
        ``0`` si todo fue bien; ``1`` si alguna de las cuentas configuradas no
        produjo ninguna factura en esta ejecución (posible fallo silencioso).
    """
    raise NotImplementedError("Fase 6: stub")


def main() -> int:
    """Punto de entrada de la CLI.

    Returns:
        El exit code del proceso.
    """
    raise NotImplementedError("Fase 6: stub")


if __name__ == "__main__":
    raise SystemExit(main())
