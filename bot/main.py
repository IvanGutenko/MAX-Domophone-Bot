import asyncio
import logging
import re
import sys

from maxapi import Bot, Dispatcher
from maxapi.client.default import DefaultConnectionProperties
from maxapi.filters.command import Command
from maxapi.types import BotStarted, MessageCallback, MessageCreated

from bot.config import BOT_TOKEN, CONSENT_BUTTON_TEXT
from bot.fsm.states import RequestState, user_state
from bot.keyboards.reply import REQUEST_TYPE_CHOICE_TEXTS
from bot.middleware_dedupe import DedupeUpdatesMiddleware
from bot.handlers.smart_intercom import handle_smart_intercom
from bot.handlers.start import _user_id
from bot.utils import (
    audio_attachment,
    forwardable_media_attachments,
    get_message_text,
    normalize_menu_text,
)

sys.stdout.reconfigure(line_buffering=True)
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise RuntimeError("Укажите BOT_TOKEN в файле .env в каталоге domophone_bot")

# GET /updates: maxapi.Dispatcher.start_polling не передаёт limit/timeout.
# Явно задаём их по документации MAX (limit до 1000, timeout до 90 с) — иначе на части
# окружений приходит мало событий за один ответ, а короткий long poll чаще рвётся
# (на Windows типично WinError 121 «таймаут семафора»).
_POLL_UPDATES_LIMIT = 100
_POLL_UPDATES_TIMEOUT = 30
_HTTP_CLIENT_TOTAL_S = 60.0

bot = Bot(
    token=BOT_TOKEN,
    default_connection=DefaultConnectionProperties(
        timeout=_HTTP_CLIENT_TOTAL_S,
        sock_connect=60,
    ),
)

_orig_get_updates = bot.get_updates


async def _get_updates_with_polling_defaults(
    limit: int | None = None,
    timeout: int | None = None,
    marker: int | None = None,
    types=None,
):
    return await _orig_get_updates(
        limit=limit if limit is not None else _POLL_UPDATES_LIMIT,
        timeout=timeout if timeout is not None else _POLL_UPDATES_TIMEOUT,
        marker=marker,
        types=types,
    )


bot.get_updates = _get_updates_with_polling_defaults  # type: ignore[method-assign]

dp = Dispatcher()

dp.outer_middleware(DedupeUpdatesMiddleware())

_start_command = Command("start")

_REQUEST_STATES_BLOCKING_MENU = frozenset(
    {
        RequestState.AWAITING_TYPE,
        RequestState.AWAITING_ADDRESS,
        RequestState.AWAITING_DESCRIPTION,
        RequestState.AWAITING_PHONE,
        RequestState.AWAITING_VOICE,
        RequestState.AWAITING_DOCUMENT_UPLOAD,
    }
)


def _interrupt_texts_for_request_wizard(faq_keys: frozenset[str], shop_keys: frozenset[str]):
    from bot.keyboards.reply import MAIN_MENU_BUTTON_TEXTS

    return (
        MAIN_MENU_BUTTON_TEXTS
        | faq_keys
        | shop_keys
        | frozenset(
            {
                "Частые вопросы",
                "Как подключить дом к системе УД",
                "Сообщение диспетчеру",
            }
        )
    )


def _menu_text_resets_request_wizard(
    state: RequestState,
    text: str,
    *,
    interrupt_texts: frozenset[str],
) -> bool:
    """True — выйти из мастера заявки и обработать текст как пункт меню (кнопка MAX)."""
    if state not in _REQUEST_STATES_BLOCKING_MENU:
        return False
    t = (text or "").strip()
    if not t:
        return False
    if state == RequestState.AWAITING_TYPE and t in REQUEST_TYPE_CHOICE_TEXTS:
        return False
    nt = normalize_menu_text(t)
    norm_interrupt = {normalize_menu_text(x) for x in interrupt_texts}
    return nt in norm_interrupt


@dp.bot_started()
async def on_bot_started(event: BotStarted):
    from bot.handlers import start

    await start.handle_bot_started(event)


