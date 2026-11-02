"""Вспомогательные функции для сообщений maxapi."""

from __future__ import annotations

from maxapi.enums.attachment import AttachmentType


def get_message_text(message) -> str | None:
    if message.body is None:
        return None
    return message.body.text


def first_attachment_of_type(message, attachment_type: AttachmentType):
    if message.body is None or not message.body.attachments:
        return None
    want = attachment_type.value
    for att in message.body.attachments:
        t = getattr(att, "type", None)
        if t == attachment_type:
            return att
        tv = t if isinstance(t, str) else getattr(t, "value", None)
        if tv == want:
            return att
    return None


def audio_attachment(message):
    return first_attachment_of_type(message, AttachmentType.AUDIO)


def image_attachment(message):
    return first_attachment_of_type(message, AttachmentType.IMAGE)


_FORWARD_MEDIA_TYPES = frozenset(
    {AttachmentType.IMAGE, AttachmentType.FILE, AttachmentType.AUDIO}
)


def forwardable_media_attachments(message) -> list:
    """Вложения image/file/audio для пересылки диспетчеру (без клавиатур и прочего)."""
    if message.body is None or not message.body.attachments:
        return []
    out: list = []
    for att in message.body.attachments:
        t = getattr(att, "type", None)
        if t in _FORWARD_MEDIA_TYPES:
            out.append(att)
            continue
        tv = t.value if hasattr(t, "value") else None
        if tv in ("image", "file", "audio"):
            out.append(att)
    return out


def normalize_menu_text(s: str | None) -> str:
    """
    Сопоставление текста с подписями кнопок меню: пробелы, невидимые символы,
    «умные» кавычки, лишние знаки в конце (? ! …), регистр.
    """
    if not s:
        return ""
    t = s.strip()
    for ch in ("\u00ad", "\u200b", "\u200c", "\u200d", "\ufeff"):
        t = t.replace(ch, "")
    t = (
        t.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )
    while t and t[-1] in ".?!…":
        t = t[:-1].rstrip()
    return t.casefold()


def attachment_ref_for_db(att) -> str:
    """Строка для логирования (URL/токен из payload)."""
    if att is None:
        return ""
    payload = getattr(att, "payload", None)
    if payload is None:
        return str(att.type)
    url = getattr(payload, "url", None)
    token = getattr(payload, "token", None)
    if url:
        return url
    if token:
        return f"token:{token}"
    return str(payload)


def audio_attachment_for_resend(ref: str):
    """
    Восстановить вложение audio для повторной отправки (уведомление диспетчеру и т.д.)
    по строке из БД: URL или «token:…».
    """
    if not ref or not isinstance(ref, str):
        return None
    ref = ref.strip()
    try:
        from maxapi.enums.attachment import AttachmentType
        from maxapi.types.attachments.attachment import OtherAttachmentPayload
        from maxapi.types.attachments.audio import Audio

        if ref.startswith("http://") or ref.startswith("https://"):
            return Audio(
                type=AttachmentType.AUDIO,
                payload=OtherAttachmentPayload(url=ref, token=None),
            )
        if ref.startswith("token:"):
            tok = ref[6:].strip()
            if tok:
                return Audio(
                    type=AttachmentType.AUDIO,
                    payload=OtherAttachmentPayload(url="", token=tok),
                )
    except Exception:
        return None
    return None
