import asyncio
from unittest.mock import AsyncMock

async def main():
    class Bot:
        async def get_updates(self, limit=None, timeout=None, marker=None, types=None):
            return {"marker": marker}
    bot = Bot()
    _orig = bot.get_updates
    async def _patch(limit=None, timeout=None, marker=None, types=None):
        print(f"called with marker={marker}")
        return await _orig(limit=limit, timeout=timeout, marker=marker, types=types)
    bot.get_updates = _patch

    await bot.get_updates(marker=123)

asyncio.run(main())