@dp.message_callback()
async def handle_callback(event: MessageCallback):
    """Callback: заявки диспетчера (approve/reject) или нажатия кнопок клавиатуры меню."""
    from bot.handlers import dispatcher

    payload = (event.callback.payload or "").strip() if event.callback else ""

    # MAX API: в ответ на callback обязателен `message` или `notification`.
    # Кнопки диспетчера подтверждаются один раз в handle_dispatcher_callback.
    bot_instance = event._ensure_bot()
    if event.callback and event.callback.callback_id:
        if not re.match(r"^(approve|reject)_", payload):
            try:
                await bot_instance.send_callback(
                    callback_id=event.callback.callback_id,
                    notification=" ",
                )
            except Exception as e:
                logger.warning("Не удалось подтвердить callback: %s", e)

    if re.match(r"^(approve|reject)_", payload):
        await dispatcher.handle_dispatcher_callback(event)
        return

    if re.match(r"^relay_pick_\d+_\d+$", payload):
        await dispatcher.handle_resident_relay_pick(event)
        return

    if not payload:
        return

    if event.message is None or event.message.body is None:
        logger.warning("message_callback без message/body — меню не обработать")
        return

    old_text = event.message.body.text
    event.message.body.text = payload
    try:
        await dispatch_incoming_text(event, payload)
    finally:
        event.message.body.text = old_text


@dp.message_created()
async def handle_all_messages(event: MessageCreated):
    from bot.handlers import menu

    user_id = _user_id(event.from_user)
    text_raw = get_message_text(event.message)
    text = (text_raw or "").strip()

    if not text:
        from bot.config import DISPATCHER_USER_IDS
        from bot.handlers import request
        from bot.handlers.dispatcher import (
            handle_relay_dispatcher_message,
            handle_relay_resident_media,
            reject_pending,
            relay_by_dispatcher,
            relay_by_resident,
        )

        media_atts = forwardable_media_attachments(event.message)
        if media_atts and DISPATCHER_USER_IDS and user_id in relay_by_resident:
            if await handle_relay_resident_media(event, media_atts):
                return

        if user_id in DISPATCHER_USER_IDS:
            if user_id in reject_pending:
                await event.message.answer(
                    text="Отправьте причину отказа обычным текстом (или «-» для шаблона о задолженности)."
                )
                return
            if user_id in relay_by_dispatcher:
                if media_atts and await handle_relay_dispatcher_message(event):
                    return
                await event.message.answer(
                    text="Для пересылки заявителю отправьте текст, фото, файл или голосовое."
                )
                return

        st = user_state.get_state(user_id)
        if st == RequestState.AWAITING_VOICE and audio_attachment(event.message):
            await request.handle_voice_message(event)
        elif st == RequestState.AWAITING_DOCUMENT_UPLOAD and forwardable_media_attachments(
            event.message
        ):
            await menu.handle_photo_received(event)
        return

    await dispatch_incoming_text(event, text)


