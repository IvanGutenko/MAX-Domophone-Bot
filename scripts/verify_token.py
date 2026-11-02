#!/usr/bin/env python3
"""Одноразовая проверка BOT_TOKEN (get_me). Запуск на сервере: из каталога domophone_bot: python scripts/verify_token.py"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


async def _main() -> None:
    from maxapi import Bot
    from maxapi.exceptions.max import InvalidToken

    from bot.config import BOT_TOKEN

    if not BOT_TOKEN:
        print("Ошибка: BOT_TOKEN не задан в .env", file=sys.stderr)
        sys.exit(2)

    bot = Bot(token=BOT_TOKEN)
    try:
        me = await bot.get_me()
    except InvalidToken:
        print("Ошибка: неверный токен (сверьте с кабинетом MAX для партнёров)", file=sys.stderr)
        sys.exit(3)
    except Exception as e:
        print(f"Ошибка API/сети: {e!r}", file=sys.stderr)
        sys.exit(4)
    finally:
        await bot.close_session()

    print(
        "Токен действителен:",
        f"id={me.user_id}",
        f"username={getattr(me, 'username', '') or '-'}",
        f"name={getattr(me, 'first_name', '') or '-'}",
    )


if __name__ == "__main__":
    asyncio.run(_main())
