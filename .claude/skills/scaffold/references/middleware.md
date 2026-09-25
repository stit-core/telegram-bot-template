# scaffold › middleware — outer/inner-middleware (граница с tgbotkit)

⚠️ **Прочитай первым.** Outer-middleware-цепочка бота живёт **в `tgbotkit`**, не в шаблоне, и висит на `dp.update` — едином входе и обычных апдейтов, и фоновых событий диалога: RequestId → Dedup → Throttle → Recovery → Observability (`pylibinfra`: `src/pylibinfra/tgbotkit/docs/architecture.md` § Цепочка `dp.update`; rule `tgbotkit-boundary`). Дедуп `update_id` и rate-limit входящих там уже есть — их включают env-ручками. Новая generic-механика — это **инфра**: **PR в `pylibinfra/tgbotkit`** через `infra-handoff`, а не код в шаблоне.

Поэтому у этого варианта несколько дорог. Сначала классифицируй.

## Классификация

| Что нужно | Это… | Куда |
|---|---|---|
| Rate-limit / дедуп входящих апдейтов | уже в kit'е | ручки `BOT_THROTTLE_RPS` / `BOT_DEDUP_ENABLED`, `BOT_DEDUP_TTL` (`.env.example`); новое значение env → `infra-handoff` |
| Новый generic-перехват всех апдейтов (ban-gate, тех-заглушка maintenance) | инфра-механика | **PR в `tgbotkit`** (см. ниже §A) |
| Бизнес-фильтр/обогащение для конкретной фичи/команды (проверка роли, фича-флаг, A/B) | бизнес-логика | в шаблоне, но обычно **не middleware** (см. §B) |
| Новая точка расширения (kit должен дать ещё один хук) | контракт kit'а | **PR в `tgbotkit`** |

## §A. Generic-механика → PR в tgbotkit (не пиши в шаблоне)

Если нужен настоящий middleware на **все** апдейты (ban-gate, maintenance-заглушка):

1. **Не пиши его в `src/bot/`.** Это нарушит `tgbotkit-boundary` (rule) и не покроется тестами kit'а.
2. Оформи через **`infra-handoff`**: `WHAT: новый outer-middleware <X>`, `ACTION: PR в pylibinfra/tgbotkit (цепочка dp.update + конфиг <X>)`, `WHO: pylibinfra`.
3. Место в цепочке — `dp.update`, как у всех middleware кита: через него же `aiogram_dialog` проводит фоновые события диалога (`propagate_event("update")`), поэтому отдельная навеска на `message`/`callback_query`/`DIALOG_EVENT_NAME` не нужна. Позиция относительно RequestId/Dedup/Recovery — часть контракта PR.
4. Шаблон может временно нести механику локально и вынести её PR'ом (rule `tgbotkit-boundary`) — но это явный долг в `## Handoff` плана, не «оставим так».

## §B. Бизнес-перехват в шаблоне — обычно НЕ middleware

Большинство «нужна проверка перед хендлером» решается **без** middleware, средствами, которые шаблон уже даёт:

- **Роль/доступ** — `policy` фичи + `BotIdentity.role` (admin-allowlist из `APP_ADMIN_IDS`, см. `config.py`/`platform/identity`). usecase сам отказывает (`raise errors.Forbidden(...)`), getter показывает мягко.
- **Фильтр на команду** — aiogram-фильтр в `CommandSpec(observer, handler, filters)`: `CommandSpec("message", handler, (F.text, RoleFilter("admin")))`. Фильтр — чистая функция-предикат, бизнес-условие; живёт рядом с фичей.
- **Per-feature предусловие** — проверка в начале usecase/handler (например, «онбординг пройден?» через cross-feature порт `OnboardingReader`).
- **Локаль/i18n** — уже решено `OptionalLocaleResolver` (`ExtensionProvider.resolver` в `app.py`); не пиши свой i18n-middleware.

Если это действительно фильтр (предикат на апдейт) — заведи его как aiogram-фильтр и отдай в `filters` нужного `CommandSpec`, не как middleware:

```python
# features/admin/filters.py — бизнес-предикат (PURE-ish), не middleware
from aiogram.filters import Filter
from aiogram.types import Message


class IsAdmin(Filter):
    def __init__(self, admin_ids: frozenset[int]) -> None:
        self._ids = admin_ids

    async def __call__(self, message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in self._ids
```

## Если всё же нужен локальный middleware на конкретный роутер

aiogram позволяет навесить middleware на отдельный `Router`/`Dialog`. Это допустимо для **бизнес-обогащения данных конкретного диалога** (не generic-инфры). Но:

- на уровне роутера фоновые события диалога приходят в наблюдатель `router.observers[DIALOG_EVENT_NAME]`, а не в `message`/`callback_query` — если middleware должен видеть и их, навесь на оба;
- не дублируй то, что уже даёт kit (request-id, dedup) — получишь двойную обработку;
- если ловишь себя на «это нужно всем диалогам» — это §A (PR в kit), не локальный middleware.

## Тесты + верификация

- фильтр/предикат — unit-тест (pure): admin/не-admin → True/False.
- если завёл локальный middleware — flow-тест, что обогащение дошло до getter/handler.
- `make check`; тронул `app.py`/регистрацию — `pytest -k collision`.

`feat(admin): add IsAdmin filter` (для §B). Для §A — коммита в шаблоне нет, есть `## Handoff` плана + PR в pylibinfra.

## Anti-patterns

- ❌ Писать throttle/dedup в `src/bot/` — они уже в цепочке кита (env-ручки); новый auth/ban-gate — PR в `tgbotkit`.
- ❌ Свой i18n/locale-middleware — уже есть `LocaleResolver` (`ExtensionProvider` в `app.py`).
- ❌ Generic-middleware на `message`/`callback_query` вместо `dp.update` — фоновые события диалога его минуют.
- ❌ Решать роль/доступ через middleware, когда хватает `policy` + `BotIdentity.role` или фильтра на `CommandSpec`.
- ❌ Дублировать kit-механику (request-id/dedup) локальным middleware.
