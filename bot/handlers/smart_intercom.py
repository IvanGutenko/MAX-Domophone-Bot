from maxapi.enums.parse_mode import ParseMode
from maxapi.types import MessageCallback, MessageCreated

from bot.config import SMART_INTERCOM_ABOUT_URL, SMART_INTERCOM_DOM_CONNECT_REPLY_HTML
from bot.keyboards.reply import get_smart_intercom_menu_keyboard, get_write_manager_followup_keyboard
from bot.utils import get_message_text, normalize_menu_text

# HTML: ссылка на сайт только на слове «Подробнее».
SMART_INTERCOM_ANSWERS_HTML = {
    "Что такое умный домофон": (
        "Умный домофон — это современная система, которая позволяет:\n"
        "• Открывать дверь через смартфон\n"
        "• Видеть кто звонит в видео\n"
        "• Принимать вызовы удалённо\n"
        "• Подключаться к подъездной системе\n\n"
        f'<a href="{SMART_INTERCOM_ABOUT_URL}">Подробнее</a>'
    ),
    "Как подключить дом к системе УД": SMART_INTERCOM_DOM_CONNECT_REPLY_HTML,
}


def _smart_intercom_key(text: str) -> str | None:
    nt = normalize_menu_text(text)
    for k in SMART_INTERCOM_ANSWERS_HTML:
        if normalize_menu_text(k) == nt:
            return k
    return None


async def handle_smart_intercom(event: MessageCreated | MessageCallback) -> bool:
    text = (get_message_text(event.message) or "").strip()
    key = _smart_intercom_key(text)

    if key:
        if key == "Как подключить дом к системе УД":
            kb = get_write_manager_followup_keyboard()
        else:
            kb = get_smart_intercom_menu_keyboard()
        await event.message.answer(
            text=SMART_INTERCOM_ANSWERS_HTML[key],
            attachments=[kb],
            format=ParseMode.HTML,
            disable_link_preview=True,
        )
        return True
    return False
