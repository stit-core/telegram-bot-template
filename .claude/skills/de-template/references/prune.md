# de-template › prune reference-фич

`start` / `profile` / `payments` / `lang` / `notifications` (+ `booking`) — учебные reference-фичи. Удаляются на де-темплейтизации **после** того как свои фичи спроектированы (`/dialog-deep-dive`) и сгенерированы (`scaffold feature`) — иначе теряешь живой образец гексагона. Удаляй все точки; недоудаление оставит висящие импорты, осиротевшие StatesGroup, ключи i18n или мёртвые pkg-клиенты.

## Что чем является (решай по фиче)

| фича | роль | прунить? |
|---|---|---|
| `profile` | полный гексагон (state/errors/policy/ports/usecase/views/dialogs/getters/handlers/adapters/provider) поверх pkg-клиента `ProfileAPI` — эталон бэкенд-фичи | да (после своих) |
| `booking` | wizard: все шаги — методы usecase, результаты шагов в `dto.py` (`GuestsStep`), идемпотентный submit | да (после своих) |
| `payments` | dispatcher-level (pre_checkout/successful_payment, XTR), wire-`Offer` → доменный `Order(Money)` | прунь, **если бот без платежей**; иначе адаптируй |
| `notifications` | NATS-router + `deliver_*` — образец push | прунь, **если бот без push**; иначе адаптируй |
| `lang` | смена локали + i18n | прунь, **если бот моноязычный**; иначе оставь |
| `start` | корневой `LaunchMode.ROOT` диалог + `/start` + `infra/store.py` (порт поверх cachekit) | **обычно НЕ удалять целиком** — переименуй/перепиши под своё меню; бот без ROOT-диалога не имеет точки входа |

`start` чаще не прунится, а **переделывается**: убираешь кнопки на удалённые фичи (`profile`/`payments`/`lang`), оставляешь корневой ROOT + `/start`=RESET_STACK как каркас своего меню.

## Чеклист удаления одной фичи `<name>`

1. **Пакет фичи** — `src/bot/features/<name>/` целиком (`git rm -r`).
2. **StatesGroup** — класс `<Name>` в `src/bot/platform/dialogs/states.py`. ⚠️ Удаляй только если фичу реально удаляешь и **бот ещё не деплоился** с этим State; на живом боте удаление State — это `state-migration`, не prune.
3. **Регистрация в `app.py`** (единый composition root):
   - импорт фичи в `from bot.features import …` и `<name>.Provider()` в `build_container()`;
   - её `dialog` из `RouterBundle` (метод `routers` `ExtensionProvider`);
   - её `cmd_spec`/`command_specs` из `CommandBundle` (метод `commands`);
   - для `notifications` — вызов `build_router(...)` в `NotifierBundle` (метод `notifiers`) и `stream_bus`/`NatsProvider()`, если NATS больше не нужен;
   - для `lang` — `ChainResolver`/`FromCachePref`/`LocalePrefStore` в `resolver` (если убираешь i18n-выбор — упрости до `FromUserLanguage()` или убери `OptionalLocaleResolver`).
4. **pkg-клиент фичи** — если его больше никто не использует: модуль `src/bot/pkg/http_client/internal/<name>.py` + его `@provide` в `pkg/http_client/provider.py`. Если с ним умирает целый бэкенд — запись в `BackendsConfig` (`config.py`) и его `*_BASE_URL` env (`.env.example`; инфра-поверхность → `infra-handoff`).
5. **i18n-каталоги** — `src/bot/locales/<lang>/<name>.ftl` (по всем локалям) + строка `<name>.ftl` в `_I18N_RESOURCES` (`config.py`). Удаляй ключи с префиксом фичи.
6. **cross-feature связи** — если другая фича читала эту через `adapters.py`/`ports.py` (напр. `profile` читает `start` через `OnboardingReader`): убери порт+адаптер у потребителя, иначе провайдер не соберётся.
7. **platform-glue** — если фича писала/читала общий ключ (`start` пишет `chat_link_key`/`onboard_key` из `platform/links.py` через `infra/store.py`, читает `notifications`): удаляешь обе стороны или оставляешь общий контракт. Осиротевший писатель/читатель — баг.
8. **Тесты** — `tests/flows/test_<name>_flow.py`, `tests/unit/test_<name>*.py`, `tests/pkg/test_<name>_api.py` (вместе с pkg-клиентом) + его `@provide` в `FakesProvider` (`tests/_fakes/harness.py`), упоминания в `tests/flows/test_composition.py` (список диалогов `for dialog in (...)`).

