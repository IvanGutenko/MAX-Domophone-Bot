from maxapi.enums.parse_mode import ParseMode
from maxapi.types import BotStarted, MessageCallback, MessageCreated

from bot import db
from bot.config import CONSENT_BUTTON_TEXT, FULL_WELCOME_MESSAGE_HTML, PDF_URL
from bot.keyboards.reply import get_main_menu_keyboard
from bot.keyboards.inline import get_consent_keyboard

# Уже показали запрос согласия из handle_bot_started — не дублировать в handle_start
# после автоматического /start или «Начать» от MAX.
_consent_banner_already_shown: set[int] = set()


def _user_id(user) -> int:
    return getattr(user, "user_id", None) or getattr(user, "id")


def consent_prompt_attachments():
    return [
        get_consent_keyboard(PDF_URL),
    ]


async def send_welcome_with_menu(event_message):
    await event_message.answer(
        text=FULL_WELCOME_MESSAGE_HTML,
        attachments=[get_main_menu_keyboard()],
        format=ParseMode.HTML,
        disable_link_preview=True,
    )


async def handle_start(event: MessageCreated | MessageCallback):
    user_id = _user_id(event.from_user)
    name = event.from_user.first_name or ""
    username = event.from_user.username or ""

    await db.create_user(user_id, name, username)
    user = await db.get_user(user_id)

    if not user or not user.get("personal_data_accepted"):
        if user_id in _consent_banner_already_shown:
            await remind_consent(event)
            return
        
        # Mark as shown BEFORE sending to prevent race conditions with handle_bot_started
        _consent_banner_already_shown.add(user_id)
        await event.message.answer(
            text=(
                "Ознакомьтесь с политикой конфиденциальности (кнопка ниже) "
                "и нажмите «Принимаю», чтобы продолжить."
            ),
            attachments=consent_prompt_attachments(),
        )
        return

    await send_welcome_with_menu(event.message)


async def handle_bot_started(event: BotStarted):
    bot = event.bot
    if bot is None:
        return
    user = event.from_user
    user_id = _user_id(user)
    name = user.first_name or ""
    username = user.username or ""

    await db.create_user(user_id, name, username)
    row = await db.get_user(user_id)

    if not row or not row.get("personal_data_accepted"):
        if user_id in _consent_banner_already_shown:
            return
            
        # В MAX после BotStarted почти сразу приходит сообщение /start или «Начать».
        # Чтобы не было дубля, помечаем, что баннер «в процессе» или показан.
        _consent_banner_already_shown.add(user_id)
        
        await bot.send_message(
            chat_id=event.chat_id,
            user_id=user_id,
            text=(
                "Ознакомьтесь с политикой конфиденциальности (кнопка ниже) "
                "и нажмите «Принимаю», чтобы продолжить."
            ),
            attachments=consent_prompt_attachments(),
        )
        return

    # Если уже принял — сразу показываем меню (например, после удаления чата и кнопки "Старт")
    # Используем баннер-флаг, чтобы не дублировать с handle_start, который придет следом.
    if user_id not in _consent_banner_already_shown:
        _consent_banner_already_shown.add(user_id)
        await bot.send_message(
            chat_id=event.chat_id,
            user_id=user_id,
            text=FULL_WELCOME_MESSAGE_HTML,
            attachments=[get_main_menu_keyboard()],
            format=ParseMode.HTML,
            disable_link_preview=True,
        )


async def handle_consent_message(event: MessageCreated | MessageCallback):
    """Пользователь нажал кнопку согласия (приходит как текст)."""
    user_id = _user_id(event.from_user)
    name = event.from_user.first_name or ""
    username = event.from_user.username or ""
    await db.create_user(user_id, name, username)
    await db.update_consent(user_id, accepted=True)
    _consent_banner_already_shown.discard(user_id)
    # Одно сообщение: приветствие + главное меню (без отдельного «Спасибо», чтобы не терялось в MAX)
    await send_welcome_with_menu(event.message)


async def remind_consent(event: MessageCreated | MessageCallback):
    await event.message.answer(
        text="Пожалуйста, примите политику обработки персональных данных, чтобы продолжить.",
        attachments=consent_prompt_attachments(),
    )
