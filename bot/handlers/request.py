from maxapi.types import MessageCreated

from bot import db
from bot.config import DISPATCHERS
from bot.fsm.states import user_state, RequestState
from bot.fsm.request import (
    handle_request_fsm,
    handle_voice_submit,
    start_request_text,
    start_request_voice,
)
from bot.handlers.dispatcher import notify_dispatcher_new_request
from bot.handlers.start import _user_id
from bot.keyboards.reply import (
    get_back_to_menu_keyboard,
    get_main_menu_keyboard,
    get_request_type_keyboard,
    get_cancel_keyboard,
)
from bot.utils import audio_attachment, get_message_text


async def handle_request_type(event: MessageCreated):
    user_id = _user_id(event.from_user)
    text = get_message_text(event.message) or ""

    if text == "Написать текстом":
        await start_request_text(event)
        await event.message.answer(
            text="Укажите полный адрес, Город, улица, дом, квартира:",
            attachments=[get_cancel_keyboard()],
        )
    elif text == "Записать голосовое":
        await start_request_voice(event)
        await event.message.answer(
            text=(
                "Пожалуйста, продиктуйте в одном голосовом сообщении ваш полный адрес "
                "(город, улица, дом) и подробно опишите проблему"
            ),
            attachments=[get_cancel_keyboard()],
        )
    elif text == "Отмена":
        user_state.clear(user_id)
        await event.message.answer(
            text="Заявка отменена.",
            attachments=[get_main_menu_keyboard()],
        )
    else:
        await event.message.answer(
            text="Выберите способ кнопкой ниже или нажмите «Отмена».",
            attachments=[get_request_type_keyboard()],
        )


async def handle_request_text(event: MessageCreated):
    user_id = _user_id(event.from_user)
    state = user_state.get_state(user_id)
    text = get_message_text(event.message) or ""

    if text in ("Отмена", "Назад в главное меню"):
        user_state.clear(user_id)
        await event.message.answer(
            text="Заявка отменена.",
            attachments=[get_main_menu_keyboard()],
        )
        return

    if state == RequestState.AWAITING_VOICE:
        await event.message.answer(
            text="Ожидается голосовое сообщение. Запишите адрес и проблему одним сообщением.",
            attachments=[get_cancel_keyboard()],
        )
        return

    result, action = await handle_request_fsm(event)

    if action == "main_menu":
        await event.message.answer(
            text="Возвращаю в главное меню.",
            attachments=[get_main_menu_keyboard()],
        )
        return

    if action == "ask_description":
        await event.message.answer(
            text="Что не работает:",
            attachments=[get_cancel_keyboard()],
        )
    elif action == "ask_phone":
        await event.message.answer(
            text="Укажите номер телефона для связи (с кодом страны или города, как вам удобно):",
            attachments=[get_cancel_keyboard()],
        )
    elif action == "invalid_phone":
        await event.message.answer(
            text="Номер не может быть пустым. Введите телефон текстом:",
            attachments=[get_cancel_keyboard()],
        )
    elif action == "submit_request":
        await submit_request(event, result)


async def handle_voice_message(event: MessageCreated):
    user_id = _user_id(event.from_user)
    if user_state.get_state(user_id) != RequestState.AWAITING_VOICE:
        return

    if not audio_attachment(event.message):
        await event.message.answer(
            text="Пожалуйста, отправьте голосовое сообщение с адресом и описанием проблемы.",
            attachments=[get_cancel_keyboard()],
        )
        return

    data, action = await handle_voice_submit(event)
    if action == "no_audio":
        await event.message.answer(
            text="Не удалось прочитать аудио. Отправьте голосовое ещё раз.",
            attachments=[get_cancel_keyboard()],
        )
        return
    if action == "ask_phone":
        await event.message.answer(
            text="Укажите номер телефона для связи (с кодом страны или города, как вам удобно):",
            attachments=[get_cancel_keyboard()],
        )
        return


async def submit_request(event: MessageCreated, data: dict):
    user_id = _user_id(event.from_user)
    u = event.from_user
    display_name = (u.username and f"@{u.username}") or u.first_name or str(user_id)

    request_id = await db.save_request(
        user_id=user_id,
        request_type=data.get("request_type", "text"),
        city=data.get("address", "") or data.get("city", ""),
        street=data.get("street", ""),
        house_apartment=data.get("house", ""),
        description=data.get("description", ""),
        phone=data.get("phone", "") or "",
        audio_file_id=data.get("audio_file_id"),
    )

    bot = event.message.bot
    notified = False
    if bot:
        notified = await notify_dispatcher_new_request(
            bot,
            request_id,
            user_id=user_id,
            display_name=display_name,
            request_type=data.get("request_type", "text"),
            city=data.get("address", "") or data.get("city", ""),
            street=data.get("street", ""),
            house_apartment=data.get("house", ""),
            description=data.get("description", ""),
            phone=data.get("phone", "") or "",
            audio_ref=data.get("audio_file_id", "") or "",
            voice_attachment=data.get("voice_attachment"),
        )

    if DISPATCHERS:
        if notified:
            thanks = (
                "Спасибо! Заявка отправлена диспетчерам на рассмотрение. "
                "Ожидайте ответа. Написать по заявке можно через пункт меню «Сообщение диспетчеру»."
            )
        else:
            thanks = (
                "Заявка сохранена. Уведомить диспетчеров в MAX не удалось "
                "(у каждого должен быть открыт личный чат с ботом). "
                "Позвоните в офис: 8 (496) 567-09-19 или откройте бота у диспетчера и подайте заявку снова."
            )
        attachments = [get_back_to_menu_keyboard()]
    else:
        if notified:
            thanks = (
                "Спасибо! Заявка отправлена диспетчеру на рассмотрение. Ожидайте решения."
            )
        else:
            thanks = (
                "Заявка сохранена. Сейчас не удалось уведомить диспетчера в MAX "
                "(нет личного чата бота с диспетчером). Попросите диспетчера один раз открыть этого бота "
                "и написать ему сообщение, затем подайте заявку снова или позвоните в офис."
            )
        attachments = [get_back_to_menu_keyboard()]

    await event.message.answer(
        text=thanks,
        attachments=attachments,
    )
