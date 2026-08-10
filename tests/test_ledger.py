"""Tests del ledger de idempotencia.

Cubren lo que exige la Fase 3: inserción, detección de duplicado y que una
reejecución completa no genere escrituras nuevas.
"""

from __future__ import annotations

import sqlite3

import pytest

from ledger import Ledger, normalize_msg_id

MENSAJES = [
    ("<msg-1@facebookmail.com>", "act_111", "2026-08-01T09:00:00+00:00", "a/2026-08/1.pdf"),
    ("<msg-2@facebookmail.com>", "act_222", "2026-08-01T09:05:00+00:00", "b/2026-08/2.pdf"),
    ("<msg-3@facebookmail.com>", "act_333", "2026-08-02T10:00:00+00:00", "c/2026-08/3.pdf"),
    ("<msg-4@facebookmail.com>", "act_444", "2026-08-02T10:30:00+00:00", "d/2026-08/4.pdf"),
]


@pytest.fixture()
def db_path(tmp_path) -> str:
    return str(tmp_path / "ledger.db")


def procesar_todo(ledger: Ledger) -> list[bool]:
    """Simula una pasada completa sobre los 4 mensajes, respetando la regla 1."""
    resultados = []
    for msg_id, act_id, fecha, ruta in MENSAJES:
        if ledger.is_processed(msg_id):
            resultados.append(False)  # "skipped"
            continue
        resultados.append(ledger.commit_processed(msg_id, act_id, fecha, ruta))
    return resultados


# -- Inserción --------------------------------------------------------------


def test_insercion_crea_la_fila(db_path: str) -> None:
    with Ledger(db_path) as ledger:
        assert ledger.count() == 0
        assert ledger.commit_processed(*MENSAJES[0]) is True
        assert ledger.count() == 1
        assert ledger.is_processed(MENSAJES[0][0]) is True


def test_insercion_guarda_todos_los_campos(db_path: str) -> None:
    msg_id, act_id, fecha, ruta = MENSAJES[0]
    with Ledger(db_path) as ledger:
        ledger.commit_processed(msg_id, act_id, fecha, ruta)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM processed").fetchone()
    conn.close()

    assert row["msg_id"] == "msg-1@facebookmail.com"
    assert row["act_id"] == act_id
    assert row["fecha_correo"] == fecha
    assert row["ruta"] == ruta
    assert row["uploaded_at"].startswith("20")  # ISO-8601


def test_mensaje_desconocido_no_esta_procesado(db_path: str) -> None:
    with Ledger(db_path) as ledger:
        assert ledger.is_processed("<jamas-visto@facebookmail.com>") is False


# -- Duplicados -------------------------------------------------------------


def test_duplicado_no_inserta_segunda_fila(db_path: str) -> None:
    with Ledger(db_path) as ledger:
        assert ledger.commit_processed(*MENSAJES[0]) is True
        assert ledger.commit_processed(*MENSAJES[0]) is False
        assert ledger.count() == 1


def test_duplicado_conserva_la_ruta_original(db_path: str) -> None:
    """INSERT OR IGNORE: el segundo intento no debe pisar la fila existente."""
    msg_id, act_id, fecha, ruta = MENSAJES[0]
    with Ledger(db_path) as ledger:
        ledger.commit_processed(msg_id, act_id, fecha, ruta)
        ledger.commit_processed(msg_id, "act_OTRA", "2099-01-01T00:00:00+00:00", "otra.pdf")

        row = ledger._conn.execute("SELECT * FROM processed").fetchone()
        assert row["act_id"] == act_id
        assert row["ruta"] == ruta


@pytest.mark.parametrize(
    "variante",
    [
        "<msg-1@facebookmail.com>",
        "msg-1@facebookmail.com",
        "  <msg-1@facebookmail.com>  ",
        "<msg-1@facebookmail.com>\r\n",
    ],
)
def test_duplicado_pese_a_variaciones_del_header(db_path: str, variante: str) -> None:
    """El mismo Message-ID con distinto formato debe ser la misma clave."""
    with Ledger(db_path) as ledger:
        ledger.commit_processed(*MENSAJES[0])
        assert ledger.is_processed(variante) is True
        assert ledger.commit_processed(variante, "act_111", "x", "y") is False
        assert ledger.count() == 1


# -- Reejecución ------------------------------------------------------------


def test_reejecucion_completa_no_escribe_nada(db_path: str) -> None:
    """La comprobación central de la Fase 3.

    Primera pasada: 4 inserciones. Segunda pasada, sobre una conexión nueva:
    cero escrituras y el mismo número de filas.
    """
    with Ledger(db_path) as ledger:
        assert procesar_todo(ledger) == [True, True, True, True]
        assert ledger.count() == 4

    with Ledger(db_path) as ledger:
        escrituras_antes = ledger.total_changes
        assert procesar_todo(ledger) == [False, False, False, False]
        assert ledger.total_changes == escrituras_antes, "no debe haber escrituras nuevas"
        assert ledger.count() == 4


def test_reejecucion_incorpora_solo_lo_nuevo(db_path: str) -> None:
    with Ledger(db_path) as ledger:
        procesar_todo(ledger)

    nuevo = ("<msg-5@facebookmail.com>", "act_111", "2026-08-03T08:00:00+00:00", "a/5.pdf")
    with Ledger(db_path) as ledger:
        assert procesar_todo(ledger) == [False, False, False, False]
        assert ledger.commit_processed(*nuevo) is True
        assert ledger.count() == 5


def test_el_fichero_no_cambia_en_una_reejecucion(db_path: str, tmp_path) -> None:
    """Comprobación a nivel de bytes: la reejecución no toca la base de datos."""
    import hashlib
    from pathlib import Path

    with Ledger(db_path) as ledger:
        procesar_todo(ledger)

    digest_antes = hashlib.sha256(Path(db_path).read_bytes()).hexdigest()

    with Ledger(db_path) as ledger:
        procesar_todo(ledger)

    assert hashlib.sha256(Path(db_path).read_bytes()).hexdigest() == digest_antes


# -- Esquema y validación ---------------------------------------------------


def test_init_schema_es_idempotente(db_path: str) -> None:
    with Ledger(db_path) as ledger:
        ledger.commit_processed(*MENSAJES[0])
        ledger.init_schema()
        ledger.init_schema()
        assert ledger.count() == 1


def test_msg_id_vacio_es_error(db_path: str) -> None:
    with Ledger(db_path) as ledger:
        for invalido in ("", "   ", "<>"):
            with pytest.raises(ValueError):
                ledger.commit_processed(invalido, "act_111", "x", "y")


def test_campos_obligatorios(db_path: str) -> None:
    with Ledger(db_path) as ledger:
        with pytest.raises(ValueError):
            ledger.commit_processed("<m@x>", "", "x", "y")
        with pytest.raises(ValueError):
            ledger.commit_processed("<m@x>", "act_111", "x", "")


def test_normalize_msg_id() -> None:
    assert normalize_msg_id("<a@b>") == "a@b"
    assert normalize_msg_id(" a@b ") == "a@b"
    with pytest.raises(ValueError):
        normalize_msg_id("<>")
