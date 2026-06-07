"""Точка входа: python -m bot."""

import asyncio

from bot.app import run

if __name__ == "__main__":
    asyncio.run(run())