## Что НЕ удалять (платформа/pkg-каркас, не фичи)

- `src/bot/platform/{identity,dialogs}/` — платформенная инфра-glue. Переиспользуется своими фичами.
- `src/bot/platform/dialogs/{common,errors,states}.py` — общие виджеты, `AppErrorUX`, каталог StatesGroup. Каркас; чистится содержимое, не файлы.
- `src/bot/shared/` — pure-утилиты (`decision`/`errors`/...). Переиспользуются всеми фичами.
- `src/bot/pkg/http_client/{provider,internal/codec}.py` — каркас клиентов API (реестр + валидация контрактов). Чистятся провайды удалённых клиентов, не каркас.
- `docs/stack/_templates/` — скаффолд-шаблоны стека.

Условно (удаляй только при осознанном решении стека):
- `src/bot/platform/webapp/` — **только** если форк без Mini App (`docs/stack/auth.md`).
- `src/bot/pkg/http_client/` — **только** в local-only боте (секция ниже), когда стек заявил «без бэкенда» (`docs/stack/backends.md` пуст).

## Local-only бот (без бэкенда)

Бот, который **ничего не дёргает по HTTP** (вся логика в Redis/локальном состоянии: меню,
FSM-визарды, контент). Тогда HTTP-слой — мёртвый вес; режь его целиком **после** того как свои
фичи переписаны на локальные store (`features/<имя>/infra/` поверх cachekit, как
`start/infra/store.py: CacheOnboardingStore`).

1. **Backend-фичи** (`profile`/`payments`/`booking` — у всех порт байндится на pkg-клиент) — прунь (чеклист выше) или перепиши порт на `infra/`-store.
2. **`src/bot/pkg/http_client/`** целиком (`git rm -r`) — клиенты, codec, provider.
3. **`app.py`** — убери `ApiClientsProvider()` и `http_client.Provider()` (+ импорты).
4. **`config.py`** — убери `HttpConfig`/`BackendsConfig`/импорт `CORE_BACKEND` (нет `HTTPCLIENT_*`-ручек).
5. **`BotIdentity`** (`platform/identity/identity.py`) — выкинь поле `backend_user_id` (оно жило только ради бэкенда); в `IdentityProvider` убери `_resolve_backend_id`/чтение `backend_link_key`. Останутся `tg_id` + `role`.
6. **`platform/links.py`** — убери `backend_link_key`/`BACKEND_LINK_PREFIX`, если их писал только онбординг под бэкенд.
7. **Тесты/фейки** — `tests/pkg/`, `tests/_fakes/backend.py` (`FakeApiClient`), pkg-провайды и `make_container(..., backend=)` в `tests/_fakes/harness.py`.

Проверка та же (`Verify` ниже): import-linter не должен видеть `bot.pkg`, контейнер собирается без `ApiClients`.

## Verify

```bash
uv run pytest -k collision   # startup-smoke: нет осиротевших/дублирующих StatesGroup
make lint                    # import-linter не ругается на висящие импорты удалённых фич
make check                   # полный гейт
```

Зелёные — prune полный. Красный import-linter с `bot.features.<X>`/`bot.pkg` → недочистил точку 3/4 (регистрация/pkg) или 6 (cross-feature). Красный startup-smoke → осиротевший State в `states.py` (точка 2) или окно ссылается на удалённый State.
