# 13 — Стратегия тестирования бота (зона M)

> Артефакт зоны M: пирамида тестов для `telegram-bot-template` (aiogram 3.28 +
> aiogram_dialog 2.6, поверх `pylibinfra`). Бот — **фронтенд** к бэкендам; бизнес-логика
> на бэкендах, в тестах бэкенд **мокается**. Тулинг — uv + pytest, RED-first
> (аналог go-`triage-failure`), testcontainers из `pylibinfra.testkit`.
>
> Источники (абсолютные пути от `/root/git/sftbmb/sftbmb-core/`):
> - `telegram-bot-template/aiogram-dialog-docs/reference/20-testing-preview-i18n-faq.md`
>   (харнесс `BotClient`/`MockMessageManager`/`JsonMemoryStorage` — далее «reference/20 §N»)
> - `.../design/_research/01` (go-template архитектура), `/03` (pytest-тулинг/CI/gate),
>   `/05` (integration-киты pylibinfra: httpclient/cachekit/natskit/testkit),
>   `/06` (dishka test-override)
> - `go-backend-template/test/**` (эталон таксономии e2e/smoke-харнеса) и
>   `go-backend-template/.claude/rules/tests-pipeline.md` + `.../skills/triage-failure/SKILL.md`
>   (RED-first дисциплина — зеркалим по смыслу)
>
> Метки источников: **[ПРОВЕРЕНО]** — из reference/20 / testkit-исследования / go-эталона;
> **[ТРЕБУЕТ ПРОВЕРКИ]** — вывод по аналогии, сверить на целевых версиях
> aiogram 3.28 / aiogram_dialog 2.6 / dishka 1.10.x при реализации шаблона.

---

## 0. TL;DR — пирамида и правила

```
        ▲  fewer, slower, need Docker / real Telegram
        │
   e2e  │  опц., за флагом: реальный Bot API + тестовый бэкенд            (-m e2e)
        │  ── граница CI-only / on-demand ──
integr. │  testcontainers: start_redis (FSM/dedup), start_nats (push)    (-m integration)
        │  ── граница `make check` (быстрый gate) ──
backend │  мок gateway: respx (httpx) ИЛИ fake Protocol-адаптер;
 -mock  │  идемпотентность / маппинг ошибок / breaker-деградация         (unit, no I/O)
        │
 dialog │  BotClient + MockMessageManager + JsonMemoryStorage;
 -flow  │  прогон сценариев диалога; gateway подменён dishka-override     (unit, no I/O)
        │
  unit  │  pure policy.py, error-mapping, validators (initData/deep-link),
        │  render-логика виджетов где возможно                           (unit, no I/O)
        ▼  many, fast, deterministic
```

**Инварианты (зеркало go-`tests-pipeline.md`):**
- `make check` = `ruff format --check` + `ruff check` + `mypy src tests` +
  `pytest -m "not integration and not e2e"`. Зелёный = claim «готово». Висит на `pre-push`.
- CI гоняет `integration` (есть Docker); `e2e` — за флагом/on-demand (нужен реальный
  Bot API). Маркеры селектят, каталоги организуют (как `test/README.md §Разделение зон`).
- **RED-first для багфиксов обязателен** (см. §8): падающий тест, воспроизводящий баг
  **по той же причине** → фикс → зелёный → оба файла одним `fix(...)`-коммитом
  (`tests-pipeline.md §TDD`). Багфикс идёт в `triage-failure`, не в `plan`.
- `time.Now()` в коде запрещён — инжектится `clockkit.Clock`; в тестах — **Fixed clock**
  (детерминизм; go-аналог — `clockkit.Clock` инъекция).

---

## 1. Таксономия каталога `tests/` (зеркало go-backend `test/`)

go-эталон разводит зоны по подпапкам, маркеры селектят (`test/README.md`,
`test/pyproject.toml`). Зеркалим, адаптируя под бот-специфику (нет SQL/huma — есть
диалоги/gateway):

