# 17 · i18n и push-уведомления «из коробки» (зона 17) — generic→kit vs контент→шаблон

> **Задача зоны.** Спроектировать два встроенных в скелет механизма — **i18n** (локализация
> диалогов) и **push-уведомления** (NATS-событие бэкенда → сообщение/обновление диалога в
> Telegram) — строго по границе **generic-механика → pylibinfra bot-infra kit** (условно `tgkit`,
> aiogram как опциональная extra) vs **контент/бизнес-логика → шаблон**.
>
> **Главная директива архитектора (зеркало ARCHITECTURE.md §1, _research/14 §5 «граница с
> pylibinfra»):** *«Переиспользуемое/инфра → кандидат в pylibinfra, не в бот. Бот импортит
> kit-фасады, не httpx/redis/aiogram-обвязку напрямую.»* Поэтому **вся generic-механика** обоих
> механизмов (виджет, middleware, runtime подписчика, обёртка BgManager-подводных-камней) живёт в
> `tgkit`, а в шаблоне остаётся **только контент**: переводы, список ключей, политика локали,
> какие subject'ы подписываем и `event→сообщение`-маппинг.
>
> Зона 18 параллельно проектирует сам kit — generic-поверхность ниже оформлена **совместимо** с
> инвариантами pylibinfra-китов (из _research/04 §0, _research/05 §0):
> - каждый кит — `dishka.Provider`, `scope=Scope.APP`, подключается независимо;
> - **asymmetry note:** Provider **не** provide'ит свой `*Config` — его регистрирует caller; есть
>   дешёвые фабрики `new_*_config()`;
> - `Config` — `pydantic-settings BaseSettings`, поля через `validation_alias`=ENV (public API),
>   таймауты/TTL — float-секунды;
> - lifecycle через async-generator provider (`yield` + cleanup на `container.close()`);
> - OTel/biz-метрики через **глобальный** provider (no-op без `telemetry.init`).
>
> Источники-якоря (цитируются по тексту): `aiogram-dialog-docs/reference/20` (I18NFormat +
> middleware, §4), `aiogram-dialog-docs/reference/06` (BgManager, все подводные камни),
> `aiogram-dialog-docs/guides/building-a-template.md` §8 (i18n-паттерн); `_research/05` §3
> (natskit API: core vs JetStream, drain), `_research/09` §6 (push-направление, deliver_plain/
> deliver_dialog), `_research/11` (long-running health, graceful shutdown, метрики);
> `_research/14` (platform-раскладка, composition root). WebSearch (июнь 2026) — выбор i18n-движка.

---

## 0. Таблица «механизм → generic(kit) / контент(шаблон) → поверхность»

Главный артефакт зоны — раздел границы. Слева generic (в `tgkit`), справа контент (в шаблоне).

### 0.1 i18n

