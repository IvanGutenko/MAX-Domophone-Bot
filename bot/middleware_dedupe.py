"""
Дедупликация обновлений от платформы MAX.

MAX может присылать одно и то же действие пользователя несколькими событиями
подряд с разными mid и разным (или пустым) текстом. Из-за этого бот отвечает
несколько раз на одно нажатие кнопки или команду /start.

Стратегия (три уровня, от быстрого к медленному):

1. По mid/callback_id  — если уже видели этот ID, отбрасываем немедленно.
2. По (user_id, event_type) с коротким TTL — только для MessageCallback и BotStarted.
   Для MessageCreated отключено: иначе повторное нажатие кнопки в течение 2 с не обрабатывалось.
3. Фильтрация собственных сообщений бота (is_bot=True / совпадение user_id).
"""

import logging
import time
from collections import OrderedDict
from typing import Any

from maxapi.filters.middleware import BaseMiddleware
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated

logger = logging.getLogger(__name__)

# Окно дедупликации по user_id: одно событие того же типа на пользователя
# в течение этого времени (сек) считается дублем.
USER_TTL: float = 2.0

# Сколько уникальных id хранить в истории
MAX_KEYS = 4096


class DedupeUpdatesMiddleware(BaseMiddleware):

    def __init__(self) -> None:
        # mid / callback_id → None (просто множество, через OrderedDict)
        self._seen_ids: OrderedDict[str, None] = OrderedDict()
        # (user_id, event_class_name) → monotonic time первого события
        self._user_ts: OrderedDict[tuple, float] = OrderedDict()
        # Для коротких окон (например, MessageCreated)
        self._user_ts_short: OrderedDict[tuple, float] = OrderedDict()

    # ------------------------------------------------------------------
    def _check_id(self, key: str) -> bool:
        """Вернуть True, если ID *новый* (первый раз). False — дубль."""
        if key in self._seen_ids:
            self._seen_ids.move_to_end(key)
            return False
        self._seen_ids[key] = None
        while len(self._seen_ids) > MAX_KEYS:
            self._seen_ids.popitem(last=False)
        return True

    def _check_user(self, user_id: int, event_tag: str) -> bool:
        """Вернуть True, если событие *новое*. False — дубль по времени."""
        now = time.monotonic()
        key = (user_id, event_tag)

        # Вычищаем устаревшие записи с начала очереди
        while self._user_ts:
            first = next(iter(self._user_ts))
            if now - self._user_ts[first] >= USER_TTL:
                self._user_ts.popitem(last=False)
            else:
                break

        if key in self._user_ts:
            # Запись свежая — дубль
            logger.info(
                "Dedupe[user]: dropping event %s for user=%s (within %.1fs window)",
                event_tag, user_id, USER_TTL,
            )
            return False

        # Первый раз — запомнить
        self._user_ts[key] = now
        self._user_ts.move_to_end(key)
        while len(self._user_ts) > MAX_KEYS:
            self._user_ts.popitem(last=False)
        return True

    def _check_user_short(self, user_id: int, event_tag: str, ttl: float = 0.5) -> bool:
        """Вернуть True, если событие *новое* в коротком окне."""
        now = time.monotonic()
        key = (user_id, event_tag)

        while self._user_ts_short:
            first = next(iter(self._user_ts_short))
            if now - self._user_ts_short[first] >= ttl:
                self._user_ts_short.popitem(last=False)
            else:
                break

        if key in self._user_ts_short:
            logger.info(
                "Dedupe[user_short]: dropping event %s for user=%s (within %.1fs window)",
                event_tag, user_id, ttl,
            )
            return False

        self._user_ts_short[key] = now
        self._user_ts_short.move_to_end(key)
        while len(self._user_ts_short) > MAX_KEYS:
            self._user_ts_short.popitem(last=False)
        return True

    # ------------------------------------------------------------------
    async def __call__(self, handler, event_object: Any, data: dict[str, Any]):
        bot_instance = getattr(event_object, "bot", None)
        
        # dynamic import to avoid circular dependencies if any
        from bot.handlers.start import _user_id as get_uid

        if isinstance(event_object, MessageCreated):
            msg = event_object.message

            # Фильтруем сообщения самого бота
            if msg and msg.sender and bot_instance:
                if getattr(msg.sender, "is_bot", False):
                    return None
                me = getattr(bot_instance, "_me", None) or await bot_instance.get_me()
                if me and msg.sender.user_id == me.user_id:
                    return None

            # 1. Дедупликация по mid
            mid = None
            if msg and msg.body and msg.body.mid:
                mid = f"mc:{msg.body.mid}"
                if not self._check_id(mid):
                    logger.info("Dedupe[ID]: dropping duplicate mid=%s", mid)
                    return None

            # 2. Дедупликация по user_id + текст для MessageCreated
            # Используем короткое окно (0.7 сек), чтобы отсечь баг MAX (повтор одного и того же действия),
            # но не помешать пользователю, если он осознанно дважды нажал кнопку.
            user_id = get_uid(event_object.from_user) if getattr(event_object, "from_user", None) else None
            if user_id is not None:
                text = msg.body.text if msg and msg.body and msg.body.text else ""
                text = text.strip()
                if text:
                    tag = f"MessageCreated:{text}"
                    if not self._check_user_short(user_id, tag, ttl=0.7):
                        return None

        elif isinstance(event_object, MessageCallback):
            cb = event_object.callback
            if cb:
                # 1. По callback_id
                if cb.callback_id:
                    cid = f"cb:{cb.callback_id}"
                    if not self._check_id(cid):
                        logger.info("Dedupe[ID]: dropping duplicate callback_id=%s", cid)
                        return None

                user_id = get_uid(event_object.from_user) if event_object.from_user else None
                if user_id is not None:
                    payload = (cb.payload or "").strip()
                    tag = f"MessageCallback:{payload}" if payload else "MessageCallback"
                    if not self._check_user(user_id, tag):
                        return None
        
        else:
            # Обработка других типов событий (например, BotStarted)
            from maxapi.types import BotStarted
            if isinstance(event_object, BotStarted):
                user_id = get_uid(event_object.from_user) if event_object.from_user else None
                if user_id is not None:
                    # Мапим на тот же тег "start", что и команду /start
                    if not self._check_user(user_id, "start"):
                        return None

        return await handler(event_object, data)