async def dispatch_incoming_text(event: MessageCreated | MessageCallback, text: str):
    """Общая логика для текста из сообщения и для текста с кнопки (message_callback)."""
    from bot import db
    from bot.config import DISPATCHER_USER_IDS
    from bot.handlers import dispatcher, faq, request, shop, start
    from bot.handlers.faq import FAQ_ANSWERS
    from bot.keyboards.reply import (
        get_back_to_menu_keyboard,
        get_faq_keyboard,
        get_main_menu_keyboard,
        get_request_type_keyboard,
        get_shop_menu_keyboard,
        get_smart_intercom_menu_keyboard,
        get_cancel_keyboard,
    )

    if event.from_user is None:
        logger.warning("Событие без from_user, пропуск")
        return

    user_id = _user_id(event.from_user)

    if DISPATCHER_USER_IDS:
        from bot.handlers.dispatcher import (
            handle_relay_dispatcher_message,
            handle_relay_resident_message,
            relay_by_resident,
        )

        # Сначала проверяем, не является ли пользователь диспетчером.
        # Это важно, если диспетчер подал заявку «сам себе» для теста.
        if isinstance(event, MessageCreated) and user_id in DISPATCHER_USER_IDS:
            if await dispatcher.handle_dispatcher_reject_message(event):
                return
            
            # Команда /chat [ID] для быстрого возобновления диалога
            if text.startswith("/chat"):
                parts = text.split()
                if len(parts) > 1 and parts[1].isdigit():
                    await dispatcher.handle_dispatcher_chat_resume(event, int(parts[1]))
                    return
                else:
                    await event.message.answer(text="Использование: /chat <номер_заявки>")
                    return

            if await handle_relay_dispatcher_message(event):
                return

        if user_id in relay_by_resident:
            # Если житель в режиме переписки, проверяем, не команда ли это (начинается с /)
            # Если команда — пропускаем дальше к старту или меню.
            if text.startswith("/"):
                pass
            else:
                if await handle_relay_resident_message(event):
                    return

    if text and isinstance(event, MessageCreated) and await _start_command(event):
        await start.handle_start(event)
        return

    logger.debug("Incoming text: '%s' (len: %d)", text, len(text))

    if text == CONSENT_BUTTON_TEXT:
        await start.handle_consent_message(event)
        return

    if text == "Начать":
        await start.handle_start(event)
        return

    row = await db.get_user(user_id)
    if not row or not row.get("personal_data_accepted"):
        await start.remind_consent(event)
        return

    nt_nav = normalize_menu_text(text)
    if nt_nav in (
        normalize_menu_text("Отмена"),
        normalize_menu_text("Назад в главное меню"),
    ):
        user_state.clear(user_id)
        await event.message.answer(
            text=(
                "Главное меню:"
                if nt_nav == normalize_menu_text("Назад в главное меню")
                else "Заявка отменена."
            ),
            attachments=[get_main_menu_keyboard()],
        )
        return

    state = user_state.get_state(user_id)

    if state not in (RequestState.NONE, RequestState.SMART_INTERCOM_MENU):
        interrupt = _interrupt_texts_for_request_wizard(
            frozenset(FAQ_ANSWERS.keys()),
            frozenset(shop.CATEGORY_URLS.keys()),
        )
        if _menu_text_resets_request_wizard(state, text, interrupt_texts=interrupt):
            user_state.clear(user_id)
            state = RequestState.NONE

    if state == RequestState.AWAITING_TYPE:
        await request.handle_request_type(event)
        return

    if state == RequestState.AWAITING_VOICE:
        if isinstance(event, MessageCreated) and audio_attachment(event.message):
            await request.handle_voice_message(event)
        else:
            await event.message.answer(
                text="Пожалуйста, отправьте голосовое сообщение или нажмите «Отмена».",
                attachments=[get_cancel_keyboard()]
            )
        return

    if state == RequestState.SMART_INTERCOM_MENU:
        if await handle_smart_intercom(event):
            return
        user_state.clear(user_id)
        state = RequestState.NONE

    if state == RequestState.AWAITING_DOCUMENT_UPLOAD:
        await event.message.answer(
            text=(
                "Ожидается фото или файл документа — отправьте вложением "
                "или нажмите «Назад в главное меню»."
            ),
            attachments=[get_back_to_menu_keyboard()],
        )
        return

    if state != RequestState.NONE:
        await request.handle_request_text(event)
        return

    if normalize_menu_text(text) == normalize_menu_text("Что такое умный домофон"):
        user_state.set_state(user_id, RequestState.SMART_INTERCOM_MENU)
        await event.message.answer(
            text="Выберите раздел:",
            attachments=[get_smart_intercom_menu_keyboard()],
        )
        return

    _nt_write_to_staff = frozenset(
        normalize_menu_text(x)
        for x in (
            "Написать диспетчеру",
            "Сообщение диспетчеру",
            "Написать директору",
        )
    )
    nt_in = normalize_menu_text(text)
    if nt_in in _nt_write_to_staff:
        from bot.config import DISPATCHERS
        from bot.handlers.dispatcher import start_single_dispatcher_relay_for_menu
        from bot.keyboards.inline import get_resident_pick_dispatcher_keyboard

        addressee = "директору" if nt_in == normalize_menu_text("Написать директору") else "диспетчеру"

        if not DISPATCHERS:
            await event.message.answer(
                text="Связь через бот не настроена. Позвоните в офис: 8 (496) 567-09-19.",
                attachments=[get_main_menu_keyboard()],
            )
            return
        rid = await db.get_latest_request_id_for_user(user_id)
        if rid is None:
            await event.message.answer(
                text="Сначала подайте заявку на ремонт через меню — после этого можно написать по заявке.",
                attachments=[get_main_menu_keyboard()],
            )
            return
        if await start_single_dispatcher_relay_for_menu(
            event, request_id=rid, addressee=addressee
        ):
            return
        await event.message.answer(
            text=(
                "Сначала выберите сотрудника кнопкой ниже, затем наберите сообщение "
                "в поле ввода внизу экрана и отправьте.\n\n"
                "Завершить переписку: «Завершить диалог» или /relay_end."
            ),
            attachments=[get_resident_pick_dispatcher_keyboard(rid)],
        )
        return

    faq_key = faq.faq_key_for_user_text(text)
    if faq_key:
        await faq.handle_faq(event, question_key=faq_key)
        return

    if await shop.try_handle_shop(event):
        return

    if normalize_menu_text(text) == normalize_menu_text("Подать заявку на ремонт"):
        user_state.set_state(user_id, RequestState.AWAITING_TYPE)
        await event.message.answer(
            text="Выберите способ подачи заявки:",
            attachments=[get_request_type_keyboard()],
        )
        return

    if normalize_menu_text(text) == normalize_menu_text("Купить ключ от домофона"):
        await shop.send_products(event, "keys")
        return

    if normalize_menu_text(text) == normalize_menu_text(
        "Купить видеодомофон и др. оборудование"
    ):
        await event.message.answer(
            text="Выберите категорию:",
            attachments=[get_shop_menu_keyboard()],
        )
        return

    if normalize_menu_text(text) == normalize_menu_text("Отправить фото документа"):
        user_state.set_state(user_id, RequestState.AWAITING_DOCUMENT_UPLOAD)
        await event.message.answer(
            text=(
                "Вы можете отправить файл или фотографию документа. "
                "Используйте встроенные средства мессенджера MAX."
            ),
            attachments=[get_back_to_menu_keyboard()],
        )
        return

    if normalize_menu_text(text) == normalize_menu_text("Частые вопросы"):
        await event.message.answer(
            text="Выберите вопрос:",
            attachments=[get_faq_keyboard()],
        )
        return