```
tests/
  conftest.py            # корневые фикстуры: dp/client/message_manager/container/fake_backend/clock
  unit/                  # @pytest.mark.unit (дефолт) — без I/O, без Docker
    test_policy.py       #   pure policy.py: admin-allowlist, rate-limit-решения
    test_error_mapping.py#   backend HTTPStatusError/BreakerOpenError → user-facing текст
    test_validators.py   #   WebApp initData (HMAC), deep-link start-token (JWT/opaque)
    test_widgets.py      #   render-логика кастомных Text/виджетов где возможно
  dialog/                # @pytest.mark.dialog — BotClient-флоу, gateway замокан
    conftest.py          #   dp-фикстура диалогов + override gateway → FakeBackendGateway
    test_main_menu.py    #   /start → главное меню → переходы (локаторы кнопок, fullmatch!)
    test_wizard.py       #   многошаговый TextInput-мастер (см. reference/20 §6.1)
    test_unknown_intent.py #  stale callback после рестарта → рестарт в меню (mega §6)
  backend/               # @pytest.mark.unit — контракт gateway↔бэкенд
    test_gateway_respx.py#   respx-мок httpx: статусы/ретраи/идемпотентность
    test_breaker.py      #   BreakerOpenError → BackendUnavailable деградация
  integration/           # @pytest.mark.integration — testcontainers, нужен Docker
    conftest.py          #   start_redis/start_nats фикстуры (session-scope)
    test_fsm_redis.py    #   реальный Redis: FSM-storage round-trip, dedup update_id
    test_push_nats.py    #   реальный NATS: событие бэкенда → bot.send_message (мок Bot)
  e2e/                   # @pytest.mark.e2e — опц., за флагом; реальный Bot API + бэкенд
    test_smoke_flow.py   #   happy-path против тестового Bot API (если включён)
  _fakes/                # переиспользуемые фейки (не тесты): FakeBackendGateway, fixtures-data
    gateway.py           #   in-memory Protocol-реализация BackendGateway
    builders.py          #   билдеры DTO/ответов бэкенда (зеркало test/scenarios go)
```

**Соответствие go→bot:**

| go `test/` | bot `tests/` | роль |
|---|---|---|
| `client/` (типизированный httpx-клиент) | `_fakes/gateway.py` + respx | транспорт к бэкенду (там — к своему API; тут — мок чужого) |
| `scenarios/` (step-функции без ассертов) | `_fakes/builders.py` | переиспользуемые билдеры данных |
| `infra/` (pg/nats/redis интроспекция) | `integration/conftest.py` (testkit) | доступ к side-effects: Redis/NATS |
| `smoke/` (`-m smoke`) | `e2e/` (`-m e2e`) | критический happy-path |
| `e2e/` (по доменам, `-m e2e`) | `dialog/` (`-m dialog`) | сценарии «по экранам» (тут — диалоги, не HTTP) |
| `conftest.py` (session-стек) | `integration/conftest.py` | session-фикстуры контейнеров |

> Отличие от go: у бота **нет своей БД** (`_research/05 §7` — pgkit боту не нужен),
> поэтому нет `infra/pg.py`/миграций/seed-admin. Side-effects бота — Redis (FSM/dedup)
> и NATS (push), их интроспекция — через `testkit`-фикстуры, не через ручной psycopg.

---

## 2. Маркеры и pytest-конфиг

`pyproject.toml` (порт `test/pyproject.toml` + pytest-конвенций pylibinfra из
`_research/03 §1.2`):

```toml
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
pythonpath = ["src", "tests"]
asyncio_mode = "auto"                    # как pylibinfra — без @pytest.mark.asyncio на каждом
addopts = "-ra --strict-markers --strict-config --import-mode=importlib"
markers = [
  "unit: быстрый тест без I/O (дефолт-слой, входит в make check)",
  "dialog: BotClient-флоу диалога с замоканным gateway (входит в make check)",
  "integration: testcontainers (Redis/NATS), нужен Docker — CI-only",
  "e2e: реальный Bot API + тестовый бэкенд, за флагом — on-demand",
]
```

Gate-селекторы (порт `make test`/`make e2e-smoke` из `_research/03 §1.3`):

```
make test   → uv run pytest -m "not integration and not e2e" -q   # = go test -short
make int    → uv run pytest -m integration                        # Docker, CI
make e2e    → uv run pytest -m e2e                                 # за флагом
```

> `--strict-markers` (как go-эталон) — опечатка в маркере = ошибка, а не молчаливый
> прогон. `asyncio_mode="auto"` важен: и `BotClient.send/click`, и httpx, и testkit-фикстуры
> — async; иначе пришлось бы вешать `@pytest.mark.asyncio` на каждый (reference/20
> примеры используют его явно, но в авто-режиме он не нужен).

---

## 3. Слой 1 — Unit (быстрые, без I/O)

Аналог `go test -short`. Покрывают **чистую** логику бота, без aiogram-пайплайна.

### 3.1 Pure policy.py

Бот-`policy.py` (зеркало go-`user/policy.go`, `test/README.md §authz`) — решения
admin-allowlist / rate-limit / можно-ли-действие, без I/O:

```python
# tests/unit/test_policy.py
import pytest
from bot.policy import can_admin, RateDecision, decide_rate

@pytest.mark.parametrize("uid,allow", [(111, True), (222, False)])
def test_admin_allowlist(uid: int, allow: bool) -> None:
    assert can_admin(uid, admins={111, 333}) is allow

def test_rate_limit_blocks_after_threshold() -> None:
    # чистая функция (счётчик/окно передаются аргументами, не Redis)
    assert decide_rate(hits=6, window_max=5) is RateDecision.BLOCK
```

