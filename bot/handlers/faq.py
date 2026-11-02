import logging
from maxapi.enums.parse_mode import ParseMode
from maxapi.types import MessageCallback, MessageCreated

from bot.config import (
    PERSONAL_ACCOUNT_URL,
    SERVICES_PAGE_URL,
    CCTV_INSTALL_URL,
    SMART_INTERCOM_ABONENT_CONNECT_REPLY_HTML,
    SMART_INTERCOM_DOM_CONNECT_REPLY_HTML,
    VIDEODOMOFON_INSTALL_URL,
)
from bot.keyboards.reply import get_back_to_menu_keyboard, get_write_manager_followup_keyboard
from bot.utils import get_message_text, normalize_menu_text

logger = logging.getLogger(__name__)

# Все ответы в HTML: ссылки только внутри слов («Подробнее», «Перейти», и т.д.).
FAQ_ANSWERS = {
    "Как оплатить абонентскую плату без комиссии": (
        "Оплатить абонентскую плату без комиссии можно:\n"
        f'• В <a href="{PERSONAL_ACCOUNT_URL}">личном кабинете на сайте</a>\n'
        "• Через банковское приложение по реквизитам\n"
        "• В офисе компании\n\n"
        f'<a href="{PERSONAL_ACCOUNT_URL}">Подробнее</a>'
    ),
    "Что делать если квитанция пришла с задолженностью?": (
        "Если в квитанции указана задолженность:\n"
        f'1. Проверьте сумму в <a href="{PERSONAL_ACCOUNT_URL}">личном кабинете</a>\n'
        "2. Свяжитесь с нами для уточнения\n"
        "3. При наличии задолженности оплатите её\n\n"
        "Телефон: 8 (496) 567-09-19\n\n"
        f'<a href="{PERSONAL_ACCOUNT_URL}">Подробнее на сайте</a>'
    ),
    "Как перейти на обслуживание в вашу компанию?": (
        "Для перехода на обслуживание:\n"
        "1. Позвоните: 8 (496) 567-09-19\n"
        "2. Мы подготовим договор\n"
        "3. Произведём замену оборудования при необходимости\n\n"
        "Переход возможен при наличии технической возможности.\n\n"
        f'<a href="{SERVICES_PAGE_URL}">Перейти на обслуживание</a>'
    ),
    "Как установить видеодомофон?": (
        f'<a href="{VIDEODOMOFON_INSTALL_URL}">Перейти</a> в раздел услуг на сайте — там информация по установке видеодомофона.'
    ),
    "Как установить систему видеонаблюдения?": (
        f'<a href="{CCTV_INSTALL_URL}">Перейти</a> в раздел услуг на сайте — там информация по видеонаблюдению.'
    ),
    "Как подключиться к системе умный домофон": SMART_INTERCOM_ABONENT_CONNECT_REPLY_HTML,
    "Как подключить дом к системе умный домофон?": SMART_INTERCOM_DOM_CONNECT_REPLY_HTML,
}


def faq_key_for_user_text(text: str) -> str | None:
    nt = normalize_menu_text(text)
    for k in FAQ_ANSWERS:
        if normalize_menu_text(k) == nt:
            return k
    return None


async def handle_faq(
    event: MessageCreated | MessageCallback, *, question_key: str | None = None
):
    text = (get_message_text(event.message) or "").strip()
    key = question_key or faq_key_for_user_text(text)

    if key and key in FAQ_ANSWERS:
        if key in (
            "Как подключить дом к системе умный домофон?",
            "Как подключиться к системе умный домофон",
        ):
            attachments = [get_write_manager_followup_keyboard()]
        else:
            attachments = [get_back_to_menu_keyboard()]
        await event.message.answer(
            text=FAQ_ANSWERS[key],
            attachments=attachments,
            format=ParseMode.HTML,
            disable_link_preview=True,
        )
    else:
        logger.warning("FAQ text not found in dictionary: '%s' (len: %d)", text, len(text))