async def main():
    import logging
    from bot import db
    from bot.config import (
        WEBHOOK_URL,
        WEBHOOK_HOST,
        WEBHOOK_PORT,
        WEBHOOK_PATH,
        WEBHOOK_SECRET,
    )

    await db.init_db()
    logger.info("База инициализирована")

    if WEBHOOK_URL:
        logger.info("Запуск в режиме WEBHOOK: %s", WEBHOOK_URL)
        try:
            await bot.subscribe_webhook(url=WEBHOOK_URL, secret=WEBHOOK_SECRET)
            logger.info("Подписка на webhook %s оформлена", WEBHOOK_URL)
        except Exception as e:
            logger.error("Не удалось подписаться на webhook: %s", e)
            # Если не удалось подписаться, возможно стоит упасть или продолжить (если уже подписаны)
        
        await dp.handle_webhook(
            bot=bot,
            host=WEBHOOK_HOST,
            port=WEBHOOK_PORT,
            path=WEBHOOK_PATH,
            secret=WEBHOOK_SECRET,
        )
    else:
        try:
            await bot.delete_webhook()
            logger.info("Подписки webhook сброшены — используется long polling")
        except Exception as e:
            logger.warning("Не удалось сбросить webhook (можно игнорировать при первом запуске): %s", e)

        while True:
            try:
                await dp.start_polling(bot)
            except Exception as e:
                # Ловим исключения типа ContentTypeError (когда MAX отдает HTML вместо JSON при сбоях)
                # или временные разрывы соединения.
                logger.error("Критическая ошибка polling: %s. Повтор через 5 секунд...", e)
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
