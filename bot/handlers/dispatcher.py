"""
Уведомления диспетчера и обработка кнопок «Принять» / «Отклонить».
Переписка с жителем только через бота.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from maxapi.exceptions.max import MaxApiError, MaxConnection
from maxapi.types import MessageCallback, MessageCreated

MessageEvent = MessageCreated | MessageCallback

from bot import db
from bot.config import (
    DEFAULT_REJECT_DEBT_TEXT,
    DISPATCHER_CHAT_ID,
    DISPATCHERS,
    DISPATCHER_USER_IDS,
)
from bot.handlers.start import _user_id
from bot.keyboards.inline import get_dispatcher_approve_keyboard
from bot.keyboards.reply import (
    MAIN_MENU_BUTTON_TEXTS,
    get_back_to_menu_keyboard,
    get_dispatcher_relay_keyboard,
    get_main_menu_keyboard,
)
from bot.services import cloud
from bot.utils import audio_attachment_for_resend, normalize_menu_text

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from maxapi.bot import Bot

# Диспетчер нажал «Отклонить» — ждём текст причины: dispatcher_user_id -> request_id
reject_pending: dict[int, int] = {}

# Активный диалог после отклонения: dispatcher_id -> (resident_user_id, request_id)
relay_by_dispatcher: dict[int, tuple[int, int]] = {}
# resident_id -> (dispatcher_id, request_id)
relay_by_resident: dict[int, tuple[int, int]] = {}

RELAY_END_PHRASES = frozenset({"Завершить диалог", "🛑 Завершить диалог", "Назад в главное меню", "/relay_end"})

# Сообщения, после которых житель выходит из relay и снова обрабатывается обычное меню.
# «Отправить фото документа» не выходит: иначе relay рвётся, и диспетчер теряет канал к заявителю.
_RELAY_RESIDENT_EXIT_TEXTS = (
    MAIN_MENU_BUTTON_TEXTS - frozenset({"Отправить фото документа"})
) | frozenset(
    {
        "Назад в главное меню",
        "Отмена",
        "Частые вопросы",
        "Сообщение диспетчеру",
    }
)
_RELAY_RESIDENT_EXIT_NORMALIZED: frozenset[str] = frozenset(
    normalize_menu_text(x) for x in _RELAY_RESIDENT_EXIT_TEXTS
)


def _is_relay_end(text: str) -> bool:
    t = (text or "").strip()
    if t in RELAY_END_PHRASES:
        return True
    return t.lower() == "/relay_end"


def _register_relay(dispatcher_id: int, resident_id: int, request_id: int) -> None:
    if dispatcher_id == resident_id:
        # Не включаем пересылку сообщений самому себе
        return
    # Диспетчер теперь "активен" для этого жителя
    relay_by_dispatcher[dispatcher_id] = (resident_id, request_id)
    # Житель "помнит", с каким диспетчером и по какой заявке он говорит
    relay_by_resident[resident_id] = (dispatcher_id, request_id)


def _is_dialog_not_found(err: MaxApiError) -> bool:
    raw = err.raw
    return isinstance(raw, dict) and raw.get("code") == "dialog.not.found"


async def send_message_to_dispatcher_user(
    bot: "Bot",
    dispatcher_user_id: int,
    *,
    text: str,
    attachments: list | None = None,
    disable_link_preview: bool | None = None,
) -> bool:
    """Сообщение одному диспетчеру (пересылка от жителя, уведомления о завершении диалога и т.п.)."""
    kwargs: dict = {"text": text}
    if attachments:
        kwargs["attachments"] = attachments
    if disable_link_preview is not None:
        kwargs["disable_link_preview"] = disable_link_preview
    try:
        await bot.send_message(user_id=dispatcher_user_id, **kwargs)
        return True
    except MaxConnection as e:
        logger.error("Сетевая ошибка при отправке диспетчеру (user_id=%s): %s", dispatcher_user_id, e)
    except MaxApiError as e:
        if _is_dialog_not_found(e):
            logger.warning(
                "Диалог с диспетчером (user_id=%s) не найден: откройте чат с ботом в MAX.",
                dispatcher_user_id,
            )
        else:
            logger.exception("Не удалось отправить сообщение диспетчеру (user_id=%s): %s", dispatcher_user_id, e)
    except Exception as e:
        logger.exception("Непредвиденная ошибка при отправке диспетчеру (user_id=%s): %s", dispatcher_user_id, e)
    return False


async def broadcast_new_request_to_dispatchers(
    bot: "Bot",
    *,
    text: str,
    attachments: list | None = None,
) -> bool:
    """
    Уведомление о новой заявке всем диспетчерам.
    Если диспетчер один и задан DISPATCHER_CHAT_ID — сначала пробуем chat_id (как раньше).
    """
    kwargs: dict = {"text": text}
    if attachments:
        kwargs["attachments"] = attachments

    if not DISPATCHER_USER_IDS:
        if DISPATCHER_CHAT_ID is None:
            return False
        try:
            await bot.send_message(chat_id=DISPATCHER_CHAT_ID, **kwargs)
            logger.info("Новая заявка: уведомление отправлено в chat_id=%s", DISPATCHER_CHAT_ID)
            return True
        except MaxConnection as e:
            logger.error("Сетевая ошибка при отправке заявки в чат диспетчера (chat_id=%s): %s", DISPATCHER_CHAT_ID, e)
        except MaxApiError as e:
            if not _is_dialog_not_found(e):
                logger.exception("Не удалось отправить заявку в чат диспетчера (chat_id): %s", e)
        except Exception as e:
            logger.exception("Непредвиденная ошибка при отправке заявки в чат диспетчера (chat_id=%s): %s", DISPATCHER_CHAT_ID, e)
        return False

    if len(DISPATCHERS) == 1:
        uid = DISPATCHERS[0][0]
        # Сначала личный чат диспетчера с ботом — иначе устаревший DISPATCHER_CHAT_ID
        # может «успешно» принять сообщение не туда, куда смотрит диспетчер.
        if await send_message_to_dispatcher_user(bot, uid, text=text, attachments=attachments):
            logger.info("Новая заявка: уведомление отправлено диспетчеру user_id=%s", uid)
            return True
        if DISPATCHER_CHAT_ID is not None:
            try:
                await bot.send_message(chat_id=DISPATCHER_CHAT_ID, **kwargs)
                logger.info(
                    "Новая заявка: уведомление отправлено в chat_id=%s (fallback, user_id=%s недоступен)",
                    DISPATCHER_CHAT_ID,
                    uid,
                )
                return True
            except MaxConnection as e:
                logger.error("Сетевая ошибка при отправке заявки в fallback чат (chat_id=%s): %s", DISPATCHER_CHAT_ID, e)
            except MaxApiError as e:
                if not _is_dialog_not_found(e):
                    logger.exception("Не удалось отправить заявку диспетчеру (chat_id): %s", e)
                else:
                    logger.warning(
                        "Диалог chat_id=%s не найден; user_id=%s тоже недоступен.",
                        DISPATCHER_CHAT_ID,
                        uid,
                    )
            except Exception as e:
                logger.exception("Непредвиденная ошибка при отправке в fallback чат: %s", e)
        return False

    ok_any = False
    for uid, _ in DISPATCHERS:
        if await send_message_to_dispatcher_user(bot, uid, text=text, attachments=attachments):
            logger.info("Новая заявка: уведомление отправлено диспетчеру user_id=%s", uid)
            ok_any = True
    return ok_any


async def forward_media_to_dispatchers(
    bot: "Bot",
    *,
    intro_text: str,
    attachments: list,
) -> bool:
    """Переслать фото/файл всем диспетчерам (п. меню «Отправить фото документа» и т.п.)."""
    if not attachments:
        return False
    if not DISPATCHER_USER_IDS:
        if DISPATCHER_CHAT_ID is None:
            return False
        try:
            await bot.send_message(
                chat_id=DISPATCHER_CHAT_ID,
                text=intro_text,
                attachments=attachments,
            )
            logger.info("Медиа жителя: отправлено в chat_id=%s", DISPATCHER_CHAT_ID)
            return True
        except MaxApiError as e:
            if not _is_dialog_not_found(e):
                logger.exception("Медиа: не удалось отправить в chat_id: %s", e)
            return False

    if len(DISPATCHERS) == 1:
        uid = DISPATCHERS[0][0]
        if await send_message_to_dispatcher_user(
            bot, uid, text=intro_text, attachments=attachments
        ):
            logger.info("Медиа жителя: диспетчер user_id=%s", uid)
            return True
        if DISPATCHER_CHAT_ID is not None:
            try:
                await bot.send_message(
                    chat_id=DISPATCHER_CHAT_ID,
                    text=intro_text,
                    attachments=attachments,
                )
                logger.info(
                    "Медиа жителя: chat_id=%s (fallback, user_id=%s)",
                    DISPATCHER_CHAT_ID,
                    uid,
                )
                return True
            except MaxApiError as e:
                if not _is_dialog_not_found(e):
                    logger.exception("Медиа: не удалось в chat_id: %s", e)
        return False

    ok_any = False
    for uid, _ in DISPATCHERS:
        if await send_message_to_dispatcher_user(
            bot, uid, text=intro_text, attachments=attachments
        ):
            logger.info("Медиа жителя: диспетчер user_id=%s", uid)
            ok_any = True
    return ok_any


async def handle_relay_resident_media(
    event: MessageCreated, attachments: list
) -> bool:
    """Житель в relay прислал фото/файл без текста — переслать выбранному диспетчеру."""
    from bot.fsm.states import RequestState, user_state

    if not attachments or not DISPATCHER_USER_IDS:
        return False
    uid = _user_id(event.from_user)
    if uid not in relay_by_resident:
        return False
    disp_id, request_id = relay_by_resident[uid]
    
    # Проверка: если этот диспетчер больше не существует в списке (крайний случай)
    if disp_id not in DISPATCHER_USER_IDS:
        relay_by_resident.pop(uid, None)
        return False

    bot = event.message.bot
    if not bot:
        await event.message.answer(
            text="Не удалось передать вложение диспетчеру. Попробуйте позже или позвоните в офис.",
            attachments=[get_back_to_menu_keyboard()],
        )
        return True
    intro = (
        f"[Заявка №{request_id}, пользователь id {uid} прислал вложение "
        "(фото, файл или голосовое)]"
    )
    ok = await send_message_to_dispatcher_user(
        bot, disp_id, text=intro, attachments=attachments
    )
    if ok:
        logger.info(
            "Relay: медиа от user_id=%s переслано диспетчеру user_id=%s, заявка #%s",
            uid,
            disp_id,
            request_id,
        )
        await event.message.answer(text="Вложение передано диспетчеру.")
    else:
        await event.message.answer(
            text="Не удалось передать вложение диспетчеру (нет чата бота с диспетчером в MAX).",
            attachments=[get_back_to_menu_keyboard()],
        )
    if user_state.get_state(uid) == RequestState.AWAITING_DOCUMENT_UPLOAD:
        user_state.set_state(uid, RequestState.NONE)
    return True


async def send_message_to_resident(
    bot: "Bot",
    user_id: int,
    text: str,
    *,
    attachments: list | None = None,
    disable_link_preview: bool | None = None,
) -> bool:
    """Личное сообщение заявителю. False, если нет диалога с ботом в MAX."""
    body = (text or "").strip()
    if attachments and not body:
        body = "Вложение от диспетчера"
    if not body and not attachments:
        return False
    try:
        kwargs: dict = {"user_id": user_id, "text": body}
        if attachments:
            kwargs["attachments"] = attachments
        if disable_link_preview is not None:
            kwargs["disable_link_preview"] = disable_link_preview
        await bot.send_message(**kwargs)
        return True
    except MaxConnection as e:
        logger.error("Сетевая ошибка при отправке жителю (user_id=%s): %s", user_id, e)
    except MaxApiError as e:
        if _is_dialog_not_found(e):
            logger.warning(
                "Сообщение пользователю user_id=%s не отправлено: нет диалога с ботом (откройте бота в MAX).",
                user_id,
            )
        else:
            logger.exception("Ошибка отправки пользователю user_id=%s: %s", user_id, e)
    except Exception as e:
        logger.exception("Непредвиденная ошибка при отправке жителю (user_id=%s): %s", user_id, e)
    return False


async def _build_cloud_data_from_request(req: dict) -> dict:
    urow = await db.get_user(req["user_id"])
    if urow:
        un = urow.get("username")
        username = (f"@{un}" if un else None) or urow.get("name") or str(req["user_id"])
    else:
        username = str(req["user_id"])
    return {
        "user_id": req["user_id"],
        "username": username,
        "request_type": req.get("request_type") or "",
        "city": req.get("city") or "",
        "street": req.get("street") or "",
        "house": req.get("house_apartment") or "",
        "phone": req.get("phone") or "",
        "description": req.get("description") or "",
        "audio_file_id": req.get("audio_file_id") or "",
    }


async def notify_dispatcher_new_request(
    bot: Bot,
    request_id: int,
    *,
    user_id: int,
    display_name: str,
    request_type: str,
    city: str,
    street: str,
    house_apartment: str,
    description: str,
    phone: str,
    audio_ref: str,
    voice_attachment=None,
) -> bool:
    if not DISPATCHER_USER_IDS and DISPATCHER_CHAT_ID is None:
        return False

    phone_line = f"Телефон: {phone or '—'}\n"

    if request_type == "voice":
        text = (
            "Новая заявка (голосовая)!\n"
            f"ID заявки: {request_id}\n"
            f"Пользователь: {display_name} (id {user_id})\n"
            f"{phone_line}"
            "Голосовое сообщение — во вложении к этому сообщению (плеер MAX)."
        )
        audio_to_send = voice_attachment or audio_attachment_for_resend(audio_ref)
        if not audio_to_send and audio_ref:
            text = (
                "Новая заявка (голосовая)!\n"
                f"ID заявки: {request_id}\n"
                f"Пользователь: {display_name} (id {user_id})\n"
                f"{phone_line}"
                f"Не удалось прикрепить плеер; откройте ссылку вручную:\n{audio_ref}"
            )
    else:
        text = (
            "Новая заявка!\n"
            f"ID заявки: {request_id}\n"
            f"Пользователь: {display_name} (id {user_id})\n"
            f"{phone_line}"
            f"Город: {city}\n"
            f"Улица: {street}\n"
            f"Дом/кв: {house_apartment}\n"
            f"Проблема: {description}"
        )
        audio_to_send = None

    kb = get_dispatcher_approve_keyboard(request_id)
    if request_type == "voice" and audio_to_send is not None:
        attachments = [audio_to_send, kb]
    else:
        attachments = [kb]

    return await broadcast_new_request_to_dispatchers(
        bot,
        text=text,
        attachments=attachments,
    )


async def handle_dispatcher_callback(event: MessageCallback):
    payload = event.callback.payload or ""
    bot = event._ensure_bot()
    if event.message is not None and event.message.bot is not None:
        bot = event.message.bot

    cid = event.callback.callback_id

    async def ack() -> None:
        if cid:
            try:
                await bot.send_callback(callback_id=cid, notification=" ")
            except Exception as e:
                logger.warning("Не удалось подтвердить callback диспетчера: %s", e)

    if not DISPATCHER_USER_IDS:
        await ack()
        return

    if _user_id(event.from_user) not in DISPATCHER_USER_IDS:
        if event.message is not None:
            await event.message.answer(text="Эти действия доступны только диспетчеру.")
        await ack()
        return

    m = re.match(r"^approve_(\d+)$", payload)
    if m:
        await _handle_approve(event, int(m.group(1)))
        await ack()
        return

    m = re.match(r"^reject_(\d+)$", payload)
    if m:
        await _handle_reject_click(event, int(m.group(1)))
        await ack()
        return

    m = re.match(r"^chat_(\d+)$", payload)
    if m:
        await handle_dispatcher_chat_resume(event, int(m.group(1)))
        await ack()
        return

    await ack()


async def start_single_dispatcher_relay_for_menu(
    event: MessageCreated, *, request_id: int, addressee: str = "диспетчеру"
) -> bool:
    """
    В конфиге ровно один диспетчер — сразу включаем переписку по заявке, без inline-кнопки «Диспетчер».
    addressee: «диспетчеру» или «директору» (для совместимости вызова из меню).
    """
    if addressee == "директору":
        from bot.config import DIRECTOR_USER_ID
        if not DIRECTOR_USER_ID:
            await event.message.answer(
                text="Связь с директором пока не настроена.",
                attachments=[get_main_menu_keyboard()],
            )
            return True
        dispatcher_uid = DIRECTOR_USER_ID
    else:
        if len(DISPATCHERS) != 1:
            return False
        dispatcher_uid, _ = DISPATCHERS[0]
        if dispatcher_uid not in DISPATCHER_USER_IDS:
            return False

    resident_uid = _user_id(event.from_user)
    req = await db.get_request(request_id)
    if not req or req["user_id"] != resident_uid:
        await event.message.answer(text="Заявка не найдена или у вас нет к ней доступа.")
        return True
    bot = event.message.bot
    if not bot:
        await event.message.answer(
            text="Сейчас не удалось связаться с сотрудником через бота. Позвоните в офис: 8 (496) 567-09-19.",
            attachments=[get_main_menu_keyboard()],
        )
        return True
    _register_relay(dispatcher_uid, resident_uid, request_id)
    await event.message.answer(
        text=(
            "Наберите сообщение в поле ввода внизу экрана и отправьте.\n\n"
            "Завершить переписку: «Завершить диалог» или /relay_end."
        ),
        attachments=[get_back_to_menu_keyboard()],
    )
    # Без служебного «открыл переписку» — сотрудник получит первое реальное сообщение заявителя.
    return True


async def handle_resident_relay_pick(event: MessageCallback) -> None:
    """Житель выбрал диспетчера для переписки по заявке (кнопка relay_pick)."""
    payload = (event.callback.payload or "").strip()
    m = re.match(r"^relay_pick_(\d+)_(\d+)$", payload)
    if not m or event.message is None:
        return

    request_id = int(m.group(1))
    dispatcher_uid = int(m.group(2))
    resident_uid = _user_id(event.from_user)

    if dispatcher_uid not in DISPATCHER_USER_IDS:
        await event.message.answer(text="Этот диспетчер недоступен.")
        return

    req = await db.get_request(request_id)
    if not req or req["user_id"] != resident_uid:
        await event.message.answer(text="Заявка не найдена или у вас нет к ней доступа.")
        return

    _register_relay(dispatcher_uid, resident_uid, request_id)
    disp_name = next((n for u, n in DISPATCHERS if u == dispatcher_uid), "диспетчер")
    await event.message.answer(
        text=(
            f"Вы выбрали «{disp_name}». Наберите сообщение в поле ввода внизу и отправьте.\n\n"
            "Завершить переписку: «Завершить диалог» или /relay_end."
        ),
        attachments=[get_back_to_menu_keyboard()],
    )


async def _handle_approve(event: MessageCallback, request_id: int):
    bot = (event.message.bot if event.message else None) or event._ensure_bot()
    disp_id = _user_id(event.from_user) if event.from_user else None
    # Автоматическое переключение: диспетчер теперь будет отвечать этому жителю.
    # Старый житель (если был) остается в relay_by_resident, но диспетчер
    # переключает свой исходящий канал на новую заявку.
    pass

    req = await db.get_request(request_id)
    if not req:
        if event.message is not None:
            await event.message.answer(text="Заявка не найдена.")
        return

    st = req.get("status") or "pending"
    uid = req["user_id"]
    if st == "accepted":
        if event.message is not None:
            await event.message.answer(text="Заявка уже принята.")
        else:
            await bot.send_message(user_id=disp_id, text="Заявка уже принята.")
        # Даже если принята, проверим relay. Если диспетчер нажал снова —
        # возможно он хочет переключиться на эту заявку.
        if disp_id is not None and relay_by_dispatcher.get(disp_id) != (uid, request_id):
             # Переключаем/включаем relay
            _register_relay(disp_id, uid, request_id)
            msg = "Переписка переключена на эту заявку."
            if event.message is not None:
                await event.message.answer(text=msg, attachments=[get_dispatcher_relay_keyboard()])
            else:
                await bot.send_message(user_id=disp_id, text=msg, attachments=[get_dispatcher_relay_keyboard()])
        return
    if st == "rejected":
        if event.message is not None:
            await event.message.answer(text="Заявка уже отклонена.")
        return

    await db.update_request_status(request_id, "accepted")
    cloud_data = await _build_cloud_data_from_request(req)
    await cloud.save_to_cloud(cloud_data)

    uid = req["user_id"]
    ok = await send_message_to_resident(
        bot,
        uid,
        "Ваша заявка принята в работу. Мы свяжемся с вами в ближайшее время.",
    )
    if ok and disp_id is not None:
        _register_relay(disp_id, uid, request_id)

    if event.message is not None:
        if ok:
            await event.message.answer(
                text=(
                    f"Заявка №{request_id} принята и сохранена. Жителю отправлено уведомление.\n"
                    "Ваши следующие сообщения пересылаются заявителю."
                ),
                attachments=[get_dispatcher_relay_keyboard()]
            )
        else:
            await event.message.answer(
                text=(
                    f"Заявка №{request_id} принята и сохранена. Уведомление заявителю не доставлено: "
                    "у него нет активного чата с ботом в MAX (пусть откроет бота и напишет / Начать). "
                    "Режим переписки включен (но сообщения могут не доходить)."
                ),
                attachments=[get_dispatcher_relay_keyboard()]
            )


async def _handle_reject_click(event: MessageCallback, request_id: int):
    disp_id = _user_id(event.from_user)
    # Автоматическое переключение: завершаем текущий диалог перед отклонением новой заявки.
    if disp_id in relay_by_dispatcher:
        pair = relay_by_dispatcher.pop(disp_id, None)
        if pair:
            relay_by_resident.pop(pair[0], None)
            logger.info("Relay завершен автоматически для диспетчера %s перед отклонением заявки #%s", disp_id, request_id)
    reject_pending[disp_id] = request_id
    if event.message is not None:
        await event.message.answer(
            text=(
                f"Заявка №{request_id}. Введите причину отказа для заявителя одним сообщением.\n"
                "Или отправьте «-» для стандартного текста о задолженности."
            )
        )


async def handle_dispatcher_reject_message(event: MessageCreated):
    """Следующее сообщение диспетчера после нажатия «Отклонить» — причина жителю."""
    from bot.utils import get_message_text

    if not DISPATCHER_USER_IDS:
        return False

    bot = event.message.bot
    disp_id = _user_id(event.from_user)
    if disp_id not in DISPATCHER_USER_IDS:
        return False

    request_id = reject_pending.pop(disp_id, None)
    if request_id is None:
        return False

    req = await db.get_request(request_id)
    if not req:
        await event.message.answer(text="Заявка не найдена.")
        return True

    raw = (get_message_text(event.message) or "").strip()
    if raw == "-" or raw == "—":
        reason = DEFAULT_REJECT_DEBT_TEXT
    else:
        reason = raw or DEFAULT_REJECT_DEBT_TEXT

    await db.update_request_status(request_id, "rejected")
    uid = req["user_id"]
    ok = await send_message_to_resident(bot, uid, f"По вашей заявке: {reason}")
    if not ok:
        await event.message.answer(
            text=(
                "Текст отказа не доставлен заявителю (нет диалога с ботом в MAX). "
                "Свяжитесь с ним по телефону из заявки. Режим пересылки в чате не включён."
            )
        )
        return True
    _register_relay(disp_id, uid, request_id)
    await event.message.answer(
        text=(
            "Причина отправлена заявителю. Дальнейшие сообщения пересылаются ему. "
            "Чтобы завершить диалог, отправьте «Завершить диалог» или /relay_end."
        )
    )
    return True


async def handle_relay_dispatcher_message(event: MessageCreated) -> bool:
    """Пересылка текста и вложений диспетчера заявителю. True если событие обработано."""
    from bot.utils import forwardable_media_attachments, get_message_text

    if not DISPATCHER_USER_IDS:
        return False
    disp_id = _user_id(event.from_user)
    if disp_id not in DISPATCHER_USER_IDS:
        return False
    if disp_id not in relay_by_dispatcher:
        return False

    text = (get_message_text(event.message) or "").strip()
    media = forwardable_media_attachments(event.message) or None

    if _is_relay_end(text):
        await end_relay_from_dispatcher(event)
        return True

    if not text and not media:
        if event.message is not None:
            await event.message.answer(
                text="Отправьте заявителю текст, фото, файл или голосовое — этот тип сообщения переслать нельзя."
            )
        return True

    bot = event.message.bot
    resident_id, _ = relay_by_dispatcher[disp_id]
    ok = await send_message_to_resident(bot, resident_id, text, attachments=media)
    if ok:
        await event.message.answer(text="Сообщение отправлено заявителю.")
    else:
        await event.message.answer(
            text="Не удалось доставить сообщение заявителю (нет диалога с ботом у user_id=%s)."
            % resident_id
        )
    return True


def _pop_relay_pair_for_resident(uid: int) -> tuple[int, int] | None:
    """Снять relay для жителя. Вернуть (dispatcher_id, request_id) или None."""
    pair = relay_by_resident.pop(uid, None)
    if pair is None:
        return None
    disp_id, request_id = pair
    # Если этот житель БЫЛ активным собеседником этого диспетчера - убираем и там
    active_pair = relay_by_dispatcher.get(disp_id)
    if active_pair and active_pair[0] == uid:
        relay_by_dispatcher.pop(disp_id, None)
    return disp_id, request_id


async def handle_relay_resident_message(event: MessageEvent) -> bool:
    """Пересылка текста и вложений заявителя диспетчеру. True если событие обработано."""
    from bot.fsm.states import RequestState, user_state
    from bot.utils import forwardable_media_attachments, get_message_text

    if not DISPATCHER_USER_IDS:
        return False
    uid = _user_id(event.from_user)
    if uid not in relay_by_resident:
        return False

    disp_id, request_id = relay_by_resident[uid]
    
    # Если диспетчер почему-то удален из системы
    if disp_id not in DISPATCHER_USER_IDS:
        relay_by_resident.pop(uid, None)
        return False

    text = (get_message_text(event.message) or "").strip()
    media = forwardable_media_attachments(event.message)

    if not text and not media:
        return True

    bot = event.message.bot

    async def _send_media_with_caption() -> bool:
        intro_lines = [f"[Заявка №{request_id}, пользователь id {uid}]"]
        if text:
            intro_lines.append(text)
        intro = "\n".join(intro_lines)
        ok_m = await send_message_to_dispatcher_user(
            bot, disp_id, text=intro, attachments=media
        )
        if not ok_m:
            await event.message.answer(
                text="Сообщение не доставлено диспетчеру (нет диалога бота с диспетчером в MAX). "
                "Позвоните в офис или повторите позже.",
                attachments=[get_back_to_menu_keyboard()],
            )
        if user_state.get_state(uid) == RequestState.AWAITING_DOCUMENT_UPLOAD:
            user_state.set_state(uid, RequestState.NONE)
        return ok_m

    if text and _is_relay_end(text):
        if media:
            await _send_media_with_caption()
        else:
            await send_message_to_dispatcher_user(
                bot,
                disp_id,
                text=f"[Заявка №{request_id}, пользователь id {uid} завершил диалог в боте.]",
            )
        _pop_relay_pair_for_resident(uid)
        await event.message.answer(
            text="Диалог с диспетчером завершён. Вы снова можете пользоваться меню бота.",
            attachments=[get_main_menu_keyboard()],
        )
        return True

    if text:
        nt = normalize_menu_text(text)
        if nt == normalize_menu_text("Отправить фото документа"):
            user_state.set_state(uid, RequestState.AWAITING_DOCUMENT_UPLOAD)
            await event.message.answer(
                text=(
                    "Пришлите фото или файл документа вложением — мы передадим их диспетчеру. "
                    "Переписка с диспетчером остаётся активной."
                ),
                attachments=[get_back_to_menu_keyboard()],
            )
            return True

        if nt in _RELAY_RESIDENT_EXIT_NORMALIZED:
            if media:
                await _send_media_with_caption()
            _pop_relay_pair_for_resident(uid)
            return False

    if media:
        await _send_media_with_caption()
        return True

    ok = await send_message_to_dispatcher_user(
        bot,
        disp_id,
        text=f"[Заявка №{request_id}, пользователь id {uid}]\n{text}",
    )
    if not ok:
        await event.message.answer(
            text="Сообщение не доставлено диспетчеру (нет диалога бота с диспетчером в MAX). "
            "Позвоните в офис или повторите позже.",
            attachments=[get_back_to_menu_keyboard()],
        )
    return True


async def end_relay_from_dispatcher(event: MessageCreated) -> None:
    disp_id = _user_id(event.from_user)
    if disp_id not in DISPATCHER_USER_IDS or disp_id not in relay_by_dispatcher:
        return

    pair = relay_by_dispatcher.pop(disp_id, None)
    if pair:
        resident_id, _ = pair
        relay_by_resident.pop(resident_id, None)
    bot = event.message.bot
    await event.message.answer(
        text="Диалог с заявителем завершён.",
        attachments=[get_main_menu_keyboard()],
    )
    if pair:
        await send_message_to_resident(
            bot,
            pair[0],
            "Диалог с диспетчером в этом чате завершён. Вы снова можете пользоваться меню бота.",
            attachments=[get_main_menu_keyboard()],
        )


async def handle_dispatcher_chat_resume(
    event: MessageCreated | MessageCallback, request_id: int
) -> None:
    """Диспетчер хочет возобновить или начать чат по конкретной заявке (кнопка или команда)."""
    bot = (event.message.bot if event.message else None) or event._ensure_bot()
    disp_id = _user_id(event.from_user) if event.from_user else None
    if disp_id is None or disp_id not in DISPATCHER_USER_IDS:
        return

    req = await db.get_request(request_id)
    if not req:
        msg = f"Заявка №{request_id} не найдена."
        if isinstance(event, MessageCreated):
            await event.message.answer(text=msg)
        else:
            await bot.send_message(user_id=disp_id, text=msg)
        return

    uid = req["user_id"]
    # Переключаем исходящий канал диспетчера на эту заявку.
    # Старый житель (если был) остается в режиме диалога (согласно "пусть остается открытый чат").
    _register_relay(disp_id, uid, request_id)
    msg = (
        f"Диалог по заявке №{request_id} открыт. "
        "Ваши сообщения будут пересылаться жителю."
    )
    kb = [get_dispatcher_relay_keyboard()]
    if isinstance(event, MessageCreated):
        await event.message.answer(text=msg, attachments=kb)
    else:
        await bot.send_message(user_id=disp_id, text=msg, attachments=kb)
    
    logger.info("Диспетчер %s открыл чат по заявке #%s (UID %s)", disp_id, request_id, uid)
