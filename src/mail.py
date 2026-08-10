"""Acceso IMAP al buzón donde llegan las facturas de Meta.

Busca correos NO LEÍDOS cuyo remitente sea ``*@facebookmail.com`` y que lleven
al menos un adjunto PDF. Los devuelve ordenados por el header ``Date``
ascendente, para que el procesamiento sea estrictamente cronológico.

FASE 1: sólo firmas y docstrings. Sin lógica.
FASE 4: conexión IMAP + volcado de metadatos crudos (sin parser de act_id).
FASE 5: extracción de act_id y descarga de adjuntos PDF.
"""

from __future__ import annotations

import imaplib
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Attachment:
    """Un adjunto de un correo.

    Attributes:
        filename: Nombre del fichero tal como viene en el correo.
        content_type: Content-Type MIME declarado.
        content: Bytes del adjunto.
    """

    filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class InvoiceMessage:
    """Un correo candidato a contener una factura de Meta.

    Attributes:
        msg_id: Header ``Message-ID`` (clave de idempotencia).
        uid: UID IMAP del mensaje, necesario para marcarlo como leído.
        subject: Asunto ya decodificado.
        sender: Header ``From``.
        date: Header ``Date`` parseado a ``datetime`` con tzinfo.
        attachment_names: Nombres de los adjuntos del correo.
    """

    msg_id: str
    uid: str
    subject: str
    sender: str
    date: datetime
    attachment_names: list[str]


class MailClient:
    """Cliente IMAP de sólo lectura salvo por el marcado de ``\\Seen``."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        folder: str = "INBOX",
    ) -> None:
        """Guarda los parámetros de conexión. No conecta todavía.

        Args:
            host: Host IMAP.
            port: Puerto IMAP.
            user: Usuario del buzón.
            password: Contraseña o app password.
            folder: Carpeta a inspeccionar.
        """
        raise NotImplementedError("Fase 1: stub")

    def connect(self) -> imaplib.IMAP4_SSL:
        """Abre la conexión IMAPS, hace login y selecciona la carpeta.

        Returns:
            La conexión ``IMAP4_SSL`` ya autenticada.
        """
        raise NotImplementedError("Fase 1: stub")

    def close(self) -> None:
        """Cierra la carpeta y hace logout, ignorando errores de cierre."""
        raise NotImplementedError("Fase 1: stub")

    def search_unread(self, sender_domain: str) -> list[str]:
        """Busca los UIDs de correos no leídos del dominio indicado.

        Args:
            sender_domain: Dominio del remitente (p. ej. ``facebookmail.com``).

        Returns:
            Lista de UIDs IMAP como cadenas.
        """
        raise NotImplementedError("Fase 1: stub")

    def fetch_message(self, uid: str) -> InvoiceMessage | None:
        """Descarga un mensaje y extrae sus metadatos.

        Args:
            uid: UID IMAP del mensaje.

        Returns:
            El :class:`InvoiceMessage` correspondiente, o ``None`` si el
            mensaje no tiene ningún adjunto PDF.
        """
        raise NotImplementedError("Fase 1: stub")

    def list_candidates(self, sender_domain: str) -> list[InvoiceMessage]:
        """Devuelve los correos candidatos ordenados por ``Date`` ascendente.

        Args:
            sender_domain: Dominio del remitente esperado.

        Returns:
            Lista de :class:`InvoiceMessage` en orden cronológico ascendente.
        """
        raise NotImplementedError("Fase 1: stub")

    def fetch_pdf_attachments(self, uid: str) -> list[Attachment]:
        """Descarga los adjuntos PDF de un mensaje.

        Args:
            uid: UID IMAP del mensaje.

        Returns:
            Lista de :class:`Attachment` con ``content_type`` PDF.
        """
        raise NotImplementedError("Fase 5: stub")

    def mark_as_read(self, uid: str) -> None:
        """Marca el mensaje con el flag ``\\Seen``.

        Sólo debe llamarse DESPUÉS de commitear en el ledger.

        Args:
            uid: UID IMAP del mensaje.
        """
        raise NotImplementedError("Fase 1: stub")


def extract_act_id(subject: str, body: str = "") -> str | None:
    """Extrae el ``act_id`` de la cuenta publicitaria de un correo.

    El regex se derivará en la FASE 5 a partir de asuntos reales capturados
    en la FASE 4; no se infiere de suposiciones.

    Args:
        subject: Asunto crudo del correo.
        body: Cuerpo del correo, si hiciera falta como respaldo.

    Returns:
        El ``act_id`` encontrado, o ``None`` si no se pudo determinar.
    """
    raise NotImplementedError("Fase 5: stub")
