"""provider.py — Provider фичи lang: порт LocaleStore → tgbotkit.LocalePrefStore (cachekit)."""

from __future__ import annotations

from dishka import Provider, Scope, provide
from pylibinfra.cachekit import Cache
from pylibinfra.tgbotkit import LocalePrefStore

from bot.features.lang.ports import LocaleStore
from bot.features.lang.usecase import LangUsecase


class LangProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def store(self, cache: Cache) -> LocaleStore:
        return LocalePrefStore(cache)

    @provide
    def usecase(self, store: LocaleStore) -> LangUsecase:
        return LangUsecase(store)
