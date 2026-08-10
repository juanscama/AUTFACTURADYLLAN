"""Cliente de Microsoft Graph: autenticación MSAL y subida a OneDrive.

Autenticación por *device code flow* con scopes ``Files.ReadWrite`` y
``offline_access``. El refresh token se persiste en ``token_cache.json`` para
que las ejecuciones desatendidas (cron) no requieran interacción.

Nota sobre los scopes: MSAL añade ``offline_access`` (y ``openid``/``profile``)
automáticamente en los flujos de cliente público y rechaza que se le pasen
explícitamente, así que :data:`SCOPES` documenta el conjunto efectivo y
:data:`_REQUEST_SCOPES` es lo que realmente se le entrega a MSAL.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.parse
from pathlib import Path

import httpx
import msal

from config import log_event

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
SCOPES = ["Files.ReadWrite", "offline_access"]

#: Scopes reservados que MSAL gestiona por su cuenta y no acepta como entrada.
_RESERVED_SCOPES = frozenset({"openid", "profile", "offline_access"})
_REQUEST_SCOPES = [s for s in SCOPES if s not in _RESERVED_SCOPES]

#: Intentos totales (1 inicial + 2 reintentos) para 429 y 5xx.
MAX_ATTEMPTS = 3
#: Segundos base del backoff exponencial: 1s, 2s, 4s...
DEFAULT_BACKOFF_BASE = 1.0
#: Tope de espera cuando el servidor manda un ``Retry-After`` desmesurado.
MAX_BACKOFF_SECONDS = 60.0


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
        http_client: httpx.Client | None = None,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
    ) -> None:
        """Inicializa el cliente. No hace ninguna llamada de red.

        Args:
            client_id: Application (client) ID del registro de app.
            tenant_id: Tenant id, o ``common`` / ``consumers``.
            token_cache_path: Fichero donde persistir el token cache de MSAL.
            http_client: Cliente httpx a reutilizar. Si es ``None`` se crea uno
                propio. Se inyecta en los tests.
            backoff_base: Segundos base del backoff exponencial.
        """
        if not client_id:
            raise ValueError("client_id es obligatorio")
        self._client_id = client_id
        self._authority = f"https://login.microsoftonline.com/{tenant_id or 'common'}"
        self._cache_path = Path(token_cache_path)
        self._backoff_base = backoff_base

        self._cache = msal.SerializableTokenCache()
        self._app: msal.PublicClientApplication | None = None

        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0))

    # -- Autenticación ------------------------------------------------------

    def _load_cache(self) -> None:
        """Carga el token cache desde disco si existe."""
        if self._cache_path.exists():
            self._cache.deserialize(self._cache_path.read_text(encoding="utf-8"))

    def _save_cache(self) -> None:
        """Persiste el token cache a disco si cambió, con permisos 0600."""
        if not self._cache.has_state_changed:
            return
        parent = self._cache_path.parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        tmp = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
        tmp.write_text(self._cache.serialize(), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self._cache_path)

    def _get_app(self) -> msal.PublicClientApplication:
        """Construye la app MSAL de forma perezosa (la primera vez toca red)."""
        if self._app is None:
            self._load_cache()
            self._app = msal.PublicClientApplication(
                self._client_id,
                authority=self._authority,
                token_cache=self._cache,
            )
        return self._app

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
        app = self._get_app()

        result = None
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(_REQUEST_SCOPES, account=accounts[0])
            if result and "access_token" in result:
                log_event("auth_silent", account=accounts[0].get("username"))

        if not result or "access_token" not in result:
            result = self._device_code_flow(app)

        self._save_cache()

        token = result.get("access_token") if result else None
        if not token:
            raise GraphError(
                f"No se pudo obtener access token: "
                f"{(result or {}).get('error')} / {(result or {}).get('error_description')}"
            )
        return token

    def _device_code_flow(self, app: msal.PublicClientApplication) -> dict:
        """Ejecuta el device code flow, bloqueando hasta que el usuario lo complete.

        Args:
            app: La aplicación MSAL.

        Returns:
            El dict de resultado de MSAL.

        Raises:
            GraphError: Si no se pudo iniciar el flujo.
        """
        flow = app.initiate_device_flow(scopes=_REQUEST_SCOPES)
        if "user_code" not in flow:
            raise GraphError(f"No se pudo iniciar el device code flow: {flow}")

        log_event(
            "auth_device_code",
            verification_uri=flow.get("verification_uri"),
            user_code=flow.get("user_code"),
            expires_in=flow.get("expires_in"),
        )
        # El mensaje legible va a stderr para no contaminar el log JSON de stdout.
        print(flow.get("message", ""), file=sys.stderr, flush=True)

        result = app.acquire_token_by_device_flow(flow)
        if "access_token" in result:
            log_event("auth_device_code_ok")
        return result

    # -- Subida -------------------------------------------------------------

    @staticmethod
    def _encode_path(remote_path: str) -> str:
        """Normaliza y codifica una ruta remota para el direccionamiento por path.

        Args:
            remote_path: Ruta relativa a la raíz del drive, con o sin barras
                sobrantes al principio o al final.

        Returns:
            La ruta con los segmentos percent-encoded, sin barra inicial.

        Raises:
            ValueError: Si la ruta queda vacía.
        """
        segments = [s for s in remote_path.strip().split("/") if s]
        if not segments:
            raise ValueError("remote_path vacío")
        return "/".join(urllib.parse.quote(s, safe="") for s in segments)

    def _sleep_for(self, attempt: int, response: httpx.Response) -> float:
        """Calcula la espera antes del siguiente intento.

        Args:
            attempt: Número de intento ya consumido (empezando en 1).
            response: Respuesta que provocó el reintento.

        Returns:
            Segundos a esperar: ``Retry-After`` si el servidor lo indica, si no
            backoff exponencial.
        """
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), MAX_BACKOFF_SECONDS)
            except ValueError:
                pass  # Formato fecha HTTP: caemos al backoff exponencial.
        return min(self._backoff_base * (2 ** (attempt - 1)), MAX_BACKOFF_SECONDS)

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
            "path": remote_path}`` y, si Graph lo devolvió, el DriveItem en
            ``item``.

        Raises:
            GraphError: Ante un 4xx no reintentable o tras agotar reintentos.
        """
        encoded = self._encode_path(remote_path)
        url = (
            f"{GRAPH_BASE_URL}/me/drive/root:/{encoded}:/content"
            f"?@microsoft.graph.conflictBehavior=fail"
        )
        token = self.acquire_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/pdf",
        }

        last_status: int | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            response = self._http.put(url, content=content, headers=headers)
            status = response.status_code
            last_status = status

            if 200 <= status < 300:
                log_event(
                    "uploaded",
                    path=remote_path,
                    status=status,
                    bytes=len(content),
                    attempt=attempt,
                )
                return {
                    "status": "uploaded",
                    "path": remote_path,
                    "http_status": status,
                    "item": _safe_json(response),
                }

            if status == 409:
                # Ya existía: una ejecución previa lo subió. Éxito idempotente.
                log_event("already_exists", path=remote_path, status=status)
                return {
                    "status": "already_exists",
                    "path": remote_path,
                    "http_status": status,
                    "item": None,
                }

            retryable = status == 429 or 500 <= status < 600
            if not retryable:
                log_event(
                    "upload_failed",
                    path=remote_path,
                    status=status,
                    body=response.text[:500],
                    retryable=False,
                )
                raise GraphError(f"Graph {status} en {remote_path}: {response.text[:500]}")

            if attempt == MAX_ATTEMPTS:
                break

            wait = self._sleep_for(attempt, response)
            log_event(
                "upload_retry",
                path=remote_path,
                status=status,
                attempt=attempt,
                sleep=wait,
            )
            time.sleep(wait)

        log_event(
            "upload_failed",
            path=remote_path,
            status=last_status,
            attempts=MAX_ATTEMPTS,
            retryable=True,
        )
        raise GraphError(
            f"Graph {last_status} en {remote_path}: agotados {MAX_ATTEMPTS} intentos"
        )

    def close(self) -> None:
        """Cierra el cliente HTTP si es propio de esta instancia."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "GraphClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def _safe_json(response: httpx.Response) -> dict | None:
    """Devuelve el JSON de la respuesta, o ``None`` si no lo es.

    Args:
        response: Respuesta HTTP.

    Returns:
        El cuerpo deserializado, o ``None``.
    """
    try:
        parsed = response.json()
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


# Un PDF válido mínimo, para verificar la conexión sin depender de ficheros locales.
_DUMMY_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]>>endobj\n"
    b"trailer<</Root 1 0 R/Size 4>>\n"
    b"%%EOF\n"
)


if __name__ == "__main__":
    # Verificación manual: autentica y sube un PDF de prueba a OneDrive.
    #
    #   python src/graph.py                 -> sube un PDF dummy generado aquí
    #   python src/graph.py ruta/al/tuyo.pdf -> sube ese fichero
    #
    # La ruta destino es fija a propósito: la SEGUNDA ejecución debe devolver
    # "already_exists" (409), que es justamente el comportamiento idempotente
    # que exige la regla 2.
    from dotenv import load_dotenv

    load_dotenv()

    client_id = os.getenv("GRAPH_CLIENT_ID", "")
    tenant_id = os.getenv("GRAPH_TENANT_ID", "common")
    cache_path = os.getenv("TOKEN_CACHE_PATH", "token_cache.json")
    onedrive_root = os.getenv("ONEDRIVE_ROOT", "/Facturas Meta")

    if not client_id:
        print(
            "Falta GRAPH_CLIENT_ID. Copia .env.example a .env y rellénalo.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if len(sys.argv) > 1:
        payload = Path(sys.argv[1]).read_bytes()
        source = sys.argv[1]
    else:
        payload = _DUMMY_PDF
        source = "<pdf dummy embebido>"

    destination = f"{onedrive_root.strip('/')}/_prueba_conexion.pdf"
    log_event("test_upload_start", source=source, path=destination, bytes=len(payload))

    with GraphClient(client_id, tenant_id, cache_path) as graph_client:
        try:
            outcome = graph_client.upload_file(payload, destination)
        except GraphError as err:
            log_event("test_upload_error", error=str(err))
            raise SystemExit(1) from err

    log_event("test_upload_done", result=outcome["status"], path=outcome["path"])
    raise SystemExit(0)
