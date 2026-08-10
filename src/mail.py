"""Acceso IMAP al buzón donde llegan las facturas de Meta.

Busca correos NO LEÍDOS cuyo remitente sea ``*@facebookmail.com`` y que lleven
al menos un adjunto PDF. Los devuelve ordenados por el header ``Date``
ascendente, para que el procesamiento sea estrictamente cronológico.

La lectura es NO DESTRUCTIVA por partida doble: la carpeta se abre con
``EXAMINE`` (readonly) y los cuerpos se piden con ``BODY.PEEK[]``. Ninguna de
las dos cosas toca el flag ``\\Seen``. Sólo :meth:`MailClient.mark_as_read`
modifica flags, y para eso hay que abrir la conexión en modo escritura.

FASE 4: conexión IMAP + volcado de metadatos crudos (sin parser de act_id).
FASE 5: extracción de act_id y descarga de adjuntos PDF.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import hashlib
import imaplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import Message

from config import log_event

#: Fecha de reserva para correos con un header ``Date`` ilegible: van primero.
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

#: Content-Types que se consideran PDF.
PDF_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf", "application/acrobat"})


class MailError(Exception):
    """Fallo de conexión, login o comando IMAP."""


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


# -- Helpers de parseo (puros, testeables sin IMAP) -------------------------


def decode_mime_header(raw: str | None) -> str:
    """Decodifica un header MIME (RFC 2047) a texto legible.

    Args:
        raw: Valor crudo del header, o ``None``.

    Returns:
        El header decodificado, o cadena vacía si venía vacío. Si la
        decodificación falla se devuelve el valor crudo.
    """
    if not raw:
        return ""
    try:
        return str(email.header.make_header(email.header.decode_header(raw)))
    except (UnicodeDecodeError, LookupError, ValueError):
        return raw


def parse_date(raw: str | None) -> datetime:
    """Parsea el header ``Date`` a un ``datetime`` con tzinfo.

    Args:
        raw: Valor crudo del header ``Date``.

    Returns:
        El instante correspondiente. Si el header falta o es ilegible se
        devuelve :data:`EPOCH`, que ordena el mensaje el primero para que se
        procese antes y no se quede colgado indefinidamente.
    """
    if not raw:
        return EPOCH
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        log_event("date_unparseable", raw=raw)
        return EPOCH
    if parsed.tzinfo is None:
        # Sin zona horaria explícita: RFC 5322 dice que se asuma local; aquí
        # se asume UTC para que el orden sea determinista entre máquinas.
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_pdf_part(part: Message) -> bool:
    """Indica si una parte MIME es un PDF adjunto.

    Se mira el Content-Type y, como respaldo, la extensión del nombre: algunos
    remitentes mandan los PDF como ``application/octet-stream``.

    Args:
        part: Parte MIME del mensaje.

    Returns:
        ``True`` si la parte parece un PDF.
    """
    content_type = (part.get_content_type() or "").lower()
    if content_type in PDF_CONTENT_TYPES:
        return True
    filename = decode_mime_header(part.get_filename()) or ""
    return filename.lower().endswith(".pdf")


def iter_attachment_parts(msg: Message):
    """Itera las partes MIME que son adjuntos con nombre.

    Args:
        msg: Mensaje ya parseado.

    Yields:
        Cada parte MIME que tenga nombre de fichero o disposición
        ``attachment``.
    """
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        disposition = (part.get_content_disposition() or "").lower()
        if part.get_filename() or disposition == "attachment":
            yield part


def stable_fallback_id(msg: Message) -> str:
    """Genera una clave estable para un correo sin ``Message-ID``.

    Sin Message-ID no hay clave de idempotencia, así que se deriva una a
    partir de headers que no cambian entre ejecuciones.

    Args:
        msg: Mensaje ya parseado.

    Returns:
        Un identificador sintético con la forma ``sha256:<hex12>@local``.
    """
    material = "|".join(
        (msg.get("Date", ""), msg.get("From", ""), msg.get("Subject", ""), msg.get("To", ""))
    )
    digest = hashlib.sha256(material.encode("utf-8", "replace")).hexdigest()[:12]
    return f"sha256:{digest}@local"


def describe_message(msg: Message, uid: str) -> dict:
    """Extrae todos los metadatos relevantes de un mensaje ya parseado.

    Función pura: no toca IMAP, así que se puede testear con mensajes
    sintéticos. Es la base tanto del volcado de la Fase 4 como de
    :meth:`MailClient.fetch_message`.

    Args:
        msg: Mensaje parseado.
        uid: UID IMAP de procedencia.

    Returns:
        Un dict con ``uid``, ``msg_id``, ``subject_raw``, ``subject``,
        ``sender``, ``date_raw``, ``date`` (ISO-8601), ``attachments``
        (lista de dicts) y ``has_pdf``.
    """
    msg_id = (msg.get("Message-ID") or "").strip()
    if not msg_id:
        msg_id = stable_fallback_id(msg)
        log_event("missing_message_id", uid=uid, fallback=msg_id)

    subject_raw = msg.get("Subject") or ""
    date_raw = msg.get("Date") or ""

    attachments = []
    for part in iter_attachment_parts(msg):
        filename = decode_mime_header(part.get_filename()) or "(sin nombre)"
        payload = part.get_payload(decode=True)
        attachments.append(
            {
                "filename": filename,
                "filename_raw": part.get_filename() or "",
                "content_type": part.get_content_type(),
                "size": len(payload) if payload else 0,
                "is_pdf": is_pdf_part(part),
            }
        )

    return {
        "uid": uid,
        "msg_id": msg_id,
        "subject_raw": subject_raw,
        "subject": decode_mime_header(subject_raw),
        "sender": decode_mime_header(msg.get("From")),
        "to": decode_mime_header(msg.get("To")),
        "date_raw": date_raw,
        "date": parse_date(date_raw).isoformat(),
        "attachments": attachments,
        "has_pdf": any(a["is_pdf"] for a in attachments),
    }


def extract_body_text(msg: Message, limit: int = 2000) -> str:
    """Extrae el texto plano del cuerpo, truncado.

    Sirve para inspeccionar dónde aparece el identificador de cuenta cuando no
    está en el asunto. No se usa en el pipeline de la Fase 4.

    Args:
        msg: Mensaje parseado.
        limit: Número máximo de caracteres a devolver.

    Returns:
        El cuerpo en texto plano, truncado a ``limit`` caracteres.
    """
    chunks: list[str] = []
    for part in msg.walk():
        if part.get_content_type() != "text/plain":
            continue
        if (part.get_content_disposition() or "").lower() == "attachment":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        chunks.append(payload.decode(charset, errors="replace"))
    text = "\n".join(chunks).strip()
    return text[:limit]


# -- Cliente IMAP -----------------------------------------------------------


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
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.folder = folder
        self._conn: imaplib.IMAP4_SSL | None = None

    def connect(self, readonly: bool = True) -> imaplib.IMAP4_SSL:
        """Abre la conexión IMAPS, hace login y selecciona la carpeta.

        Args:
            readonly: Si es ``True`` (por defecto) la carpeta se abre con
                ``EXAMINE``, que impide cualquier cambio de flags. Hay que
                pasar ``False`` para poder usar :meth:`mark_as_read`.

        Returns:
            La conexión ``IMAP4_SSL`` ya autenticada.

        Raises:
            MailError: Si falla la conexión, el login o el SELECT.
        """
        try:
            conn = imaplib.IMAP4_SSL(self.host, self.port)
        except OSError as err:
            raise MailError(f"No se pudo conectar a {self.host}:{self.port}: {err}") from err

        try:
            conn.login(self.user, self.password)
        except imaplib.IMAP4.error as err:
            raise MailError(f"Login IMAP rechazado para {self.user}: {err}") from err

        status, data = conn.select(_quote_folder(self.folder), readonly=readonly)
        if status != "OK":
            raise MailError(f"No se pudo seleccionar la carpeta {self.folder!r}: {data}")

        self._conn = conn
        log_event(
            "imap_connected",
            host=self.host,
            user=self.user,
            folder=self.folder,
            readonly=readonly,
        )
        return conn

    def close(self) -> None:
        """Cierra la carpeta y hace logout, ignorando errores de cierre."""
        if self._conn is None:
            return
        try:
            self._conn.close()
        except (imaplib.IMAP4.error, OSError):
            pass
        try:
            self._conn.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
        self._conn = None
        log_event("imap_disconnected")

    def _require_conn(self) -> imaplib.IMAP4_SSL:
        """Devuelve la conexión activa.

        Raises:
            MailError: Si no se ha llamado a :meth:`connect`.
        """
        if self._conn is None:
            raise MailError("No hay conexión IMAP activa; llama antes a connect()")
        return self._conn

    def search_unread(self, sender_domain: str, unread_only: bool = True) -> list[str]:
        """Busca los UIDs de correos no leídos del dominio indicado.

        Args:
            sender_domain: Dominio del remitente (p. ej. ``facebookmail.com``).
            unread_only: Si es ``False`` también devuelve los ya leídos, útil
                sólo para inspeccionar el buzón.

        Returns:
            Lista de UIDs IMAP como cadenas.

        Raises:
            MailError: Si el comando SEARCH falla.
        """
        conn = self._require_conn()
        criteria = ["FROM", f'"{sender_domain}"']
        if unread_only:
            criteria.insert(0, "UNSEEN")

        status, data = conn.uid("SEARCH", None, *criteria)
        if status != "OK":
            raise MailError(f"SEARCH falló: {data}")

        uids = (data[0] or b"").split()
        log_event(
            "imap_search",
            sender_domain=sender_domain,
            unread_only=unread_only,
            found=len(uids),
        )
        return [uid.decode("ascii") for uid in uids]

    def fetch_raw(self, uid: str) -> Message:
        """Descarga un mensaje completo SIN marcarlo como leído.

        Usa ``BODY.PEEK[]``: cualquier otra variante activaría el flag
        ``\\Seen`` y vaciaría la cola de pendientes.

        Args:
            uid: UID IMAP del mensaje.

        Returns:
            El mensaje parseado.

        Raises:
            MailError: Si el FETCH falla o devuelve algo inesperado.
        """
        conn = self._require_conn()
        status, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
        if status != "OK":
            raise MailError(f"FETCH falló para uid={uid}: {data}")

        for item in data:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                return email.message_from_bytes(item[1])
        raise MailError(f"FETCH devolvió una respuesta inesperada para uid={uid}")

    def describe(self, uid: str) -> dict:
        """Devuelve los metadatos crudos de un mensaje.

        Args:
            uid: UID IMAP del mensaje.

        Returns:
            El dict de :func:`describe_message`.
        """
        return describe_message(self.fetch_raw(uid), uid)

    def fetch_message(self, uid: str) -> InvoiceMessage | None:
        """Descarga un mensaje y extrae sus metadatos.

        Args:
            uid: UID IMAP del mensaje.

        Returns:
            El :class:`InvoiceMessage` correspondiente, o ``None`` si el
            mensaje no tiene ningún adjunto PDF.
        """
        info = self.describe(uid)
        if not info["has_pdf"]:
            log_event("skipped_no_pdf", uid=uid, subject=info["subject"])
            return None
        return InvoiceMessage(
            msg_id=info["msg_id"],
            uid=uid,
            subject=info["subject"],
            sender=info["sender"],
            date=parse_date(info["date_raw"]),
            attachment_names=[a["filename"] for a in info["attachments"]],
        )

    def list_candidates(self, sender_domain: str) -> list[InvoiceMessage]:
        """Devuelve los correos candidatos ordenados por ``Date`` ascendente.

        Args:
            sender_domain: Dominio del remitente esperado.

        Returns:
            Lista de :class:`InvoiceMessage` en orden cronológico ascendente.
        """
        messages = []
        for uid in self.search_unread(sender_domain):
            message = self.fetch_message(uid)
            if message is not None:
                messages.append(message)
        # El orden cronológico es requisito del proyecto: el UID no sirve,
        # porque refleja el orden de llegada al buzón, no el header Date.
        messages.sort(key=lambda m: (m.date, m.uid))
        return messages

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

        Sólo debe llamarse DESPUÉS de commitear en el ledger, y requiere que
        la conexión se haya abierto con ``readonly=False``.

        Args:
            uid: UID IMAP del mensaje.

        Raises:
            MailError: Si el STORE falla.
        """
        conn = self._require_conn()
        status, data = conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
        if status != "OK":
            raise MailError(f"STORE \\Seen falló para uid={uid}: {data}")
        log_event("marked_read", uid=uid)

    def __enter__(self) -> "MailClient":
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def _quote_folder(folder: str) -> str:
    """Entrecomilla el nombre de carpeta si lleva espacios.

    Args:
        folder: Nombre de la carpeta (p. ej. ``[Gmail]/All Mail``).

    Returns:
        El nombre listo para pasar a ``SELECT``.
    """
    if folder.startswith('"') and folder.endswith('"'):
        return folder
    return f'"{folder}"' if " " in folder else folder


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


