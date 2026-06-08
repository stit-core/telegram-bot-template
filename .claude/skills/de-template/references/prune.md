# de-template › prune reference-фич

`start` / `profile` / `payments` / `lang` / `notifications` — учебные reference-фичи. Удаляются на де-темплейтизации **после** того как свои фичи спроектированы (`/dialog-deep-dive`) и сгенерированы (`scaffold feature`) — иначе теряешь живой образец гексагона. Удаляй все точки; недоудаление оставит висящие импорты, осиротевшие StatesGroup или ключи i18n.

## Что чем является (решай по фиче)

| фича | роль | прунить? |
|---|---|---|
| `profile` | полный гексагон (state/dto/errors/policy/ports/usecase/gateway/views/dialogs/getters/handlers/adapters/provider) — эталон бэкенд-фичи | да (после своих) |
| `payments` | dispatcher-level (pre_checkout/successful_payment, XTR) — образец платежей | прунь, **если бот без платежей**; иначе адаптируй |
| `notifications` | NATS-router + `deliver_*` — образец push | прунь, **если бот без push**; иначе адаптируй |
| `lang` | смена локали + i18n | прунь, **если бот моноязычный**; иначе оставь |
| `start` | корневой `LaunchMode.ROOT` диалог + `/start` | **обычно НЕ удалять целиком** — переименуй/перепиши под своё меню; бот без ROOT-диалога не имеет точки входа |

`start` чаще не прунится, а **переделывается**: убираешь кнопки на удалённые фичи (`profile`/`payments`/`lang`), оставляешь корневой ROOT + `/start`=RESET_STACK как каркас своего меню.

## Чеклист удаления одной фичи `<name>`

1. **Пакет фичи** — `src/bot/features/<name>/` целиком (`git rm -r`).
2. **StatesGroup** — класс `<Name>` в `src/bot/platform/dialogs/states.py`. ⚠️ Удаляй только если фичу реально удаляешь и **бот ещё не деплоился** с этим State; на живом боте удаление State — это `state-migration`, не prune.
3. **Регистрация в `extensions.py`** (`ExtensionProvider`):
   - импорт фичи в `from bot.features import …`;
   - её `dialog` из `RouterBundle` (метод `routers`);
   - её `cmd_spec`/`command_specs` из `CommandBundle` (метод `commands`);
   - для `notifications` — вызов `build_router(...)` в `NotifierBundle` (метод `notifiers`);
   - для `lang` — `ChainResolver`/`FromCachePref`/`LocalePrefStore` в `resolver` (если убираешь i18n-выбор — упрости до `FromUserLanguage()` или убери `OptionalLocaleResolver`).
4. **Регистрация в `app.py`** — `<name>.Provider()` в `make_async_container(...)` и импорт.
5. **i18n-каталоги** — `src/bot/locales/<lang>/<name>.ftl` (по всем локалям) + строка `<name>.ftl` в `_I18N_RESOURCES` (`config.py`). Удаляй ключи с префиксом фичи.
6. **cross-feature связи** — если другая фича читала эту через `adapters.py`/`ports.py` (напр. `profile` читает `start` через `OnboardingReader`): убери порт+адаптер у потребителя, иначе провайдер не соберётся.
7. **platform-glue** — если фича писала/читала общий ключ (`start` пишет `chat_link_key`/`onboard_key` в `platform/links.py`, который читает `notifications`): удаляешь обе стороны или оставляешь общий контракт. Осиротевший писатель/читатель — баг.
8. **Тесты** — `tests/flows/test_<name>_flow.py`, `tests/unit/test_<name>*.py`, упоминания в `tests/flows/test_composition.py` (список диалогов `for dialog in (...)`).

## Что НЕ удалять (платформа, не фичи)

- `src/bot/platform/{identity,dialogs}/` — платформенная инфра-glue. Переиспользуется своими фичами.
- `src/bot/platform/dialogs/{common,errors,states}.py` — общие виджеты, `AppErrorUX`, каталог StatesGroup. Каркас; чистится содержимое, не файлы.
- `src/bot/shared/` — pure-утилиты (`decision`/`errors`/...). Переиспользуются всеми фичами.
- `docs/stack/_templates/` — скаффолд-шаблоны стека.

Условно (удаляй только при осознанном решении стека):
- `src/bot/platform/webapp/` — **только** если форк без Mini App (`docs/stack/auth.md`).
- `src/bot/platform/backend/` — **только** в local-only боте (секция ниже), когда стек заявил «без бэкенда» (`docs/stack/backends.md` пуст).

## Local-only бот (без бэкенда)

Бот, который **ничего не дёргает по HTTP** (вся логика в Redis/локальном состоянии: меню,
FSM-визарды, контент). Тогда backend-слой — мёртвый вес; режь его целиком **после** того как свои
фичи переписаны на локальные store (`cachekit`, как `start.OnboardingStore`/`lang.LocaleStore`).

1. **Backend-фичи** (`profile`/`payments`/`booking` — у всех `gateway.py` поверх `platform/backend`) — прунь (чеклист выше) или перепиши gateway на локальный store.
2. **`src/bot/platform/backend/`** целиком (`git rm -r`) — `client.py`/`errors.py`/`provider.py`.
3. **`app.py`** — убери `HttpClientProvider()` и `BackendProvider()` (+ импорты).
4. **`config.py`** — убери `HttpConfig`/`httpclient` из `AppConfig` (нет `HTTPCLIENT_*`-ручек).
5. **`BotIdentity`** (`platform/identity/identity.py`) — выкинь поле `backend_user_id` (оно жило только ради бэкенда); в `IdentityProvider` убери `_resolve_backend_id`/чтение `backend_link_key`. Останутся `tg_id` + `role`.
6. **`platform/links.py`** — убери `backend_link_key`/`BACKEND_LINK_PREFIX`, если их писал только онбординг под бэкенд.
7. **Тесты/фейки** — `tests/backend/`, `tests/_fakes/backend.py`, `make_container(..., backend=)` параметр.

Проверка та же (`Verify` ниже): import-linter не должен видеть `platform.backend`, контейнер собирается без `Client`.

## Verify

```bash
uv run pytest -k collision   # startup-smoke: нет осиротевших/дублирующих StatesGroup
make lint                    # import-linter не ругается на висящие импорты удалённых фич
make check                   # полный гейт
```

Зелёные — prune полный. Красный import-linter с `bot.features.<X>` → недочистил точку 3/4 (регистрация) или 6 (cross-feature). Красный startup-smoke → осиротевший State в `states.py` (точка 2) или окно ссылается на удалённый State.
