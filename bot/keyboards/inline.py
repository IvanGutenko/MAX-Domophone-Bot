from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types.attachments.buttons import LinkButton, CallbackButton, MessageButton

from bot.config import CONSENT_BUTTON_TEXT, DISPATCHERS


def get_product_keyboard(url: str):
    builder = InlineKeyboardBuilder()
    builder.row(LinkButton(text="Перейти", url=url))
    return builder.as_markup()


def get_consent_keyboard(pdf_url: str):
    """Ссылка на политику (PDF) + кнопка «Принимаю» (отправляет текстом в чат)."""
    builder = InlineKeyboardBuilder()
    builder.row(LinkButton(text="Политика конфиденциальности", url=pdf_url))
    builder.row(MessageButton(text=CONSENT_BUTTON_TEXT))
    return builder.as_markup()


def get_dispatcher_approve_keyboard(request_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="Принять", payload=f"approve_{request_id}"),
        CallbackButton(text="Отклонить (Долг)", payload=f"reject_{request_id}"),
    )
    builder.row(
        CallbackButton(text="💬 Написать", payload=f"chat_{request_id}")
    )
    return builder.as_markup()


def get_resident_pick_dispatcher_keyboard(request_id: int):
    """Кнопки выбора диспетчера для переписки по заявке (callback relay_pick_<request_id>_<user_id>)."""
    builder = InlineKeyboardBuilder()
    for uid, name in DISPATCHERS:
        label = name if len(name) <= 120 else (name[:117] + "...")
        builder.row(
            CallbackButton(text=label, payload=f"relay_pick_{request_id}_{uid}")
        )
    builder.row(MessageButton(text="Назад в главное меню"))
    return builder.as_markup()
