"""Cliente de Microsoft Graph: autenticación MSAL y subida a OneDrive.

Autenticación por *device code flow* con scopes ``Files.ReadWrite`` y
``offline_access``. El refresh token se persiste en ``token_cache.json`` para
que las ejecuciones desatendidas (cron) no requieran interacción.

FASE 1: sólo firmas y docstrings. Sin lógica.
"""

from __future__ import annotations

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
SCOPES = ["Files.ReadWrite", "offline_access"]


class GraphError(Exception):
    """Error no recuperable devuelto por Microsoft Graph.

    Se usa para 4xx distintos de 429, que según las reglas de idempotencia
    nunca se reintentan: se loguean y abortan el ítem en curso.
    """


class GraphClient:
    """Cliente mínimo de Graph para subir ficheros al OneDrive del usuario."""

    def __init__(
        self,
        client_id: str,
        tenant_id: str,
        token_cache_path: str,
    ) -> None:
        """Inicializa el cliente.

        Args:
            client_id: Application (client) ID del registro de app.
            tenant_id: Tenant id, o ``common`` / ``consumers``.
            token_cache_path: Fichero donde persistir el token cache de MSAL.
        """
        raise NotImplementedError("Fase 1: stub")

    def acquire_token(self) -> str:
        """Obtiene un access token válido.

        Intenta primero silenciosamente desde el cache (refresh token). Si no
        hay cuenta cacheada o el refresh falla, inicia el device code flow e
        imprime el código para que el usuario lo introduzca.

        Returns:
            El access token como cadena.

        Raises:
            GraphError: Si no se pudo obtener un token.
        """
        raise NotImplementedError("Fase 1: stub")

    def upload_file(self, content: bytes, remote_path: str) -> dict:
        """Sube un fichero a OneDrive con ``conflictBehavior=fail``.

        Usa ``PUT /me/drive/root:/{remote_path}:/content``. Un **409** (el
        fichero ya existe) se trata como éxito: es la señal de que una
        ejecución anterior ya lo subió.

        Reintenta con backoff exponencial (3 intentos) sólo en 429 y 5xx.
        Cualquier otro 4xx aborta el ítem.

        Args:
            content: Contenido del PDF en bytes.
            remote_path: Ruta destino relativa a la raíz del drive, sin barra
                inicial (p. ej. ``Facturas Meta/Cliente A/2026-08/....pdf``).

        Returns:
            Un dict con al menos ``{"status": "uploaded" | "already_exists",
            "path": remote_path}`` y, si Graph lo devolvió, el DriveItem.

        Raises:
            GraphError: Ante un 4xx no reintentable o tras agotar reintentos.
        """
        raise NotImplementedError("Fase 1: stub")


if __name__ == "__main__":
    # FASE 2: bloque de verificación manual (autenticar + subir un PDF de prueba).
    raise SystemExit("Fase 1: sin lógica todavía.")
