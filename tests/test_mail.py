"""Tests de la parte A de `mail.py`: parseo de metadatos y orden cronológico.

Todo se prueba con mensajes sintéticos: no se abre ninguna conexión IMAP.
Los fixtures con asuntos reales llegan en la FASE 5.
"""

from __future__ import annotations

from datetime import timezone
from email.message import EmailMessage

import pytest

from mail import (
    EPOCH,
    MailClient,
    decode_mime_header,
    describe_message,
    extract_body_text,
    is_pdf_part,
    parse_date,
    stable_fallback_id,
)


def build_message(
    subject: str = "Tu factura",
    sender: str = "advertise-noreply@facebookmail.com",
    date: str = "Mon, 03 Aug 2026 09:15:00 +0000",
    msg_id: str | None = "<abc123@facebookmail.com>",
    body: str = "Cuerpo del correo.",
    attachments: tuple[tuple[str, str, bytes], ...] = (),
) -> EmailMessage:
    """Construye un mensaje sintético con los adjuntos indicados."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "facturacion@ejemplo.com"
    msg["Date"] = date
    if msg_id is not None:
        msg["Message-ID"] = msg_id
    msg.set_content(body)
    for filename, content_type, payload in attachments:
        maintype, _, subtype = content_type.partition("/")
        msg.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
    return msg


# -- Headers ----------------------------------------------------------------


def test_decode_mime_header_rfc2047() -> None:
    codificado = "=?UTF-8?B?VHUgZmFjdHVyYSBkZSBhbnVuY2lvcw==?="
    assert decode_mime_header(codificado) == "Tu factura de anuncios"


def test_decode_mime_header_vacio() -> None:
    assert decode_mime_header(None) == ""
    assert decode_mime_header("") == ""


def test_parse_date_con_zona() -> None:
    resultado = parse_date("Mon, 03 Aug 2026 09:15:00 +0200")
    assert resultado.tzinfo is not None
    assert resultado.astimezone(timezone.utc).hour == 7


def test_parse_date_sin_zona_asume_utc() -> None:
    resultado = parse_date("Mon, 03 Aug 2026 09:15:00")
    assert resultado.tzinfo == timezone.utc


def test_parse_date_ilegible_cae_a_epoch() -> None:
    assert parse_date("no soy una fecha") == EPOCH
    assert parse_date(None) == EPOCH
    assert parse_date("") == EPOCH


# -- Adjuntos ---------------------------------------------------------------


def test_describe_detecta_adjunto_pdf() -> None:
    msg = build_message(attachments=(("factura.pdf", "application/pdf", b"%PDF-1.4 x"),))
    info = describe_message(msg, "42")

    assert info["has_pdf"] is True
    assert info["uid"] == "42"
    assert info["msg_id"] == "<abc123@facebookmail.com>"
    assert [a["filename"] for a in info["attachments"]] == ["factura.pdf"]
    assert info["attachments"][0]["content_type"] == "application/pdf"
    assert info["attachments"][0]["size"] == len(b"%PDF-1.4 x")


def test_pdf_enviado_como_octet_stream_cuenta_como_pdf() -> None:
    """Meta no siempre declara el Content-Type correcto; vale la extensión."""
    msg = build_message(
        attachments=(("factura.pdf", "application/octet-stream", b"%PDF-1.4"),)
    )
    info = describe_message(msg, "1")
    assert info["has_pdf"] is True


def test_adjunto_no_pdf_no_cuenta() -> None:
    msg = build_message(attachments=(("logo.png", "image/png", b"\x89PNG"),))
    info = describe_message(msg, "1")

    assert info["has_pdf"] is False
    assert [a["filename"] for a in info["attachments"]] == ["logo.png"]


def test_correo_sin_adjuntos() -> None:
    info = describe_message(build_message(), "1")
    assert info["attachments"] == []
    assert info["has_pdf"] is False


def test_mezcla_de_adjuntos() -> None:
    msg = build_message(
        attachments=(
            ("logo.png", "image/png", b"\x89PNG"),
            ("factura.pdf", "application/pdf", b"%PDF"),
        )
    )
    info = describe_message(msg, "1")

    assert info["has_pdf"] is True
    assert len(info["attachments"]) == 2
    assert [a["is_pdf"] for a in info["attachments"]] == [False, True]


def test_nombre_de_adjunto_codificado_se_decodifica() -> None:
    msg = build_message(
        attachments=(("=?UTF-8?B?ZmFjdHVyYQ==?=.pdf", "application/pdf", b"%PDF"),)
    )
    info = describe_message(msg, "1")
    assert info["attachments"][0]["filename"].endswith(".pdf")


def test_describe_sobre_bytes_crudos_como_los_de_imap() -> None:
    """IMAP devuelve bytes que se parsean con message_from_bytes (clase Message,
    no EmailMessage); el parseo debe comportarse igual."""
    import email as email_module

    original = build_message(
        subject="=?UTF-8?Q?Tu_factura_de_agosto?=",
        attachments=(("factura.pdf", "application/pdf", b"%PDF-1.4 datos"),),
    )
    reparsed = email_module.message_from_bytes(original.as_bytes())
    info = describe_message(reparsed, "7")

    assert info["has_pdf"] is True
    assert info["subject"] == "Tu factura de agosto"
    assert info["attachments"][0]["filename"] == "factura.pdf"
    assert info["attachments"][0]["size"] == len(b"%PDF-1.4 datos")


def test_is_pdf_part_sobre_el_cuerpo_de_texto() -> None:
    msg = build_message()
    cuerpo = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
    assert is_pdf_part(cuerpo) is False


# -- Message-ID -------------------------------------------------------------


def test_message_id_ausente_usa_fallback_estable() -> None:
    msg = build_message(msg_id=None)
    primero = describe_message(msg, "1")["msg_id"]
    segundo = describe_message(build_message(msg_id=None), "1")["msg_id"]

    assert primero.startswith("sha256:")
    assert primero == segundo, "el fallback debe ser estable entre ejecuciones"


def test_fallback_distingue_correos_distintos() -> None:
    uno = stable_fallback_id(build_message(subject="Factura A", msg_id=None))
    otro = stable_fallback_id(build_message(subject="Factura B", msg_id=None))
    assert uno != otro


# -- Cuerpo -----------------------------------------------------------------


def test_extract_body_text() -> None:
    msg = build_message(body="Hola\nEsta es tu factura.")
    assert "Esta es tu factura." in extract_body_text(msg)


def test_extract_body_text_trunca() -> None:
    msg = build_message(body="x" * 5000)
    assert len(extract_body_text(msg, limit=100)) == 100


# -- Orden cronológico ------------------------------------------------------


class FakeMailClient(MailClient):
    """MailClient con IMAP sustituido por un diccionario en memoria."""

    def __init__(self, mensajes: dict[str, EmailMessage]) -> None:
        super().__init__("host", 993, "user", "pass")
        self._mensajes = mensajes

    def search_unread(self, sender_domain: str, unread_only: bool = True) -> list[str]:
        return list(self._mensajes)

    def fetch_raw(self, uid: str) -> EmailMessage:
        return self._mensajes[uid]


def test_list_candidates_ordena_por_date_no_por_uid() -> None:
    """El UID refleja el orden de llegada; el requisito es el header Date."""
    pdf = (("f.pdf", "application/pdf", b"%PDF"),)
    mensajes = {
        # UID bajo pero fecha posterior: debe quedar el último.
        "10": build_message(
            date="Wed, 05 Aug 2026 12:00:00 +0000", msg_id="<c@x>", attachments=pdf
        ),
        "20": build_message(
            date="Mon, 03 Aug 2026 08:00:00 +0000", msg_id="<a@x>", attachments=pdf
        ),
        "30": build_message(
            date="Tue, 04 Aug 2026 09:30:00 +0000", msg_id="<b@x>", attachments=pdf
        ),
    }
    candidatos = FakeMailClient(mensajes).list_candidates("facebookmail.com")

    assert [c.msg_id for c in candidatos] == ["<a@x>", "<b@x>", "<c@x>"]
    assert [c.date for c in candidatos] == sorted(c.date for c in candidatos)


def test_list_candidates_descarta_los_que_no_llevan_pdf() -> None:
    mensajes = {
        "1": build_message(msg_id="<con@x>", attachments=(("f.pdf", "application/pdf", b"%PDF"),)),
        "2": build_message(msg_id="<sin@x>"),
        "3": build_message(msg_id="<png@x>", attachments=(("i.png", "image/png", b"\x89"),)),
    }
    candidatos = FakeMailClient(mensajes).list_candidates("facebookmail.com")
    assert [c.msg_id for c in candidatos] == ["<con@x>"]


def test_fetch_message_devuelve_none_sin_pdf() -> None:
    cliente = FakeMailClient({"1": build_message()})
    assert cliente.fetch_message("1") is None


# -- Fase 5: todavía sin implementar ----------------------------------------


def test_extract_act_id_sigue_pendiente() -> None:
    """El regex se deriva de datos reales en la Fase 5, no de suposiciones."""
    from mail import extract_act_id

    with pytest.raises(NotImplementedError):
        extract_act_id("cualquier asunto")
