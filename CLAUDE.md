# meta-invoices

Descarga diariamente las facturas PDF de Meta Ads que llegan por correo (4 cuentas
publicitarias distintas) y las sube a OneDrive en carpetas separadas por cuenta,
de forma ordenada, secuencial e idempotente.

## Restricciones técnicas

- Python 3.11.
- Dependencias permitidas: `imaplib` (stdlib), `msal`, `httpx`, `python-dotenv`. **Nada más.**
  (`pytest` sólo como dependencia de desarrollo.)
- Procesamiento **estrictamente secuencial**, ordenado por el header `Date` ascendente.
  Nunca concurrente. Nada de `asyncio`, `threading` ni pools.
- **Idempotente**: reejecutar no debe duplicar archivos ni saltarse facturas.
- **Sin secretos en el código.** Todo desde `.env`. `.env` está en `.gitignore`.
- **Log estructurado**: una línea JSON por evento a stdout.

## Estructura

```
src/config.py    ACCOUNT_MAP {act_id: nombre_carpeta}, carga de .env
src/mail.py      IMAP: busca correos no leídos de *@facebookmail.com con adjunto PDF
src/graph.py     MSAL device-code flow, cache de refresh token en token_cache.json,
                 upload vía PUT /me/drive/root:/{ruta}:/content
src/ledger.py    SQLite: processed(msg_id TEXT PK, act_id, fecha_correo, ruta, uploaded_at)
src/main.py      orquestador
tests/           pytest
```

## Ruta destino en OneDrive

```
/Facturas Meta/{nombre_carpeta}/{YYYY-MM}/{YYYYMMDD-HHMMSS}_{act_id}_{msg_id_corto}.pdf
```

El prefijo timestamp garantiza que el orden lexicográfico sea el cronológico.

## Reglas de idempotencia (críticas, respétalas exactamente)

1. Antes de subir, consultar el ledger por `msg_id`. Si existe, saltar y loguear `"skipped"`.
2. Upload con `@microsoft.graph.conflictBehavior=fail`. Si Graph devuelve **409**,
   tratarlo como éxito y commitear en el ledger igualmente.
3. Commitear en el ledger **DESPUÉS** del upload exitoso.
4. Marcar el correo como leído **SOLO** después del commit en el ledger.
5. Reintento con backoff exponencial (3 intentos) únicamente en **429** y **5xx**.
   Nunca reintentar otros 4xx: loguear y abortar ese ítem.

## Salida

- Exit code `0` si todo ok.
- Exit code `1` si alguna de las 4 cuentas no produjo ninguna factura en la ejecución
  (posible fallo silencioso).

## Fases de desarrollo

| Fase | Contenido |
|------|-----------|
| 1 | Andamiaje: `CLAUDE.md`, `pyproject.toml`, `.env.example`, `.gitignore`, estructura y stubs con firmas + docstrings. Sin lógica. |
| 2 | `graph.py`: device-code flow MSAL (scopes `Files.ReadWrite`, `offline_access`), cache persistente, `upload_file(contenido_bytes, ruta_remota) -> dict`, bloque `__main__` de prueba. |
| 3 | `ledger.py` + tests pytest: inserción, duplicado, reejecución sin escrituras nuevas. |
| 4 | `mail.py` parte A: sólo conexión IMAP y volcado de asunto crudo, remitente, `Date` y nombres de adjuntos. **Sin parser de `act_id`.** |
| 5 | `mail.py` parte B: extracción de `act_id` (regex derivado de la salida real de la Fase 4) y descarga de adjuntos PDF + tests con asuntos reales como fixtures. |
| 6 | `main.py`: orquestación, reglas de idempotencia, exit code y README con instrucciones de cron. |

**Regla de trabajo:** al terminar cada fase, detenerse y esperar confirmación.
No implementar fases futuras.