if __name__ == "__main__":
    # FASE 4 — Volcado de inspección. ESTRICTAMENTE DE SÓLO LECTURA:
    # carpeta abierta con EXAMINE y cuerpos leídos con BODY.PEEK[]. Ningún
    # correo cambia de estado.
    #
    #   python src/mail.py                 -> no leídos de facebookmail.com
    #   python src/mail.py --all           -> incluye también los ya leídos
    #   python src/mail.py --body          -> añade el cuerpo en texto plano
    #   python src/mail.py --limit 5       -> como mucho 5 correos
    #
    # Pega la salida tal cual: de ahí sale el regex del act_id en la Fase 5.
    import argparse
    import os
    import sys

    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="Volcado de correos candidatos (sólo lectura)")
    parser.add_argument("--all", action="store_true", help="incluir también los ya leídos")
    parser.add_argument("--body", action="store_true", help="volcar el cuerpo en texto plano")
    parser.add_argument("--limit", type=int, default=0, help="máximo de correos a volcar")
    parser.add_argument("--body-chars", type=int, default=2000, help="caracteres de cuerpo")
    args = parser.parse_args()

    host = os.getenv("IMAP_HOST", "")
    port = int(os.getenv("IMAP_PORT", "993"))
    user = os.getenv("IMAP_USER", "")
    password = os.getenv("IMAP_PASSWORD", "")
    folder = os.getenv("IMAP_FOLDER", "INBOX")
    sender_domain = os.getenv("SENDER_DOMAIN", "facebookmail.com")

    if not (host and user and password):
        print(
            "Faltan IMAP_HOST / IMAP_USER / IMAP_PASSWORD. "
            "Copia .env.example a .env y rellénalo.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    client = MailClient(host, port, user, password, folder)
    try:
        client.connect(readonly=True)
        uids = client.search_unread(sender_domain, unread_only=not args.all)
        if args.limit > 0:
            uids = uids[: args.limit]

        descriptions = []
        for message_uid in uids:
            raw_message = client.fetch_raw(message_uid)
            info = describe_message(raw_message, message_uid)
            if args.body:
                info["body_text"] = extract_body_text(raw_message, args.body_chars)
            descriptions.append(info)

        # Orden cronológico ascendente, igual que el pipeline real.
        descriptions.sort(key=lambda d: (d["date"], d["uid"]))
        for info in descriptions:
            log_event("candidate", **info)

        log_event(
            "dump_done",
            total=len(descriptions),
            con_pdf=sum(1 for d in descriptions if d["has_pdf"]),
            sin_pdf=sum(1 for d in descriptions if not d["has_pdf"]),
        )
    except MailError as err:
        log_event("mail_error", error=str(err))
        raise SystemExit(1) from err
    finally:
        client.close()

    raise SystemExit(0)