| Механизм | generic → `tgkit.i18n` (поверхность kit'а) | контент/бизнес → шаблон |
|---|---|---|
| **Текст-виджет** | `I18NFormat(key)` — подкласс `aiogram_dialog.widgets.text.Text`, рендерит ключ через функцию перевода из `middleware_data` | — (виджет переиспользуется; ключи в окнах — это контент, см. ниже) |
| **Движок перевода** | `fluent.runtime` (FluentLocalization/FluentResourceLoader) как дефолт + Protocol `Translator` (подменяемо на gettext) | выбор формата файлов (`.ftl`), список ключей |
| **Middleware резолва локали** | `I18nMiddleware` — кладёт `format_value` локали в `data[I18N_FORMAT_KEY]`; вешается на `message`+`callback_query`+`observers[DIALOG_EVENT_NAME]` | — (регистрируется одной строкой) |
| **Источник локали** | Protocol `LocaleResolver` + 2 готовых реализации: `FromUserLanguage` (`event.from_user.language_code`), `FromCachePref` (сохранённый pref в cachekit) | **политика выбора**: какой resolver, дефолтная локаль, цепочка fallback |
| **Загрузчик каталогов** | `CatalogLoader` — сканирует `locales/<lang>/*.ftl`, строит `dict[lang, FluentLocalization]` | **сами `.ftl`-файлы** + раскладка `locales/` |
| **Сохранение pref локали** | `LocalePrefStore` (порт) поверх `cachekit.Cache` (`link`-like ключ `locale:tg:<id>`) | фича смены языка (`features/settings/` — UI выбора + вызов `store.set`) |
| **Конфиг** | `I18nConfig(default_locale, locales_dir)` (ENV `BOT_DEFAULT_LOCALE`, `BOT_LOCALES_DIR`) | значения ENV под проект |
| **Тесты-харнесс** | — (виджет работает в `BotClient` без сети) | flow-тесты: `data[I18N_FORMAT_KEY]` инжектится фейком → проверка перевода |

### 0.2 Push-уведомления

| Механизм | generic → `tgkit.notify` (поверхность kit'а) | контент/бизнес → шаблон |
|---|---|---|
| **Runtime подписчика** | `NotificationRunner` — long-running в том же loop, lifecycle (start/stop), `drain()` на shutdown поверх `natskit.Conn` | — (запускается в lifespan одной строкой) |
| **Транспорт/гарантии** | обёртка над `natskit.Bus` (core) **и** `StreamBus` (JetStream durable/ack) — выбор по конфигу; **рекомендация: JetStream durable** | какие subject'ы критичны (durable) vs best-effort |
| **Регистрация подписок** | `NotificationRouter.on(subject, handler)` — декларативная точка расширения «на subject X → сделать Y» | **сами подписки**: `router.on("orders.paid", deliver_order_paid)` |
| **Helper отправки** | `Notifier` — обёртка `Bot.send_message` + `BgManagerFactory.bg(...).update/start` со **всеми** подводными камнями BgManager закрытыми (load=True, throttle, пустой стек→warning, request_id руками) | **маппинг event→сообщение/диалог** (`views`/`deliver_*` фичи) |
| **Identity-link** | Protocol `ChatResolver` (`backend_uid → chat_id`) + дефолт поверх `cachekit` | заполнение `link:acct→chat_id` при онбординге (фича) |
| **Дедуп доставки** | `DeliveryDedup` поверх `cachekit.IdempotencyStore` (`notify:<event_id>` NX) | TTL-политика дедупа под проект |
| **Метрики доставки** | `notify_delivered_total{subject,result}`, `notify_delivery_seconds`, `notify_dedup_skipped_total` — через глоб. Meter | bizmetric `biz_tg_*` на бизнес-конверсии (опц.) |
| **Конфиг** | `NotifyConfig(durable, queue, ack_wait, throttle)` (ENV `NOTIFY_*`) | значения ENV; список durable-стримов |

> **Принцип границы (зеркало _research/14 §5 «pure core forbids infra»):** шаблон **никогда** не
> импортит `aiogram_dialog.BgManager`, `nats`, `fluent.runtime` напрямую — только `tgkit`-фасады
> (`I18NFormat`, `NotificationRouter`, `Notifier`). Все «грабли» (BgManager EDIT≠гарантия,
> middleware не проходят на фон, core-NATS at-most-once) **закрыты внутри kit'а один раз**.

---

# Часть I. i18n

## 1. Выбор движка — `fluent.runtime` (рекомендация) + Protocol для подмены

### 1.1 Кандидаты (срез на июнь 2026)

| Движок | Формат | Совместимость с `I18NFormat` | Плюрализация/гендер | Кодоген/компиляция | Вердикт |
|---|---|---|---|---|---|
| **`fluent.runtime`** (FluentLocalization) | `.ftl` (Fluent) | **идеальная**: `l10n.format_value(key, kwargs)` 1:1 с тем, что зовёт `I18NFormat._render_text` (reference/20 §4.1) | из коробки (CLDR-правила, `{ $n ->}`-селекторы) | нет (runtime-парсинг) | **дефолт** |
| `aiogram.utils.i18n` (gettext) | `.po`/`.mo` | плохая: `lazy_gettext` — ленивый прокси, завязан на contextvar aiogram; per-render в диалоге ломается | базовая (ngettext, без гендера) | **`pybabel compile`** на каждый деплой | альтернатива, не дефолт |
| `aiogram_i18n` 1.5 (март 2026) | Fluent/gettext | средняя: навязывает свой `I18nContext`/`I18nMiddleware`/manager — **дублирует** то, что делает наш kit | по backend'у | по backend'у | **избыточен** для kit-архитектуры |
| `fluentogram` | `.ftl` | хорошая, но свой transformator/stub-протокол поверх Fluent | как Fluent | precompile (`fluent_compiler`) | не нужен (свой слой) |

### 1.2 Обоснование выбора `fluent.runtime`

1. **Точное совпадение с эталоном.** `aiogram_dialog/example/i18n` (reference/20 §4.1–4.3) построен
   именно на `fluent.runtime`: `FluentResourceLoader` + `FluentLocalization`, и `format_value`
   совместима по сигнатуре `(key, kwargs) -> str` с `I18NFormat._render_text`. Виджет уже спроектирован
   под этот контракт — берём проверенный паттерн, а не переизобретаем.
2. **Ноль build-шага.** В отличие от gettext (`.po`→`.mo` через `pybabel compile` в Dockerfile/CI),
   `.ftl` парсятся в runtime. Это убирает целый класс «забыл скомпилировать переводы» из деплоя
   (зеркало инварианта «один образ, бот stateless» — ARCHITECTURE.md §12).
3. **Плюрализация/гендер из коробки** (CLDR-селекторы `{ $count -> [one] … *[other] … }`) — для
   ru/en это критично (русские падежи/числа). gettext требует ручного `ngettext`, без гендера.
4. **`aiogram_i18n`/`fluentogram` навязывают свой менеджер локали** — а в нашей архитектуре
   middleware и резолв локали **владеет kit** (`I18N_FORMAT_KEY` — просто функция `(key,data)->str`).
   Тащить ещё один middleware-слой = нарушить SRP границы.

> **Подменяемость (OCP).** Движок спрятан за Protocol `Translator`; дефолт — `FluentTranslator`.
> Если конкретный проект требует gettext (легаси-`.po`) — он регистрирует свой `Translator` в DI,
> **виджет и middleware не меняются** (reference/20 §4: *«для не-Fluent движков достаточно положить
> в I18N_FORMAT_KEY любую функцию (key, data) -> str»*).

---

## 2. generic → `tgkit.i18n` (поверхность kit'а)

### 2.1 Текст-виджет `I18NFormat`

Подкласс `Text` — рендерит **ключ**, функцию перевода берёт из `middleware_data` (reference/20 §4.1,
building-a-template §8). Кладётся в любое место `Window` вместо `Format`/`Const`.

```python
# tgkit/i18n/widget.py
from aiogram_dialog.widgets.text import Text
from aiogram_dialog.api.protocols import DialogManager
from aiogram_dialog.widgets.common import WhenCondition

I18N_FORMAT_KEY = "aiogd_i18n_format"   # ЕДИНАЯ константа — импортируется и виджетом, и middleware

def _default_format(key: str, data: dict) -> str:   # fallback без middleware (reference/20 §4.1)
    return key.format_map(data)

class I18NFormat(Text):
    """Текст-виджет, рендерящий ключ перевода. Перевод — из middleware_data по локали."""
    def __init__(self, key: str, when: WhenCondition = None) -> None:
        super().__init__(when)
        self.key = key

    async def _render_text(self, data: dict, manager: DialogManager) -> str:
        fmt = manager.middleware_data.get(I18N_FORMAT_KEY, _default_format)
        return fmt(self.key, data)      # подстановки { $name } приходят из getter через data
```

> **Подводный камень (reference/20 §4 «не кешируйте перевод в виджете»):** текст рендерится на
> **каждый** показ — это правильно: смена языка работает мгновенно. Любой кеш строки внутри виджета
> сломает переключение. Виджет **stateless** относительно локали.

### 2.2 Источник локали — Protocol `LocaleResolver` + 2 реализации

```python
# tgkit/i18n/resolver.py
from typing import Protocol
from aiogram.types import TelegramObject

class LocaleResolver(Protocol):
    async def resolve(self, event: TelegramObject) -> str | None: ...

class FromUserLanguage:
    """Локаль из event.from_user.language_code (быстро, без I/O)."""
    async def resolve(self, event: TelegramObject) -> str | None:
        u = getattr(event, "from_user", None)
        return u.language_code if u and u.language_code else None

class FromCachePref:
    """Сохранённый pref (приоритетнее language_code). Порт LocalePrefStore поверх cachekit."""
    def __init__(self, store: "LocalePrefStore") -> None:
        self._store = store
    async def resolve(self, event: TelegramObject) -> str | None:
        u = getattr(event, "from_user", None)
        return await self._store.get(u.id) if u else None

class ChainResolver:
    """Цепочка: первый непустой. Дефолт шаблона: [FromCachePref, FromUserLanguage]."""
    def __init__(self, *resolvers: LocaleResolver) -> None:
        self._resolvers = resolvers
    async def resolve(self, event: TelegramObject) -> str | None:
        for r in self._resolvers:
            if (lang := await r.resolve(event)) is not None:
                return lang
        return None
```

`LocalePrefStore` поверх `cachekit.Cache` (для фичи смены языка, _research/05 §2):

```python
# tgkit/i18n/pref_store.py
from pylibinfra.cachekit import Cache, get_json, set_json

class LocalePrefStore:                       # generic порт; ключ-неймспейс — как link:* (10 §9)
    def __init__(self, cache: Cache) -> None:
        self._cache = cache
    async def get(self, tg_id: int) -> str | None:
        v, found = await get_json(self._cache, f"locale:tg:{tg_id}")
        return v if found else None
    async def set(self, tg_id: int, lang: str) -> None:
        await set_json(self._cache, f"locale:tg:{tg_id}", lang)   # долгий/без TTL — pref
```

### 2.3 Загрузчик каталогов `CatalogLoader` + Protocol `Translator`

```python
# tgkit/i18n/translator.py
from pathlib import Path
from typing import Protocol, Callable
from fluent.runtime import FluentLocalization, FluentResourceLoader

class Translator(Protocol):
    def format_value(self, key: str, args: dict) -> str: ...   # совместимо с I18NFormat

class FluentTranslator:                       # дефолтная реализация поверх fluent.runtime
    def __init__(self, l10n: FluentLocalization) -> None:
        self._l10n = l10n
    def format_value(self, key: str, args: dict) -> str:
        return self._l10n.format_value(key, args)

class CatalogLoader:
    """Сканирует locales/<lang>/*.ftl, строит dict[lang -> Translator]."""
    def __init__(self, locales_dir: Path, default_locale: str) -> None:
        self._dir = locales_dir
        self._default = default_locale

    def load(self) -> dict[str, Translator]:
        catalogs: dict[str, Translator] = {}
        for lang_dir in sorted(p for p in self._dir.iterdir() if p.is_dir()):
            ftls = [f.name for f in lang_dir.glob("*.ftl")]
            if not ftls:
                continue
            loader = FluentResourceLoader(str(self._dir / "{locale}"))
            l10n = FluentLocalization([lang_dir.name, self._default], ftls, loader)
            catalogs[lang_dir.name] = FluentTranslator(l10n)
        if self._default not in catalogs:
            raise RuntimeError(f"default locale {self._default!r} has no catalog in {self._dir}")
        return catalogs
```

### 2.4 Middleware `I18nMiddleware`

Кладёт `format_value` нужной локали в `data[I18N_FORMAT_KEY]` (reference/20 §4.2). **Ключевой
generic:** один и тот же middleware-инстанс вешается на `message`, `callback_query` **и**
`observers[DIALOG_EVENT_NAME]` — последнее, чтобы **фоновые** рендеры (push в диалог) тоже
получали перевод (reference/06 §5, building-a-template §8: *«i18n-middleware на message,
callback_query И DIALOG_EVENT_NAME»*).

```python
# tgkit/i18n/middleware.py
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram_dialog import DIALOG_EVENT_NAME
from .widget import I18N_FORMAT_KEY
from .resolver import LocaleResolver
from .translator import Translator

class I18nMiddleware(BaseMiddleware):
    def __init__(self, catalogs: dict[str, Translator], resolver: LocaleResolver,
                 default_locale: str) -> None:
        self._catalogs = catalogs
        self._resolver = resolver
        self._default = default_locale

    async def __call__(self, handler, event: TelegramObject, data: dict):
        lang = await self._resolver.resolve(event)
        if lang not in self._catalogs:           # неизвестная/None → дефолт (reference/20 §4.2)
            lang = self._default
        data[I18N_FORMAT_KEY] = self._catalogs[lang].format_value
        data["locale"] = lang                    # доступно getter'ам (для "текущий язык" в UI)
        return await handler(event, data)

def install_i18n(dp, middleware: I18nMiddleware) -> None:
    """Generic-инсталлятор: ОБА типа событий + фоновые dialog-апдейты."""
    dp.message.middleware(middleware)
    dp.callback_query.middleware(middleware)
    dp.observers[DIALOG_EVENT_NAME].middleware(middleware)   # ← фон не проходит обычные observers
```

> **Подводный камень фоновой локали (reference/20 §4 + §06 §7):** при background-обновлениях
> `event.from_user` может содержать **только `id`** (FakeUser, `first_name=""`), поэтому
> `FromUserLanguage` вернёт `None` → `default_locale`. Чтобы push-в-диалог локализовался корректно
> для конкретного юзера — `FromCachePref` (pref в Redis) **или** push-helper передаёт локаль явно
> (см. ч. II §3.4). Это причина, почему `ChainResolver` ставит `FromCachePref` первым.

### 2.5 Provider и Config (совместимо с pylibinfra-китами)

```python
# tgkit/i18n/config.py
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field

class I18nConfig(BaseSettings):
    model_config = {"extra": "ignore", "populate_by_name": True}
    default_locale: str = Field("ru", validation_alias="BOT_DEFAULT_LOCALE")
    locales_dir: Path = Field(Path("locales"), validation_alias="BOT_LOCALES_DIR")

def new_i18n_config() -> I18nConfig:           # дешёвая фабрика (asymmetry note)
    return I18nConfig()
```

```python
# tgkit/i18n/module.py
from dishka import Provider, Scope, provide
from .config import I18nConfig
from .translator import CatalogLoader, Translator
from .resolver import ChainResolver, FromCachePref, FromUserLanguage, LocaleResolver
from .pref_store import LocalePrefStore
from .middleware import I18nMiddleware
from pylibinfra.cachekit import Cache

class I18nProvider(Provider):
    scope = Scope.APP
    # НЕ provide'ит I18nConfig (asymmetry note) — его регистрирует AppConfigProvider шаблона.

    @provide
    def catalogs(self, cfg: I18nConfig) -> dict[str, Translator]:
        return CatalogLoader(cfg.locales_dir, cfg.default_locale).load()   # один раз на старте

    @provide
    def pref_store(self, cache: Cache) -> LocalePrefStore:
        return LocalePrefStore(cache)

    @provide
    def resolver(self, pref: LocalePrefStore) -> LocaleResolver:
        return ChainResolver(FromCachePref(pref), FromUserLanguage())      # политика по умолчанию

    @provide
    def middleware(self, catalogs: dict[str, Translator], resolver: LocaleResolver,
                   cfg: I18nConfig) -> I18nMiddleware:
        return I18nMiddleware(catalogs, resolver, cfg.default_locale)
```

> **Совместимость с зоной 18.** Всё выше — стандартная kit-форма: `Config` (BaseSettings c
> validation_alias), `new_*_config()`, `Provider(Scope.APP)` без Config, lifecycle тривиален
> (каталоги — in-memory, ресурсов закрывать нет). Если зона 18 сделает aiogram опциональной extra
> у kit'а — `tgkit.i18n` сидит под extra `[aiogram]` (тянет `aiogram_dialog`), `fluent.runtime` —
> прямая зависимость extra.

---

## 3. business/контент → шаблон (i18n)

### 3.1 Раскладка `locales/` и формат `.ftl`

```
src/bot/                         # (или корень проекта — путь из BOT_LOCALES_DIR)
locales/
├── ru/                          # default_locale
│   ├── common.ftl               # кнопки/ошибки общего назначения
│   ├── start.ftl                # ключи фичи start
│   └── profile.ftl              # ключи фичи profile
└── en/
    ├── common.ftl
    ├── start.ftl
    └── profile.ftl
```

> **Решение по namespacing.** Один `.ftl`-файл на фичу (зеркало «вертикальных срезов» _research/14):
> `FluentLocalization` грузит **все** файлы локали, ключи в общем плоском пространстве — поэтому
> ключи **префиксуем именем фичи** (`profile-title`, `start-welcome`), чтобы не было коллизий между
> фичами. Это контент-конвенция шаблона, не kit'а.

```ftl
# locales/ru/start.ftl
start-welcome = 👋 Привет, { $username }! Выбери раздел:
start-btn-profile = 👤 Профиль
start-btn-settings = ⚙️ Настройки

# locales/ru/profile.ftl
profile-title = Профиль { $name }
profile-balance = Баланс: { $amount } { $currency }
# плюрализация (CLDR) — то, чего нет в gettext без ngettext:
profile-orders = У вас { $count ->
    [one] { $count } заказ
    [few] { $count } заказа
   *[other] { $count } заказов
}
```

```ftl
# locales/en/start.ftl
start-welcome = 👋 Hi, { $username }! Choose a section:
start-btn-profile = 👤 Profile
start-btn-settings = ⚙️ Settings
```

### 3.2 Использование в окне (контент фичи)

```python
# src/bot/features/start/dialogs.py
from aiogram_dialog import Dialog, Window, LaunchMode
from aiogram_dialog.widgets.kbd import Start, Group
from tgkit.i18n import I18NFormat          # ← kit-фасад, НЕ aiogram_dialog напрямую
from bot.platform.dialogs import states
from .getters import start_getter

start_dialog = Dialog(
    Window(
        I18NFormat("start-welcome"),                                  # ключ → перевод по локали
        Group(
            Start(I18NFormat("start-btn-profile"), id="profile", state=states.Profile.VIEW),
            Start(I18NFormat("start-btn-settings"), id="settings", state=states.Settings.MAIN),
            width=2,
        ),
        state=states.Start.MENU,
        getter=start_getter,        # отдаёт { "username": ... } — подстановка { $username }
    ),
    launch_mode=LaunchMode.ROOT,
)
```

### 3.3 Политика выбора локали и дефолт (решение шаблона)

| Параметр | Значение по умолчанию в шаблоне | Где менять |
|---|---|---|
| Дефолтная локаль | `ru` (`BOT_DEFAULT_LOCALE`) | ENV |
| Цепочка резолва | `FromCachePref` → `FromUserLanguage` → default | `I18nProvider.resolver` (переопределить в шаблоне) |
| Набор локалей | `ru`, `en` (по каталогам в `locales/`) | добавить каталог |
| Fallback при отсутствии ключа | `FluentLocalization([lang, default])` — fluent сам падает в default-локаль | конфиг loader'а |

### 3.4 Фича смены языка (`features/settings/`) — контент

UI выбора языка + запись pref. Generic `LocalePrefStore` — из kit'а; **UI и список доступных
языков — контент**:

```python
# src/bot/features/settings/handlers.py
from dishka.integrations.aiogram_dialog import FromDishka, inject
from tgkit.i18n import LocalePrefStore
from bot.platform.dialogs import states

@inject
async def on_pick_lang(callback, widget, manager, lang: str,
                       store: FromDishka[LocalePrefStore]):
    await store.set(callback.from_user.id, lang)     # pref → Redis (locale:tg:<id>)
    await manager.switch_to(states.Settings.MAIN)    # следующий рендер уже на новой локали
```

### 3.5 Тестирование i18n (контент-тесты)

Виджет работает в `BotClient` без сети — переводы проверяются инъекцией `I18N_FORMAT_KEY`
(reference/20 §1.5, building-a-template §9). Локаторы кнопок — **по `callback_data`/`id`**, не по
тексту (i18n+эмодзи ломают `fullmatch`, _research/13):

```python
# tests/flows/test_i18n.py
import pytest
from tgkit.i18n import I18N_FORMAT_KEY
from aiogram_dialog.test_tools.keyboard import InlineButtonDataLocator

@pytest.fixture
def dp_ru(message_manager):                  # инжектим конкретную локаль через Dispatcher-kwargs
    dp = Dispatcher(storage=JsonMemoryStorage())
    ru = {"start-welcome": "Привет!"}        # мини-каталог
    dp["_test_i18n"] = lambda k, d: ru.get(k, k)
    # outer-middleware кладёт data[I18N_FORMAT_KEY] = dp["_test_i18n"]
    ...
    return dp

@pytest.mark.asyncio
async def test_welcome_localized(dp_ru, client, message_manager):
    await client.send("/start")
    assert "Привет" in message_manager.one_message().text
    await client.click(message_manager.last_message(), InlineButtonDataLocator(r".*profile.*"))
```

---

# Часть II. Push-уведомления

## 1. generic → `tgkit.notify`: runtime подписчика

### 1.1 `NotificationRunner` — long-running в том же loop

Подписчик NATS — **отдельный long-running компонент рядом с aiogram-polling/webhook**, в том же
event-loop; на shutdown даём `Conn.drain()` отработать (_research/05 §3 ⚠️, _research/11 §5). Kit
прячет lifecycle за `start()`/`stop()`:

```python
# tgkit/notify/runner.py
import asyncio
from pylibinfra.natskit import Conn
from .router import NotificationRouter
from .config import NotifyConfig

class NotificationRunner:
    """Запускает все подписки из NotificationRouter, держит их, drain на остановке."""
    def __init__(self, conn: Conn, router: NotificationRouter, cfg: NotifyConfig) -> None:
        self._conn = conn
        self._router = router
        self._cfg = cfg
        self._started = False

    async def start(self) -> None:
        # регистрирует ВСЕ subject→handler; core-NATS или JetStream durable по cfg (§2)
        await self._router.bind(self._conn, self._cfg)
        self._started = True

    async def stop(self) -> None:
        if self._started:
            await self._conn.drain()       # дослать/долучить in-flight (05 §3, module.py)
```

> **Зачем drain, а не close (05 §3, 11 §5):** `Conn.drain()` дослушивает уже принятые сообщения и
> отписывается gracefully — это часть инварианта graceful shutdown («stop-приём → drain →
> `nats.drain` → `container.close()`»). В kit-форме `NatsProvider` сам делает `drain()` на закрытии
> скоупа; `NotificationRunner.stop()` — явная точка для шаблонного lifespan-порядка.

### 1.2 Lifecycle через Provider (совместимо с зоной 18)

```python
# tgkit/notify/module.py
from dishka import Provider, Scope, provide
from pylibinfra.natskit import Conn
from .config import NotifyConfig
from .router import NotificationRouter
from .runner import NotificationRunner
from .notifier import Notifier
from .dedup import DeliveryDedup
from .resolver import ChatResolver

class NotifyProvider(Provider):
    scope = Scope.APP
    # НЕ provide'ит NotifyConfig (asymmetry note).

    @provide
    def router(self) -> NotificationRouter:
        return NotificationRouter()            # пустой; подписки регистрирует шаблон (§ точка расш.)

    @provide
    async def runner(self, conn: Conn, router: NotificationRouter,
                     cfg: NotifyConfig) -> NotificationRunner:
        runner = NotificationRunner(conn, router, cfg)
        yield runner                           # lifecycle: start/stop дёргает lifespan шаблона
        await runner.stop()                    # drain на container.close()
```

---

## 2. generic → JetStream durable vs core (рекомендация)

### 2.1 Решение: **JetStream durable + EXPLICIT ack** по умолчанию

| Критерий | core NATS (`Bus`) | JetStream (`StreamBus`) |
|---|---|---|
| Гарантия | **at-most-once** — сообщение в даунтайм бота **потеряно** (05 §3) | at-least-once: durable consumer, `msg.ack()`/`msg.nak()` (переотправка) |
| Подходит для | эфемерные «прямо сейчас» уведомления (печатает…, прогресс) | бизнес-события (заказ оплачен, баланс изменён) — **нельзя терять** |
| Стоимость | дешевле, нет стрима | стрим `<name>.>`, `ack_wait`, durable_name |

> **Рекомендация (05 §3 ⚠️, _research/09 §6.1):** *«Если уведомление нельзя терять (не пропустить
> событие, пока бот лежал) — нужен JetStream с durable, иначе сообщения, пришедшие в даунтайм,
> потеряются».* Для sftbmb push'и — это бизнес-события → **JetStream durable дефолт**. Kit
> поддерживает оба, выбор по `NotifyConfig.durable`; core оставлен для эфемерных subject'ов.

```python
# tgkit/notify/router.py
from typing import Awaitable, Callable
from pylibinfra.natskit import Conn, NatsBus, subscribe_json
from pylibinfra.natskit import subscribe_stream_json    # JetStream durable (05 §3)
from .config import NotifyConfig

Handler = Callable[[dict], Awaitable[None]]

class NotificationRouter:
    """Декларативная точка расширения: on(subject, handler). Bind на старте runner'а."""
    def __init__(self) -> None:
        self._routes: list[tuple[str, Handler, bool]] = []   # (subject, handler, durable?)

    def on(self, subject: str, handler: Handler, *, durable: bool = True) -> None:
        self._routes.append((subject, handler, durable))     # ← шаблон регистрирует подписки тут

    async def bind(self, conn: Conn, cfg: NotifyConfig) -> None:
        bus = NatsBus(conn, ...)   # фасад; в реале берётся из natskit-Provider
        for subject, handler, durable in self._routes:
            if durable and cfg.jetstream_enabled:
                # durable consumer: успех→ack, ошибка→nak (переотправка) — 05 §3
                await subscribe_stream_json(
                    bus, stream=cfg.stream, subject=subject,
                    durable=cfg.durable_name(subject), handler=handler,
                )
            else:
                await subscribe_json(bus, subject, handler)  # core: at-most-once
```

> **Подводный камень handler-ошибки (05 §3):** в core-NATS handler-ошибка **не валит подписку**
> (panic-recovery natskit: лог+error-спан) — но сообщение **потеряно** (нет ack). В JetStream
> ошибка → `nak()` → **переотправка** (риск дубля → нужен дедуп, §4). Это и есть аргумент за
> JetStream + дедуп вместо «надёжного» core.

---

## 3. generic → helper отправки `Notifier` (все подводные камни BgManager закрыты)

Это **сердце kit'а push-направления**: единственное место, где дёргается `Bot.send_message` /
`BgManagerFactory.bg(...)`, со ВСЕМИ граблями reference/06 обёрнутыми.

```python
# tgkit/notify/notifier.py
import structlog
from aiogram import Bot
from aiogram_dialog import BgManagerFactory, ShowMode, StartMode
from aiogram.fsm.state import State
from pylibinfra.httpclient import request_id

log = structlog.get_logger()

class Notifier:
    def __init__(self, bot: Bot, bg_factory: BgManagerFactory) -> None:
        self._bot = bot
        self._bg = bg_factory

    # --- (1) простое сообщение (когда нет открытого диалога / уведомление самодостаточно) ---
    async def send(self, chat_id: int, text: str, **kwargs) -> None:
        await self._bot.send_message(chat_id, text, **kwargs)   # _research/09 §6.1 deliver_plain

    # --- (2) обновить открытый диалог пользователя ---
    async def update_dialog(self, *, user_id: int, chat_id: int, data: dict,
                            show_mode: ShowMode = ShowMode.EDIT) -> None:
        bg = self._bg.bg(bot=self._bot, user_id=user_id, chat_id=chat_id, load=True)
        # load=True ОБЯЗАТЕЛЕН: иначе FakeChat.type=="" ≠ PRIVATE и AUTO-логика SEND/EDIT
        #   некорректна; виджеты/getter'ы, читающие from_user/event_chat, получат пустоту (06 §7,§9)
        await bg.update(data, show_mode=show_mode)
        # ⚠ update() по ПУСТОМУ/закрытому стеку = тихий logger.warning("No context found"),
        #   без ошибки и без сообщения (06 §4, update_handler.py:35-37). Это НЕ баг — у юзера
        #   просто нет открытого диалога. Если нужен гарантированный показ — используй start_dialog.

    # --- (3) стартовать диалог (когда открытого может не быть) ---
    async def start_dialog(self, *, user_id: int, chat_id: int, state: State,
                           data: dict | None = None) -> None:
        bg = self._bg.bg(bot=self._bot, user_id=user_id, chat_id=chat_id, load=True)
        await bg.start(state, data=data, mode=StartMode.RESET_STACK)
        # фоновый start логично создаёт НОВОЕ сообщение (old_message=None → ветка send, 06 §9 п.1)
```

### Подводные камни BgManager — закрыты внутри `Notifier` (reference/06)

| Грабли (reference/06) | Как закрыто в kit |
|---|---|
| `bg()` требует `bot` (у фабрики нет «текущего») + `user_id`+`chat_id` (§2,§3) | `Notifier` хранит `bot`, API требует именованные `user_id`/`chat_id` |
| Без `load=True` FakeChat.type="" → AUTO почти всегда EDIT, даже в приватном (§7,§9) | `load=True` **всегда** (ценой 1-2 API-вызовов — приемлемо для редких push'ей) |
| `update()` по пустому стеку = тихий warning, без UX (§4,§12) | задокументировано; для гарантии — `start_dialog` (отдельный метод, не `update`) |
| **EDIT не гарантирован** (нет old / нельзя edit / Telegram отказал → send, §9) | принимаем как данность; helper не обещает «ровно edit», это intent |
| Фон **не проходит обычные middleware** → request_id/i18n руками (§5,§12) | request_id ставит обёртка подписки (§3.4); i18n — middleware на `DIALOG_EVENT_NAME` (ч.I §2.4) |
| Throttle: `bg.update()` возвращается до выполнения (`call_soon`) → flood при плотном цикле (§12) | `NotifyConfig.throttle` + дедуп (§4); push'и редкие, но защита есть |
| Корень роутера обязан быть `Dispatcher` иначе `TypeError` (§5,§12) | инвариант composition root (setup_dialogs на Dispatcher — ARCHITECTURE.md §7) |
| Для чужого чата `stack_id` дефолтно `""` (DEFAULT_STACK_ID) — другой стек (§3,§12) | дефолт ОК (push в основной стек юзера); если нужен конкретный — расширить API |

### 3.4 Обёртка подписки — request_id + identity руками (фон вне middleware)

Фоновый обработчик идёт **вне** middleware (05 §6.1, 09 §2.1, 11 §2.3) — корреляцию и резолв
chat_id ставим руками. Kit даёт декоратор, шаблон пишет только бизнес-`deliver`:

```python
# tgkit/notify/handler.py
import structlog
from pylibinfra.httpclient import request_id
from .resolver import ChatResolver
from .dedup import DeliveryDedup
from .notifier import Notifier

def make_delivery(resolver: ChatResolver, dedup: DeliveryDedup, notifier: Notifier,
                  deliver):
    """Оборачивает бизнес-deliver: dedup + chat-resolve + request_id + метрика.
       deliver(notifier, chat_id, evt) — пишет ШАБЛОН (event→сообщение/диалог)."""
    async def handler(evt: dict) -> None:
        event_id = evt.get("event_id", "")
        if await dedup.seen(event_id):                    # дедуп доставки (§4)
            return
        request_id.set(f"evt-{event_id}")                 # корреляция — фон вне middleware (09 §2.1)
        backend_uid = evt["user_id"]
        chat_id = await resolver.resolve(backend_uid)     # identity-link (§ resolver)
        if chat_id is None:
            structlog.get_logger().info("notify: unlinked user", backend_uid=backend_uid)
            return                                        # юзер не связан — молча (09 §6.1)
        await deliver(notifier, chat_id, backend_uid, evt)
    return handler
```

### 3.5 Метрики доставки (через глобальный Meter, kit)

```python
# tgkit/notify/metrics.py — технический RED доставки (НЕ biz_*; аналог tg_api_* из 11 §1.2)
# notify_delivered_total{subject, result}      result: ok|unlinked|error|skipped_dup
# notify_delivery_seconds{subject}             длительность доставки
# notify_dedup_skipped_total{subject}          сколько отсеяно дедупом
```

> Эти метрики дополняют `nats_*` (consumer, из natskit — 11 §0) и `tg_api_calls_total` (send из
> session-middleware — 11 §1.2). **Не дублируем** их в biz_*: бизнес-конверсии (`biz_tg_*`) —
> отдельно и в шаблоне (11 §1.3).

---

## 4. generic → дедуп доставки

JetStream at-least-once + `nak`-переотправка → возможны **дубли** → дедуп обязателен. Поверх
`cachekit.IdempotencyStore`/`Cache` (05 §2: «готовый dedup-стор»), ключ `notify:<event_id>` с NX:

```python
# tgkit/notify/dedup.py
from datetime import timedelta
from pylibinfra.cachekit import Cache

class DeliveryDedup:
    def __init__(self, cache: Cache, ttl: timedelta = timedelta(hours=24)) -> None:
        self._cache = cache
        self._ttl = ttl
    async def seen(self, event_id: str) -> bool:
        if not event_id:
            return False
        key = f"notify:{event_id}"
        _data, found = await self._cache.get(key)
        if found:
            return True                       # дубль доставки — пропускаем
        await self._cache.set(key, b"1", self._ttl)
        return False
```

> **Подводный камень дедупа (10 §дедуп, зеркало dedup update_id):** `get`→`set` имеет гонку при
> конкурентной доставке. Для строгой гарантии — атомарный `SET notify:<id> 1 NX EX` (Redis NX);
> `Cache.set` без NX оставляет узкое окно. Для редких push'ей `get+set` достаточно; точку отмечаем.

---

## 5. business → шаблон (push)

### 5.1 Раскладка: `notifications`-хендлеры в фиче

Push-направление — это **delivery-вход фичи** (зеркало `delivery/nats/` из _research/14 §6, 09
§6.1). Кладём в фичу, рядом с её диалогами:

```
src/bot/features/billing/
├── ...                              # обычные слои фичи
├── events.py                        # pydantic-payload событий бэкенда (OrderPaidEvent)
└── notifications/
    ├── __init__.py
    ├── deliver.py                   # event→сообщение/диалог (бизнес-маппинг)
    └── register.py                  # router.on("orders.paid", ...) — какие subject'ы
```

### 5.2 Какие события подписываем + маппинг event→сообщение/диалог (контент)

```python
# src/bot/features/billing/notifications/deliver.py
from tgkit.i18n import I18N_FORMAT_KEY   # для локализации текста push (опц.)
from tgkit.notify import Notifier
from bot.platform.dialogs import states

async def deliver_order_paid(notifier: Notifier, chat_id: int, backend_uid: str, evt: dict) -> None:
    # вариант (1): простое сообщение
    await notifier.send(chat_id, f"✅ Заказ {evt['order_id']} оплачен")
    # вариант (2): обновить открытый диалог (если у юзера открыт OrderSG)
    # await notifier.update_dialog(user_id=int(backend_uid), chat_id=chat_id,
    #                              data={"last_event": evt})
```

```python
# src/bot/features/billing/notifications/register.py — ТОЧКА РАСШИРЕНИЯ kit'а
from tgkit.notify import NotificationRouter
from .deliver import deliver_order_paid

def register(router: NotificationRouter) -> None:
    router.on("orders.paid", _wrap(deliver_order_paid), durable=True)   # бизнес-событие → durable
    router.on("orders.shipped", _wrap(deliver_order_shipped), durable=True)
```

### 5.3 Identity-link (`link:acct→chat_id`) — контент

Generic `ChatResolver` (порт) — в kit'е; **заполнение link'а при онбординге** — контент фичи
(05 §5, 10 §9). Дефолтная реализация поверх cachekit:

```python
# tgkit/notify/resolver.py  (generic — порт + дефолт)
from typing import Protocol
from pylibinfra.cachekit import Cache, get_json

class ChatResolver(Protocol):
    async def resolve(self, backend_uid: str) -> int | None: ...

class CacheChatResolver:
    def __init__(self, cache: Cache) -> None:
        self._cache = cache
    async def resolve(self, backend_uid: str) -> int | None:
        v, found = await get_json(self._cache, f"chat:by-acct:{backend_uid}")
        return int(v) if found else None
```

```python
# src/bot/features/start/handlers.py  (КОНТЕНТ — заполнение link при link-флоу, 05 §5)
from pylibinfra.cachekit import Cache, set_json

async def on_account_linked(cache: Cache, tg_chat_id: int, backend_uid: str) -> None:
    await set_json(cache, f"chat:by-acct:{backend_uid}", tg_chat_id)   # обратный индекс для push
    await set_json(cache, f"link:tg:{tg_chat_id}", backend_uid)        # прямой (для исходящих, 09 §2.2)
```

---

# Часть III. Wiring — как оба включаются в тонкий `app.py` шаблона

Композиция в composition root (ARCHITECTURE.md §7, _research/14 §4). Шаблон добавляет
**kit-провайдеры** в контейнер и **две строчки** установки. Вся механика — в kit'е.

```python
# src/bot/app.py  (фрагменты — только i18n + notify wiring)
from aiogram import Bot, Dispatcher
from aiogram_dialog import setup_dialogs
from aiogram.fsm.storage.redis import RedisEventIsolation
from dishka import make_async_container
from dishka.integrations.aiogram import setup_dishka

from tgkit.i18n import I18nProvider, I18nMiddleware, install_i18n, new_i18n_config, I18nConfig
from tgkit.notify import (NotifyProvider, NotificationRouter, NotificationRunner,
                          new_notify_config, NotifyConfig)
from pylibinfra.natskit import NatsProvider
from pylibinfra.cachekit import CacheProvider

# фиче-регистраторы push-подписок (КОНТЕНТ)
from bot.features.billing.notifications.register import register as register_billing_notify


def build_container(cfg):
    return make_async_container(
        # infra (pylibinfra) + AppConfigProvider (отдаёт I18nConfig, NotifyConfig — asymmetry note)
        CacheProvider(), NatsProvider(), AppConfigProvider(cfg),
        # tgkit (generic-механика обоих механизмов)
        I18nProvider(), NotifyProvider(),
        # platform + features ...
    )


def build_dispatcher(cfg, container) -> Dispatcher:
    storage = ...
    dp = Dispatcher(storage=storage)
    # ... команды, error-handlers, outer-middlewares (request-id/dedup/RED) ...

    # ── i18n: kit ставит middleware на message+callback_query+DIALOG_EVENT_NAME (1 строка) ──
    i18n_mw = container.get(I18nMiddleware)        # из I18nProvider
    install_i18n(dp, i18n_mw)                      # ← kit прячет «ОБА события + фон» (ч.I §2.4)

    dp.include_router(build_dialog_router())       # роутеры/диалоги фич
    setup_dishka(container, dp)
    # setup_dialogs ПОСЛЕДНИМ — рождает bg_factory (нужен Notifier для push в диалог)
    dp["bg_factory"] = setup_dialogs(dp, events_isolation=RedisEventIsolation(redis=storage.redis))
    return dp


async def run() -> None:
    cfg = load_config()
    container = build_container(cfg)
    dp = build_dispatcher(cfg, container)
    bot = Bot(cfg.bot_token, default=...)
    await dp.emit_startup()

    # ── notify: шаблон регистрирует подписки в kit-router, kit-runner их держит ──
    notify_router = await container.get(NotificationRouter)
    register_billing_notify(notify_router)         # ← КОНТЕНТ: «на subject X → deliver Y»
    runner = await container.get(NotificationRunner)
    await runner.start()                           # long-running в ТОМ ЖЕ loop (05 §3, 11 §5)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        # graceful shutdown (11 §5): стоп-приём → drain → container.close() → session.close()
        await runner.stop()                        # Conn.drain() — дослать in-flight push
        await container.close()                    # telemetry-flush + redis/nats close
        await bot.session.close()
```

**Что увидел разработчик шаблона:**
- i18n: добавил `I18nProvider()`, одну строку `install_i18n(dp, mw)`, положил `.ftl` в `locales/`.
  Виджет `I18NFormat("key")` — в окнах. Всё. Middleware на 3 точки, фоновая локаль, fallback —
  внутри kit'а.
- notify: добавил `NotifyProvider()`, написал `deliver_*` (event→сообщение) и `register(router)`
  (subject→deliver), вызвал `runner.start()`/`runner.stop()`. BgManager-грабли, drain, дедуп,
  request_id, метрики — внутри kit'а.

---

## Часть IV. Сводка подводных камней (с цитатами)

| # | Подводный камень | Источник | Где закрыт |
|---|---|---|---|
| 1 | **i18n-middleware на `message` И `callback_query`** — иначе при нажатии кнопки локаль не подставится | reference/20 §4 «вешать на оба типа событий» | `install_i18n` (kit) — оба + фон |
| 2 | **Фоновые dialog-апдейты не проходят обычные observers** — i18n/auth/throttle на `DIALOG_EVENT_NAME` руками | reference/06 §5; building-a-template §8 | `install_i18n` вешает на `observers[DIALOG_EVENT_NAME]` |
| 3 | **Не кешировать перевод в виджете** — иначе смена языка не работает | reference/20 §4.1 | `I18NFormat._render_text` рендерит на каждый показ |
| 4 | **Фоновая локаль:** `from_user` в bg может быть только `id` → `default_lang` | reference/20 §4; reference/06 §7 | `ChainResolver(FromCachePref, …)` — pref из Redis |
| 5 | **core-NATS at-most-once:** событие в даунтайм бота потеряно | _research/05 §3 ⚠️ | дефолт **JetStream durable** (NotifyConfig) |
| 6 | **`bg().update()` по пустому стеку = тихий warning**, без UX | reference/06 §4,§12 (`update_handler.py:35-37`) | `Notifier.update_dialog` документирует; для гарантии — `start_dialog` |
| 7 | **EDIT не гарантирует edit** (нет old / нельзя edit / Telegram отказал → send) | reference/06 §9 | принято как intent; `load=True` для корректного AUTO |
| 8 | **`load=True` обязателен** иначе FakeChat.type="" ломает AUTO SEND/EDIT (+ пустые from_user/chat) | reference/06 §7,§9 | `Notifier` всегда `load=True` |
| 9 | **Фон вне middleware → request_id руками** (иначе вызовы бэкенда без корреляции) | _research/09 §2.1; reference/06 §5 | `make_delivery` ставит `request_id.set("evt-…")` |
| 10 | **Throttle частоту `bg.update()`** — возвращается до выполнения (`call_soon`), плотный цикл → flood | reference/06 §12 | `NotifyConfig.throttle` + дедуп; push'и редки |
| 11 | **JetStream `nak` → переотправка → дубли** | _research/05 §3 | `DeliveryDedup` (`notify:<event_id>`) |
| 12 | **drain на shutdown** — иначе in-flight push теряются | _research/05 §3; _research/11 §5 | `NotificationRunner.stop()` → `Conn.drain()` |
| 13 | **Корень роутера обязан быть `Dispatcher`** иначе bg → `TypeError` | reference/06 §5,§12 | инвариант composition root |
| 14 | **Маппинг `backend_uid → chat_id` natskit не делает** | _research/05 §3 ⚠️; §09 §6.1 | `ChatResolver` (kit-порт) + заполнение link (контент) |
| 15 | **gettext требует `pybabel compile`** на деплой; Fluent — runtime | WebSearch (июнь 2026) | выбор `fluent.runtime` (ноль build-шага) |

---

## Сухой остаток (что фиксируем в дизайне)

1. **i18n-движок — `fluent.runtime`** (`.ftl`): идеальная совместимость с `I18NFormat`
   (`format_value(key, kwargs)` 1:1, reference/20 §4), ноль build-шага (vs gettext `pybabel
   compile`), плюрализация/гендер из коробки. Спрятан за Protocol `Translator` → подменяем на
   gettext без правки виджета/middleware.
2. **i18n generic → `tgkit.i18n`:** виджет `I18NFormat`, `I18nMiddleware`+`install_i18n` (на
   `message`+`callback_query`+`DIALOG_EVENT_NAME`), `LocaleResolver` (Protocol + `FromUserLanguage`/
   `FromCachePref`/`ChainResolver`), `CatalogLoader`, `LocalePrefStore`, `I18nProvider`/`I18nConfig`.
   **i18n контент → шаблон:** `.ftl` в `locales/<lang>/<feature>.ftl`, ключи (префикс=фича),
   политика резолва, дефолт `ru`, фича смены языка.
3. **Push generic → `tgkit.notify`:** `NotificationRunner` (long-running+drain),
   `NotificationRouter.on(subject, handler)` (точка расширения), `Notifier` (Bot.send_message +
   BgManager.update/start со ВСЕМИ граблями reference/06 закрытыми: `load=True`, пустой стек→документ,
   EDIT≠гарантия, request_id руками), `DeliveryDedup`, `ChatResolver`, метрики доставки,
   `NotifyProvider`/`NotifyConfig`. **Push контент → шаблон:** какие subject'ы, `deliver_*`
   (event→сообщение/диалог), `register(router)`, заполнение `chat:by-acct:<uid>` при онбординге.
4. **Транспорт push — JetStream durable дефолт** (бизнес-события нельзя терять, 05 §3), core
   оставлен для эфемерных; durable→дедуп обязателен (nak-переотправка).
5. **Wiring:** i18n — `I18nProvider()` + `install_i18n(dp, mw)` (kit ставит middleware на 3 точки).
   notify — `NotifyProvider()` + шаблон `register(router)` подписки + `runner.start()/stop()` в
   lifespan (drain до `container.close()`). Тонкий `app.py` не знает про `fluent.runtime`/`nats`/
   `BgManager` — только kit-фасады.
6. **Топ-4 граблей:** (а) middleware/i18n не проходят на `DIALOG_EVENT_NAME` → вешать руками
   (закрыто `install_i18n`); (б) `bg().update()` по пустому стеку = тихий warning, EDIT≠гарантия,
   нужен `load=True` (закрыто `Notifier`); (в) core-NATS теряет события в даунтайм → JetStream
   durable + дедуп против nak-дублей; (г) фон вне middleware → `request_id`/локаль руками + drain
   на shutdown.