### 3.2 Маппинг ошибок backend → user

Критичный для UX слой (`_research/05 §1`: бот **обязан** ловить `BreakerOpenError` и
показывать «сервис недоступен» вместо 500). Маппинг — чистая функция от исключения:

```python
# tests/unit/test_error_mapping.py
import httpx, pytest
from pylibinfra.httpclient import BreakerOpenError
from bot.errors import user_message_for

@pytest.mark.parametrize("exc, expected_key", [
    (BreakerOpenError(),                                    "backend_unavailable"),
    (httpx.HTTPStatusError("", request=..., response=_resp(404)), "not_found"),
    (httpx.HTTPStatusError("", request=..., response=_resp(422)), "validation"),
    (httpx.HTTPStatusError("", request=..., response=_resp(500)), "backend_error"),
    (httpx.TransportError("boom"),                          "network"),
])
def test_backend_error_maps_to_user_text(exc, expected_key) -> None:
    assert user_message_for(exc).key == expected_key
```

> Тестируем **функцию-маппер**, не httpx — она детерминирована, не нужен ни сервер,
> ни respx. respx-уровень (§5) проверяет, что gateway **бросает** эти исключения.

### 3.3 Валидаторы initData / deep-link

- **WebApp `initData`** — HMAC-SHA256 проверка подписи Telegram (фиксированный bot-token
  в тесте, известный валидный/невалидный вектор). Чистая крипто-функция.
- **Deep-link start-token** (`t.me/bot?start=<token>`) — verify JWT через
  `authnkit.JWTParser` (`_research/05 §5`) или opaque-токен. Векторы: валидный /
  протухший (`ErrTokenExpired`) / битая подпись (`TokenError`).

```python
# tests/unit/test_validators.py
import pytest
from bot.webapp import verify_init_data, InvalidInitData

def test_init_data_valid_signature(bot_token: str) -> None:
    assert verify_init_data(_signed(bot_token), bot_token).user_id == 42

def test_init_data_tampered_raises(bot_token: str) -> None:
    with pytest.raises(InvalidInitData):
        verify_init_data(_signed(bot_token) + "x", bot_token)
```

### 3.4 Render-логика виджетов (где возможно)

Кастомные текст-виджеты (подкласс `Text`, как `I18NFormat` в reference/20 §4) имеют
**чистый** `_render_text(data, manager) -> str`. Если виджет не лезет в manager-state,
тестируется напрямую с фейк-`data` и заглушкой manager. Сложные виджеты с состоянием —
лучше через dialog-flow (§4), не unit. **Не gold-plate**: рендер целых окон —
дешевле прогнать `BotClient`-ом и проверить `one_message().text`, чем мокать `Window`.

---

## 4. Слой 2 — Dialog-flow тесты (BotClient-харнесс)

Сердце стратегии. **reference/20 §1**: вместо реального бота поднимается обычный
`Dispatcher`, в `setup_dialogs` подсовывается `MockMessageManager` (перехватывает
«отправленные» сообщения, не ходит в Telegram), события скармливаются `BotClient`-ом
через `dp.feed_update(...)` — **прогоняется весь реальный пайплайн** middleware /
фильтров / диалогов.

### 4.1 Базовые фикстуры (reference/20 §1.5)

```python
# tests/dialog/conftest.py
import pytest
from aiogram import Dispatcher
from aiogram.filters import CommandStart
from aiogram_dialog import setup_dialogs
from aiogram_dialog.test_tools import BotClient, MockMessageManager
from aiogram_dialog.test_tools.memory_storage import JsonMemoryStorage

from bot.dialogs import dialog_router
from bot.handlers import start
from tests._fakes.gateway import FakeBackendGateway

@pytest.fixture
def message_manager() -> MockMessageManager:
    return MockMessageManager()

@pytest.fixture
def fake_gateway() -> FakeBackendGateway:
    return FakeBackendGateway()           # in-memory, программируем ответы по тесту

@pytest.fixture
def dp(message_manager: MockMessageManager, fake_gateway: FakeBackendGateway) -> Dispatcher:
    dp = Dispatcher(storage=JsonMemoryStorage())     # JSON-storage ловит несериализуемый dialog_data
    dp.message.register(start, CommandStart())
    dp.include_router(dialog_router)
    setup_dialogs(dp, message_manager=message_manager)   # ← ключевая строка (reference/20 §1.6)
    return dp

@pytest.fixture
def client(dp: Dispatcher) -> BotClient:
    return BotClient(dp)                  # user_id=1, chat_id=1 по умолчанию
```

