from maxapi.types import MessageCreated

from bot.config import DISPATCHER_USER_IDS
from bot.handlers.dispatcher import forward_media_to_dispatchers
from bot.fsm.states import user_state
from bot.handlers.start import _user_id
from bot.keyboards.reply import get_back_to_menu_keyboard
from bot.utils import forwardable_media_attachments


async def handle_photo_received(event: MessageCreated):
    user_id = _user_id(event.from_user)
    bot = event.message.bot
    atts = forwardable_media_attachments(event.message)
    forwarded = False
    if bot and atts and DISPATCHER_USER_IDS:
        intro = f"[Фото или файл документа от пользователя id {user_id}]"
        forwarded = await forward_media_to_dispatchers(
            bot, intro_text=intro, attachments=atts
        )

    if forwarded:
        reply = (
            "Спасибо! Фото или файл получены и переданы диспетчеру. "
            "При необходимости с вами свяжутся."
        )
    elif atts and DISPATCHER_USER_IDS:
        reply = (
            "Файл получен, но не удалось передать диспетчеру в MAX. "
            "Позвоните в офис: 8 (496) 567-09-19 или напишите через «Сообщение диспетчеру»."
        )
    else:
        reply = (
            "Спасибо! Фото получено. Мы обработаем обращение и свяжемся с вами при необходимости."
        )

    await event.message.answer(
        text=reply,
        attachments=[get_back_to_menu_keyboard()],
    )
    user_state.clear(user_id)
