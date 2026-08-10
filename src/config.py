"""Carga de configuración desde `.env` y logging estructurado.

Toda la configuración vive en variables de entorno; no hay secretos en el código.
Este módulo es el único punto donde se lee el entorno.

FASE 1: sólo firmas y docstrings. Sin lógica.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Configuración completa de una ejecución.

    Attributes:
        imap_host: Host del servidor IMAP.
        imap_port: Puerto IMAP (993 para IMAPS).
        imap_user: Usuario/buzón del que se leen los correos.
        imap_password: Contraseña (o app password) del buzón.
        imap_folder: Carpeta IMAP a inspeccionar (por defecto ``INBOX``).
        graph_client_id: Application (client) ID del registro de app en Entra ID.
        graph_tenant_id: Tenant id, o ``common`` / ``consumers``.
        token_cache_path: Ruta del fichero donde MSAL persiste el token cache.
        account_map: Mapa ``{act_id: nombre_carpeta}`` con las 4 cuentas.
        onedrive_root: Carpeta raíz en OneDrive (p. ej. ``/Facturas Meta``).
        ledger_path: Ruta del SQLite del ledger de idempotencia.
        sender_domain: Dominio del remitente esperado (``facebookmail.com``).
        dry_run: Si es ``True`` no se sube nada ni se marcan correos como leídos.
    """

    imap_host: str
    imap_port: int
    imap_user: str
    imap_password: str
    imap_folder: str
    graph_client_id: str
    graph_tenant_id: str
    token_cache_path: str
    account_map: dict[str, str]
    onedrive_root: str
    ledger_path: str
    sender_domain: str
    dry_run: bool


def load_config(env_path: str | None = None) -> Config:
    """Carga y valida la configuración desde `.env` + variables de entorno.

    Args:
        env_path: Ruta opcional a un fichero `.env`. Si es ``None`` se busca
            el `.env` del directorio de trabajo.

    Returns:
        Una instancia de :class:`Config` con todos los valores resueltos.

    Raises:
        ValueError: Si falta alguna variable obligatoria, si ``ACCOUNT_MAP``
            no es JSON válido o si no contiene exactamente 4 cuentas.
    """
    raise NotImplementedError("Fase 1: stub")


def parse_account_map(raw: str) -> dict[str, str]:
    """Parsea el JSON de ``ACCOUNT_MAP`` a ``{act_id: nombre_carpeta}``.

    Args:
        raw: Cadena JSON tal como viene del entorno.

    Returns:
        Mapa de id de cuenta publicitaria a nombre de carpeta en OneDrive.

    Raises:
        ValueError: Si el JSON es inválido, no es un objeto plano de strings,
            o no contiene exactamente 4 entradas.
    """
    raise NotImplementedError("Fase 1: stub")


def log_event(event: str, **fields: object) -> None:
    """Emite una línea JSON por evento a stdout.

    Formato: ``{"ts": "...", "event": "<event>", ...fields}``. Es la única
    forma de logging del proyecto; nunca se usa ``print`` libre.

    Args:
        event: Nombre corto del evento (``"skipped"``, ``"uploaded"``, ...).
        **fields: Campos adicionales serializables a JSON.
    """
    raise NotImplementedError("Fase 1: stub")