> Подмена gateway: см. §4.4 — два пути (dishka-override на REQUEST-провайдер ИЛИ
> middleware-data инъекция в конструктор `Dispatcher(...)`).
> `JsonMemoryStorage` **обязателен** (reference/20 §1.4): сериализует `dialog_data` в
> JSON-строку → ловит несериализуемые значения уже в тесте (реальный
> `aiogram.RedisStorage` тоже требует JSON-совместимости).

### 4.2 Канонический флоу-тест

```python
# tests/dialog/test_main_menu.py
import re
import pytest
from aiogram_dialog.test_tools.keyboard import InlineButtonTextLocator, InlineButtonDataLocator

@pytest.mark.dialog
async def test_start_opens_main_menu(client, message_manager, fake_gateway) -> None:
    fake_gateway.profile = {"name": "Alice"}            # программируем ответ бэкенда
    await client.send("/start")
    msg = message_manager.one_message()                 # ровно одно сообщение показано
    assert "Главное меню" in msg.text

@pytest.mark.dialog
async def test_navigate_to_profile(client, message_manager, fake_gateway) -> None:
    fake_gateway.profile = {"name": "Alice"}
    await client.send("/start")
    menu = message_manager.one_message()

    message_manager.reset_history()                     # между шагами — обязательно
    cb_id = await client.click(menu, InlineButtonDataLocator(re.compile("menu:profile")))
    message_manager.assert_answered(cb_id)              # callback отвечен
    assert "Alice" in message_manager.one_message().text
```

### 4.3 Локаторы кнопок — `fullmatch`! (reference/20 §1.3)

**Главный подводный камень**: `InlineButtonTextLocator(regex)` использует
`regex.fullmatch(button.text)`, **не** `search`. Кнопка `"➡️ Профиль"` **не** найдётся
по `InlineButtonTextLocator("Профиль")`.

| Локатор | Когда брать |
|---|---|
| `InlineButtonTextLocator(re.compile(".*Профиль.*"))` | текст с эмодзи/пробелами — оборачивай `.*…*.*` |
| `InlineButtonDataLocator(re.compile("menu:profile"))` | **предпочтительно** — callback_data стабильнее текста (не зависит от i18n/эмодзи) |
| `InlineButtonPositionLocator(row, col)` | когда важна позиция (layout-тесты) |

> Рекомендация шаблона: давать кнопкам осмысленные `id`/`callback_data` и в тестах
> локатить по **data**, а не по тексту — переживает локализацию и редизайн подписей.
> Кликать можно только по кнопкам **с callback_data** (reference/20 §1.1: `Url`/`WebApp`/
> reply-кнопки `click`-ом не нажать; reply-кнопки — через `client.send(<текст>)`,
> reference/20 §1.1).

### 4.4 Подмена BackendGateway-порта в dialog-флоу

Два пути (оба корректны; выбирать по тому, как бот резолвит gateway):

**(A) dishka test-override** (`_research/06 §3.2` + override-механика) — если gateway
резолвится через `dishka.integrations.aiogram_dialog.FromDishka` в getter'ах/on_click.
Подменяем провайдер на REQUEST/APP-scope фейк до `setup_dishka`:

```python
# tests/dialog/conftest.py (вариант с dishka)
from dishka import make_async_container, Provider, Scope, provide
from dishka.integrations.aiogram import setup_dishka, AiogramProvider
from bot.ports import BackendGateway

class _FakeGatewayProvider(Provider):
    def __init__(self, fake: FakeBackendGateway):
        super().__init__(); self._fake = fake
    @provide(scope=Scope.APP)
    def gateway(self) -> BackendGateway:        # ключ = Protocol-порт
        return self._fake

@pytest.fixture
def container(fake_gateway):
    # вместо боевого HttpClientProvider/BackendGatewayProvider — фейк-провайдер
    return make_async_container(_FakeGatewayProvider(fake_gateway), AiogramProvider())

@pytest.fixture
def dp(message_manager, container):
    dp = Dispatcher(storage=JsonMemoryStorage())
    dp.message.register(start, CommandStart())
    dp.include_router(dialog_router)
    setup_dialogs(dp, message_manager=message_manager)
    setup_dishka(container=container, router=dp)   # после include_router
    return dp
```

