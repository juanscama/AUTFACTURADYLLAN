"""Tests de `graph.upload_file`: contrato HTTP y política de reintentos.

Se usa `httpx.MockTransport` (parte de httpx, no una dependencia nueva) para
no tocar la red. La autenticación se sustituye por un token falso: aquí se
verifica el comportamiento de subida, no MSAL.
"""

from __future__ import annotations

import httpx
import pytest

import graph
from graph import GraphClient, GraphError


def make_client(handler, monkeypatch, **kwargs) -> GraphClient:
    """Crea un GraphClient con transporte simulado y sin autenticación real."""
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = GraphClient(
        client_id="fake-client-id",
        tenant_id="common",
        token_cache_path="/dev/null",
        http_client=http,
        backoff_base=0.0,
        **kwargs,
    )
    monkeypatch.setattr(client, "acquire_token", lambda: "fake-token")
    monkeypatch.setattr(graph.time, "sleep", lambda _seconds: None)
    return client


def test_upload_ok_construye_la_peticion_correcta(monkeypatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"id": "01ABC", "name": "f.pdf"})

    client = make_client(handler, monkeypatch)
    result = client.upload_file(b"%PDF-1.4", "Facturas Meta/Cliente A/2026-08/f.pdf")

    assert result["status"] == "uploaded"
    assert result["item"]["id"] == "01ABC"

    request = seen[0]
    assert request.method == "PUT"
    assert request.url.host == "graph.microsoft.com"
    # Direccionamiento por path, con los espacios percent-encoded.
    assert "/me/drive/root:/Facturas%20Meta/Cliente%20A/2026-08/f.pdf:/content" in str(
        request.url
    )
    # Regla 2: el conflictBehavior debe ser fail, nunca replace.
    assert "@microsoft.graph.conflictBehavior=fail" in str(request.url)
    assert request.headers["Authorization"] == "Bearer fake-token"
    assert request.headers["Content-Type"] == "application/pdf"
    assert request.content == b"%PDF-1.4"


def test_409_se_trata_como_exito(monkeypatch) -> None:
    """Regla 2: el fichero ya existe -> éxito idempotente, sin excepción."""
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(409, json={"error": {"code": "nameAlreadyExists"}})

    client = make_client(handler, monkeypatch)
    result = client.upload_file(b"x", "Facturas Meta/Cliente A/2026-08/f.pdf")

    assert result["status"] == "already_exists"
    assert result["http_status"] == 409
    assert calls == 1, "un 409 no debe reintentarse"


@pytest.mark.parametrize("status", [429, 500, 503])
def test_reintenta_en_429_y_5xx_y_acaba_bien(status: int, monkeypatch) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(status, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"id": "ok"})

    client = make_client(handler, monkeypatch)
    result = client.upload_file(b"x", "a/b.pdf")

    assert result["status"] == "uploaded"
    assert calls == 3


@pytest.mark.parametrize("status", [429, 500])
def test_agota_los_tres_intentos_y_falla(status: int, monkeypatch) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    client = make_client(handler, monkeypatch)
    with pytest.raises(GraphError):
        client.upload_file(b"x", "a/b.pdf")

    assert calls == graph.MAX_ATTEMPTS == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413])
def test_otros_4xx_no_se_reintentan(status: int, monkeypatch) -> None:
    """Regla 5: cualquier 4xx que no sea 429 aborta el ítem sin reintentos."""
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="nope")

    client = make_client(handler, monkeypatch)
    with pytest.raises(GraphError):
        client.upload_file(b"x", "a/b.pdf")

    assert calls == 1


def test_encode_path_normaliza_barras() -> None:
    assert GraphClient._encode_path("/Facturas Meta//Cliente A/f.pdf") == (
        "Facturas%20Meta/Cliente%20A/f.pdf"
    )
    with pytest.raises(ValueError):
        GraphClient._encode_path("///")


def test_scopes_no_incluyen_reservados_en_la_peticion() -> None:
    """MSAL rechaza offline_access como scope explícito; debe filtrarse."""
    assert "offline_access" in graph.SCOPES
    assert graph._REQUEST_SCOPES == ["Files.ReadWrite"]