**(B) Прямая middleware-data инъекция** (reference/20 §1.5: «зависимости внедряются в
конструктор `Dispatcher(...)` и доступны в getter'ах/хендлерах как kwargs») — проще,
если бот не завязан жёстко на dishka в диалогах:

```python
dp = Dispatcher(storage=JsonMemoryStorage(), gateway=fake_gateway)
# getter:  async def get_profile(gateway, **kwargs): return {"p": await gateway.profile(...)}
```

> **Решение шаблона:** диалоги получают gateway через **Protocol-порт** (`bot.ports.BackendGateway`),
> а не конкретный `pylibinfra.httpclient.Client`. Тогда фейк (вариант A/B) подменяется
> тривиально, а respx (§5) тестирует **боевую** реализацию порта отдельно. Это go-паттерн
> «мокай интерфейсы домена (Repository), не `*pgxpool.Pool`» из `tests-pipeline.md §Anti-patterns`,
> перенесённый на gateway.

### 4.5 `UnknownIntent` и встроенный About (reference/20 §3, §5.6)

- После `setup_dialogs` в роутере появляется **лишний** диалог-группа `ABOUT`
  (`_include_default_dialogs`) — учитывать в тестах, что считают диалоги/переходы.
- Обязателен тест на `UnknownIntent`-error-handler (mega §6): stale callback после
  «рестарта процесса» (новый `Dispatcher` на тот же storage) → бот отвечает на callback,
  удаляет старое сообщение, `start(Main.MAIN, mode=RESET_STACK, show_mode=SEND)`.

### 4.6 Подводные камни (reference/20 §1.6)

- `one_message()` **падает** при 0 или >1 показанных сообщений — между логическими
  шагами `reset_history()`.
- При `client.send(<текст>)` диалог по умолчанию **перерисовывает окно новым сообщением**
  (reference/20 §7 FAQ) → в `sent_messages` появится новое; учитывать в ассертах.
- `SimpleEventIsolation` подключается автоматически — два одновременных `/start`
  обрабатываются строго по одному (полезно для теста дедупа в §6).

---

## 5. Слой 3 — Backend-mock (контракт gateway ↔ бэкенд)

Проверяет **боевую** реализацию `BackendGateway` поверх `pylibinfra.httpclient.Client`
(`_research/05 §1`): статусы, ретраи, идемпотентность, breaker-деградация. Два инструмента:

### 5.1 respx (мок httpx-транспорта) — предпочтительно для HTTP-семантики

```python
# tests/backend/test_gateway_respx.py
import httpx, pytest, respx
from pylibinfra.httpclient import Client, new_config
from bot.gateway import HttpBackendGateway     # боевая реализация порта
from bot.errors import NotFound

@pytest.fixture
async def gateway() -> HttpBackendGateway:
    async with httpx.AsyncClient(base_url="http://backend") as http:
        yield HttpBackendGateway(Client(new_config(base_url="http://backend"), http))

@respx.mock
@pytest.mark.unit
async def test_profile_maps_404_to_not_found(gateway) -> None:
    respx.get("http://backend/api/v1/users/42").mock(return_value=httpx.Response(404))
    with pytest.raises(NotFound):
        await gateway.profile(42)

@respx.mock
@pytest.mark.unit
async def test_5xx_retried_then_succeeds(gateway) -> None:
    route = respx.get("http://backend/api/v1/users/42").mock(side_effect=[
        httpx.Response(503), httpx.Response(503), httpx.Response(200, json={"name": "A"}),
    ])
    assert (await gateway.profile(42))["name"] == "A"
    assert route.call_count == 3            # httpclient ретраит 5xx (config max_retries=3)
```

> respx перехватывает на уровне httpx-транспорта → **реальные** tenacity-ретраи и OTel
> httpclient отрабатывают (`_research/05 §1`: 4xx не ретраятся, 5xx ретраятся
> `max_retries+1`). Это единственный способ проверить retry-поведение без сети.

### 5.2 Breaker-деградация

```python
@pytest.mark.unit
async def test_open_breaker_degrades(gateway) -> None:
    # после N подряд 5xx purgatory открывает breaker → BreakerOpenError быстрым фейлом
    with respx.mock:
        respx.get(url__regex=r".*/users/.*").mock(return_value=httpx.Response(503))
        for _ in range(6):                  # failure_threshold=5 (_research/05 §1)
            with pytest.raises(Exception):
                await gateway.profile(42)
        # следующий вызов — мгновенный BreakerOpenError без обращения к сети
        from pylibinfra.httpclient import BreakerOpenError
        with pytest.raises(BreakerOpenError):
            await gateway.profile(42)
```

### 5.3 Идемпотентность / fake Protocol-адаптер

Для **поведенческих** тестов (idempotency-key прокидывается, дубль возвращает тот же
ответ) и как замена в dialog-флоу — `FakeBackendGateway` (Protocol-реализация, без httpx):

```python
# tests/_fakes/gateway.py
from bot.ports import BackendGateway

class FakeBackendGateway(BackendGateway):
    """In-memory фейк порта. Программируется тестом, считает вызовы."""
    def __init__(self) -> None:
        self.profile_data: dict | None = None
        self.calls: list[tuple] = []
        self._idempotent: dict[str, object] = {}

    async def profile(self, user_id: int) -> dict:
        self.calls.append(("profile", user_id))
        if self.profile_data is None:
            from bot.errors import NotFound; raise NotFound()
        return self.profile_data

    async def create_order(self, *, idem_key: str, payload: dict) -> dict:
        if idem_key in self._idempotent:        # дубль → тот же ответ (идемпотентность)
            return self._idempotent[idem_key]
        res = {"order_id": len(self._idempotent) + 1}
        self._idempotent[idem_key] = res
        return res
```

> **Решение:** respx для **HTTP-семантики** (статусы/ретраи/breaker — нужна боевая
> httpclient-цепочка); FakeBackendGateway для **доменного поведения** и для подмены в
> dialog-флоу (быстро, без httpx). Оба реализуют один Protocol-порт — go-паттерн
> «port + fake adapter» (`triage-failure §5: depguard → port+adapter`).

---

## 6. Слой 4 — Integration (testcontainers)

Маркер `integration` (≈ go build-tag `integration`, `tests-pipeline.md §Интеграционные`).
Нужен Docker. Поднимает **реальный** Redis (FSM/dedup) и NATS (push) через
`pylibinfra.testkit` (`_research/05 §8`).

### 6.1 Фикстуры контейнеров (testkit API)

`testkit` — framework-agnostic async-context-manager'ы (`_research/05 §8`):
`start_redis() → RedisFixture` (`.url`, `.cache()→RedisCache`), `start_nats() → NatsFixture`
(`.url`, `.bus()→NatsBus`), `eventbus.Recorder` (in-memory фейк `Bus`).

```python
# tests/integration/conftest.py
import pytest
from pylibinfra.testkit import start_redis, start_nats

@pytest.fixture(scope="session")
async def redis_fx():
    async with start_redis() as fx:          # redis:7-alpine, t.Cleanup гасит контейнер
        yield fx

@pytest.fixture(scope="session")
async def nats_fx():
    async with start_nats() as fx:           # nats:2-alpine
        yield fx
```

### 6.2 FSM/dedup на реальном Redis

```python
# tests/integration/test_fsm_redis.py
import pytest
from bot.dedup import already_seen

@pytest.mark.integration
async def test_update_dedup_real_redis(redis_fx) -> None:
    async with redis_fx.cache() as cache:        # RedisCache (_research/05 §2)
        assert await already_seen(cache, 42) is False
        assert await already_seen(cache, 42) is True     # дубль update_id
```

> Можно гонять и FSM round-trip: отдать `redis.Redis` в `aiogram.RedisStorage`, прогнать
> `BotClient`-флоу поверх реального Redis-storage вместо `JsonMemoryStorage` — проверяет,
> что `dialog_data` реально переживает сериализацию в Redis (`_research/05 §2`:
> «шарить один redis.Redis между aiogram-storage и cachekit — нормально»).

### 6.3 Push-подписчик на реальном NATS

```python
# tests/integration/test_push_nats.py
import pytest
from unittest.mock import AsyncMock
from pylibinfra.natskit import publish_json
from bot.push import setup_notifications

@pytest.mark.integration
async def test_order_paid_triggers_send(nats_fx) -> None:
    bot = AsyncMock()                            # send_message замокан (не ходим в Telegram)
    async with nats_fx.bus() as bus:
        await setup_notifications(bus, bot, cache=...)   # подписка ДО publish
        await publish_json(bus, "orders.paid", {"order_id": 7, "user_id": 42})
        await _wait_until(lambda: bot.send_message.called)   # core NATS async
    bot.send_message.assert_awaited_once()
```

> **Подводный камень (core NATS at-most-once, `_research/05 §3`):** подписка должна встать
> **до** publish (как go `NatsCollector` в `test/README.md §Side-effect ассерты`). Для
> чисто-unit проверки «бот опубликовал правильное событие» — `eventbus.Recorder` без NATS
> (`recorder.published(subject)`/`last`/`count`), это слой backend-mock, не integration.

---

## 7. Слой 5 — e2e (опционально, за флагом)

Маркер `e2e`, **не** входит в `make check`, on-demand (нужен реальный/тестовый Bot API
и тестовый бэкенд). Аналог go-`smoke` (`test/README.md`), но для бота — дороже и
флакируется (внешний Telegram). Запуск за флагом окружения (`E2E_BOT_TOKEN` задан →
тесты собираются, иначе `pytest.skip`).

```python
# tests/e2e/test_smoke_flow.py
import os, pytest
pytestmark = pytest.mark.skipif(not os.getenv("E2E_BOT_TOKEN"), reason="e2e off")

@pytest.mark.e2e
async def test_boot_and_start(real_bot_session, test_backend_url) -> None:
    # отправить /start реальному боту через тестовый Bot API, проверить ответ
    ...
```

> **Не gold-plate:** e2e опционален. go-эталон сознательно держит часть путей вне e2e
> (`test/README.md §Покрытие`: «confirm-roundtrip — дом usecase/integration-тестов»).
> Для бота большая часть UX-покрытия достигается **dialog-флоу** (§4) без реального
> Telegram; e2e — только smoke «бот вообще поднимается и отвечает».

---

## 8. DI в тестах (dishka test-container override)

Из `_research/06`: `make_async_container(*providers)` собирает APP-контейнер; в тестах —
**override** боевых провайдеров фейками. Ключевые подмены:

| Боевой провайдер | Тест-override | Источник |
|---|---|---|
| `HttpClientProvider` / `BackendGatewayProvider` | `_FakeGatewayProvider(FakeBackendGateway)` (§4.4) | `_research/06 §3.2` |
| `clockkit.ClockProvider` (боевые часы) | **Fixed clock** — `clockkit.Clock` с зафиксированным `now()` | `tests-pipeline §Anti-patterns` (`time.Now()` запрещён) |
| `natskit.NatsProvider` (реальный NATS) | `eventbus.Recorder` как `Bus` (unit) / `start_nats` (integration) | `_research/05 §8` |
| `cachekit.CachekitProvider` (Redis) | in-memory `Cache`-фейк (unit) / `start_redis` (integration) | `_research/05 §8` |
| `AppConfigProvider` | тестовый Config с фиксированными ENV (bot-token, base_url) | `_research/06 §1` |

```python
# Паттерн override: тот же container, но фейк-провайдеры вместо боевых kit-провайдеров.
container = make_async_container(
    FixedClockProvider(now=datetime(2026, 6, 7, tzinfo=UTC)),  # детерминизм
    _FakeGatewayProvider(fake_gateway),                        # бэкенд замокан
    _RecorderBusProvider(recorder),                            # NATS-фейк (unit)
    AppConfigProvider(),                                       # тестовый Config
    AiogramProvider(),
)
# !!! container.close() обязателен (_research/06 §5) — иначе не отработают yield-cleanup'ы.
```

> **Решение:** один и тот же набор **бизнес**-провайдеров, но **kit**-провайдеры
> (httpclient/cachekit/natskit/clock) заменяются фейками/контейнерами по слою теста. Это
> прямой аналог go-`tests-pipeline §Моки`: мокаем порты, не транспорт.
> `clockkit.Clock` Fixed обязателен везде, где код зависит от времени (TTL dedup,
> breaker recovery, rate-limit окна) — иначе тесты флакируются.

---

## 9. Gate и RED-first дисциплина

### 9.1 `make check` (порт go-`make check` + pylibinfra-петли, `_research/03 §1`)

```
make check  =  fmt(--check) → lint → typecheck → test(not integration, not e2e)
            =  uv run ruff format --check .
               uv run ruff check .
               uv run mypy src tests
               uv run pytest -m "not integration and not e2e" -q
```

- Единственный канонический гейт; зелёный = claim «готово». Висит на **`pre-push`**
  git-хуке (`--no-verify` запрещён политикой, `_research/03 §4`; аварийный обход —
  `SKIP_PREPUSH=1`).
- `pre-commit`: `ruff format --check` → `ruff check` → `mypy src` (быстрая полоса).
- CI (`ci.yml`, порт pylibinfra `_research/03 §3`): job `test` гоняет
  `pytest -m "not integration"` (быстрая полоса) **затем** `pytest -m integration`
  (testcontainers на runner'е с Docker). `e2e` — отдельный on-demand workflow за
  секретом `E2E_BOT_TOKEN`.

### 9.2 RED-first (triage-failure-аналог)

Зеркало go-`triage-failure/SKILL.md` + `tests-pipeline §TDD`. Для **багфикса**:

1. Написать **падающий** тест, воспроизводящий баг — падать должен **по той же причине**,
   что и прод-баг (иначе тестируется другое). Имя `test_<behavior>` / `test_<method>_<scenario>`.
2. `pytest -k test_new` → **red**. Подтвердить, что red — твой red, не инфра.
3. **Только теперь** править прод-код.
4. `pytest -k test_new` → green.
5. `pytest tests/<area>` → весь модуль green (не сломал соседей).
6. Коммит: оба файла одним `fix(<scope>): <one-liner>`.

Багфикс идёт в `triage-failure`, **не** в `plan`. Anti-patterns (1:1 из go):
- ❌ «перепиши тест, чтобы проходил» — сокрытие, не фикс.
- ❌ фикс без теста для багфикса — TDD не опциональна для багов.
- ❌ большой «while we're at it» — багфикс = маленький коммит.

### 9.3 Категории падений → где смотреть (порт triage-таблицы под Python/бот)

| Тип | Признаки | Где смотреть |
|---|---|---|
| **Lint** | `ruff` коды (`E/F/B/SIM/ASYNC/S`) | `uv run ruff check <path>` |
| **Type** | `mypy` error | `uv run mypy <path>` — strict, pydantic-plugin |
| **Unit/dialog** | `FAILED tests/...`, assertion | `pytest <path> -x -vv` |
| **Dialog-локатор** | `ValueError: button not found` | проверь `fullmatch`! (§4.3) — эмодзи/текст не совпал |
| **Integration** | падает только под `-m integration` | Docker не поднят / порт занят / подписка после publish (§6.3) |
| **respx** | `AllMockedAssertionError` | незамоканный URL — добавь route или `assert_all_called=False` |
| **Flaky** | проходит через раз | `time.Now()` вместо Fixed clock; подписка после publish; гонка стека |

---

## 10. Чек-лист для шаблона (зона M)

- [ ] `tests/` зеркалит go-`test/`: `unit/ dialog/ backend/ integration/ e2e/ _fakes/`.
- [ ] Маркеры `unit/dialog/integration/e2e` + `--strict-markers`; `asyncio_mode=auto`.
- [ ] Dialog-флоу: `BotClient` + `MockMessageManager` + `JsonMemoryStorage`,
      `setup_dialogs(dp, message_manager=...)`. Локаторы — по **callback_data** (fullmatch!).
- [ ] gateway — **Protocol-порт**; подмена: FakeBackendGateway (dialog/поведение) +
      respx (HTTP-семантика/ретраи/breaker).
- [ ] `clockkit.Clock` **Fixed** везде, где есть время (TTL/breaker/rate-limit).
- [ ] testcontainers через `pylibinfra.testkit` (`start_redis`/`start_nats`); подписка
      NATS встаёт **до** publish.
- [ ] `make check` = ruff+mypy+pytest(not integration, not e2e); CI гоняет integration;
      e2e за флагом. `pre-push` = `make check`.
- [ ] RED-first для багфиксов: red(по той причине)→фикс→green→оба файла одним `fix(...)`.
- [ ] Учесть встроенный About-диалог и обязательный `UnknownIntent`-handler в тестах.
- [ ] `container.close()` в тестах (иначе yield-cleanup'ы kit'ов не отработают).

---

## Открытые вопросы / проверить при реализации

1. **[ТРЕБУЕТ ПРОВЕРКИ]** Совместимость `dishka.integrations.aiogram_dialog` (override
   gateway в getter'ах) на aiogram_dialog 2.6 + dishka 1.10.x (`_research/06 §3.2`,
   open-вопрос). Fallback — middleware-data инъекция (§4.4 вариант B).
2. **[ТРЕБУЕТ ПРОВЕРКИ]** Поведение `BotClient` с навешанным `setup_dishka` — порядок
   `setup_dialogs` vs `setup_dishka` и доступность REQUEST-контейнера в getter'ах под
   `feed_update` (reference/20 гоняет реальный пайплайн, dishka-middleware должна успеть).
3. **[ТРЕБУЕТ ПРОВЕРКИ]** `eventbus.Recorder` точная сигнатура (`published`/`last`/`count`)
   и подойдёт ли как drop-in `Bus` для unit-теста подписчика (`_research/05 §8`).
4. **[ТРЕБУЕТ ПРОВЕРКИ]** respx + tenacity-ретраи httpclient: что `route.call_count`
   реально считает попытки (а не один логический вызов) — сверить на боевой config.
5. **[ТРЕБУЕТ ПРОВЕРКИ]** Нужен ли отдельный тестовый Bot API (telegram-bot-api docker)
   для e2e или достаточно мок-сервера — решение по флагу, не блокирует пирамиду.

---

## Источники

- aiogram_dialog test_tools (BotClient/MockMessageManager/JsonMemoryStorage/локаторы) —
  `telegram-bot-template/aiogram-dialog-docs/reference/20-testing-preview-i18n-faq.md`
  (§1.1–1.6, §3, §5, §7).
- pylibinfra integration-киты (httpclient/cachekit/natskit/testkit) —
  `design/_research/05-pylibinfra-integration-kits.md` (§1, §2, §3, §8).
- dishka DI/override — `design/_research/06-dishka-aiogram-di.md` (§1, §3, §5).
- pytest-тулинг/gate/CI — `design/_research/03-go-template-tooling-ci-docs.md` (§1, §3, §4).
- go-эталон таксономии/дисциплины — `go-backend-template/test/README.md`,
  `.../test/conftest.py`, `.../test/pyproject.toml`,
  `.../.claude/rules/tests-pipeline.md`, `.../.claude/skills/triage-failure/SKILL.md`.
