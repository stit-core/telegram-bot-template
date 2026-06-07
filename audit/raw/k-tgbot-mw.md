# Аудит области k-tgbot-mw — tgbotkit middleware

Область: стандартная outer-цепочка middleware бота в
`pylibinfra/src/pylibinfra/tgbotkit/middleware/` — `dedup`, `throttle`, `recovery`, `request_id`,
`observability` + сборка в `__init__.py` (`install_standard_middleware`). Проверка: порядок
outer/inner, корректность recovery (доходит ли error-UX, не глотает ли молча), throttle/dedup
(ключи, гонки, ложные срабатывания), request_id-проброс, observability (span/метки),
async-корректность.

## Что смотрел

- Все 6 файлов области (`dedup.py`, `observability.py`, `recovery.py`, `request_id.py`,
  `throttle.py`, `__init__.py`).
- Точку сборки: `tgbotkit/module.py:88-110` (`dispatcher`-провайдер) и порядок навешивания
  outer-middleware в `install_standard_middleware` (`__init__.py:40-46`).
- Реальный порядок outer-цепочки aiogram: `Dispatcher.__init__`
  (`aiogram/dispatcher/dispatcher.py:80-96`) — `ErrorsMiddleware` / `UserContextMiddleware` /
  `FSMContextMiddleware` регистрируются ДО kit-овых.
- Механику `dp.errors` vs outer-middleware: `aiogram/dispatcher/middlewares/error.py`,
  `aiogram/dispatcher/middlewares/manager.py:56-68` (`wrap_middlewares`/`reversed`),
  `aiogram/dispatcher/event/telegram.py:96-130`.
- Где aiogram_dialog бросает `UnknownIntent/OutdatedIntent/UnknownState` и как регистрирует
  свои middleware (`aiogram_dialog/setup.py:103-170`, `context/intent_middleware.py`).
- Фоновый путь dialog-апдейтов (`aiogram_dialog/manager/updater.py`,
  `api/entities/update_event.py`) — `DialogUpdate(update_id=0, event_type="aiogd_update")`.
- Где встаёт dishka-`ContainerMiddleware` (`dishka/integrations/aiogram.py:98-107`,
  вызывается в `tgbotkit/runner/base.py:57`).
- `errorux.py`, `metrics.py`, `telemetry/decorator.py` (span), тесты
  `tests/tgbotkit/test_middleware.py` + `conftest.py` (FakeRedis).
- **Эмпирическая проверка**: воспроизвёл порядок цепочки на живом `Dispatcher` (см. находку 1).
- `ruff check` и `mypy` по области — **чисто** (`All checks passed`, `Success: no issues`).

## Реальный порядок outer-цепочки на `dp.update` (снаружи → внутрь)

1. `ErrorsMiddleware` (диспетчит в `dp.errors`) — хардкод, `dispatcher.py:80`, **самый внешний**
2. `UserContextMiddleware` (ставит `event_from_user`/`event_chat`) — `dispatcher.py:84`
3. `FSMContextMiddleware` — `dispatcher.py:96`
4. `RequestIdMiddleware` — `middleware/__init__.py:40`
5. `DedupMiddleware` (опц.) — `:42`
6. `ThrottleMiddleware` (опц.) — `:44`
7. `RecoveryMiddleware` — `:45`
8. `ObservabilityMiddleware` — `:46`
9. `ContainerMiddleware` (dishka, Scope.REQUEST) — навешивается позже в `runner/base.py:57`, **самый внутренний** из outer
10. → inner-middleware фич + хендлер

Ключевой факт: `RecoveryMiddleware` сидит **внутри** `ErrorsMiddleware`. Это и есть источник
главной находки.

## Сильные стороны

- **Единая точка пропагации фона.** Фоновые dialog-апдейты (`BgManager`) идут через
  `Updater._process_update` → `dp.propagate_event(update_type="update", ...)`
  (`aiogram_dialog/manager/updater.py:30-40`), а это резолвит observer `dp.update` и крутит ту же
  outer-цепочку (`router.py:152-166`). Заявление в `__init__.py:1-3` («обычные И фоновые идут через
  один `propagate_event("update")`») — **верно**. Дедуп/observability/request_id честно покрывают и
  фон. (SEV=info)
- **Dedup корректен и атомарен.** `SET NX EX` одной командой (`dedup.py:34`) — без гонки
  check-then-set; ключ скоупится `bot_id` (`dedup.py:33`); фон (`update_id=0`) осознанно не
  дедупится (`:30`). At-least-once Telegram закрыт правильно. TTL форсится `>= 1`
  (`dedup.py:25`). (SEV=info)
- **request_id-проброс верный и async-safe.** `contextvar.set`→`reset(token)` строго
  симметрично в `try/finally` (`request_id.py:35-39`), structlog-`bind`/`unbind` тоже. Token
  внутри одной таски корректен; для фона дополнительно изолируется в `Delivery`
  (`notifications/delivery.py:36-44`/`47-53`). Синтетический `tg-bg-<id(event)>` для фона
  (`request_id.py:24`) — разумно. (SEV=info)
- **Observability — span корректен.** `span("tg.update")` через
  `telemetry/decorator.py:12-22` ловит исключение, делает `record_exception` + `set_status(ERROR)`;
  middleware помечает `result=error` и **пробрасывает** (`observability.py:34-36`), RED-метрики
  пишутся в `finally` (`:37-40`) — считаются даже при исключении. Длительность через
  `perf_counter`. (SEV=info)
- **Recovery как «последний рубеж» от паники.** Сама идея — ловить непредусмотренное, мерить
  `tg_update_panics_total`, не валить воркер на одном битом апдейте, показать нейтральный UX —
  правильная и реализована аккуратно (лог `repr(exc)`, best-effort UX в своём `try/except`,
  `recovery.py:37-40`). (SEV=info)
- **Тонкость соблюдена.** Это чистая инфра-механика в ките, в шаблоне её нет — by design. Чисто
  по `ruff`/`mypy`. (SEV=info)

## Находки

### 1. [critical / CONF=high] RecoveryMiddleware перехватывает `UnknownIntent/OutdatedIntent/UnknownState` РАНЬШЕ `dp.errors` → штатный dialog-recovery и tailored stale-UX мертвы

**Доказательство.** `ErrorsMiddleware` (он диспетчит `dp.errors`) регистрируется самым внешним
outer-middleware прямо в конструкторе `Dispatcher` (`aiogram/dispatcher/dispatcher.py:80`).
`RecoveryMiddleware` навешивается позже (`middleware/__init__.py:45`), значит сидит **внутри**
`ErrorsMiddleware`. aiogram_dialog бросает `UnknownIntent/OutdatedIntent/UnknownState` в
per-event-type observer'ах (`router.callback_query.outer_middleware(process_callback_query)` и т.д.,
`aiogram_dialog/setup.py:139-146`), т.е. глубоко внутри цепочки. Исключение всплывает вверх и
**первым его ловит `RecoveryMiddleware`** (`recovery.py:31 except Exception`), глотает и возвращает
`None`. До `ErrorsMiddleware` исключение не доходит — `dp.errors` **не срабатывает**.

`UnknownIntent(DialogsError → RuntimeError → Exception)` — подтверждено по
`aiogram_dialog/api/exceptions.py`, т.е. `except Exception` его ловит.

Воспроизвёл эмпирически на живом `Dispatcher` (тот же порядок middleware, хендлер бросает
`UnknownIntent`):
```
enter:Recovery
enter:Observability
caught-by:Observability:UnknownIntent   # span помечает error, пробрасывает
RECOVERY-SWALLOWS:UnknownIntent          # Recovery глотает
# DP_ERRORS_FIRED — НЕ появилось ни разу
```

**Почему это серьёзно (две жертвы, не одна):**
1. **Kit-овый `register_error_handlers` → `on_stale` → `on_unknown_intent/state`**
   (`errorux.py:54-67`) — **мёртвый код** для нормальных апдейтов. Tailored UX «Session expired,
   send /start» (`errorux.py:34-38`) никогда не показывается; пользователь всегда получает общий
   `on_unhandled` («Something went wrong»). Это прямо противоречит docstring'ам
   `recovery.py:1-5` («UnknownIntent/State обрабатываются там и сюда не доходят») и
   `errorux.py:55-58` («Прочие … пусть всплывают в recovery … чтобы observability успела пометить
   result=error»). Дизайн-намерение и фактическое поведение разошлись.
2. **Штатный recovery самого aiogram_dialog тоже не отрабатывает.** `IntentErrorMiddleware`
   зарегистрирован на `dp.errors` (`aiogram_dialog/setup.py:125-129`) и на
   `UnknownIntent/OutdatedIntent/UnknownState` **чинит сломанный стек**: `_fix_broken_stack` сносит
   битые контексты (`context/intent_middleware.py:479-497`, `534`). Раз `dp.errors` не
   срабатывает — стек НЕ чинится. После протухшей кнопки у пользователя остаётся corrupted
   dialog-стек, и он может ловить ошибку повторно, пока `/start` (RESET_STACK) не пересоберёт стек
   руками. Это функциональная регрессия, не только косметика текста.

**Fix.** RecoveryMiddleware должен пропускать «ожидаемые» dialog-исключения наверх, к `dp.errors`,
а глотать только всё остальное:
```python
from aiogram_dialog.api.exceptions import OutdatedIntent, UnknownIntent, UnknownState
_DIALOG_EXPECTED = (UnknownIntent, OutdatedIntent, UnknownState)
...
except _DIALOG_EXPECTED:
    raise            # пусть ErrorsMiddleware → dp.errors разрулит (kit on_stale + dialog stack-fix)
except Exception as exc:
    ...              # как сейчас
```
Альтернатива (хуже): зарегистрировать stale-обработку прямо в Recovery — но тогда дублируется
логика aiogram_dialog (stack-fix), это велосипед. Чистый путь — пропустить наверх.

### 2. [medium / CONF=high] ThrottleMiddleware режет фоновые dialog-апдейты (notifications) и не скоупится по `bot_id`

**Доказательство.** Throttle ключ — `tg:throttle:{user.id}` (`throttle.py:26`), берёт
`event_from_user` из `data`. Для фонового пути `Updater._process_update` сам кладёт
`event_from_user=event.from_user` в kwargs (`aiogram_dialog/manager/updater.py:37`), а
`UserContextMiddleware` его не перетирает (для `DialogUpdate` `resolve_event_context` пуст,
ставит ключ только если `is not None`). Значит при `throttle_rps>0` всплеск нотификаций одному
юзеру (NATS at-least-once + несколько событий подряд) попадает в тот же per-user bucket и часть
доставок **тихо дропается** (`throttle.py:30-31 return None`) — без лога, без метрики. Это ложное
срабатывание троттла на системном фоне, который пользователь не «спамил».

Вторично: dedup-ключ скоупится `bot_id` (`dedup.py:33`), а throttle-ключ — **нет**
(`throttle.py:26`). Если в одном процессе/redis крутятся несколько ботов (мультибот), юзеры
разных ботов с одинаковым `user.id` делят bucket — cross-throttle.

**Fix.** (а) В throttle игнорировать фон: `if update_id` или проверять `event_type !=
"aiogd_update"` перед инкрементом; (б) скоупить ключ `bot_id` симметрично dedup:
`tg:throttle:{bot_id}:{user.id}`. По дефолту `throttle_rps=0` (off), поэтому SEV=medium, не high.

### 3. [low / CONF=high] ThrottleMiddleware: INCR без гарантии EXPIRE → возможен «вечный» бан окна и неатомарность

**Доказательство.** `count = INCR(key)`; `if count == 1: EXPIRE(key, 1)` (`throttle.py:27-29`).
Две проблемы:
- Между `INCR` и `EXPIRE` нет атомарности. Если процесс падает/отменяется (`CancelledError`
  на shutdown-drain) ровно после первого `INCR` и до `EXPIRE`, ключ остаётся **без TTL** — юзер
  залочен в этом «окне» навсегда (до ручной чистки redis). Маловероятно, но это не self-healing.
- При гонке двух воркеров на «первом» апдейте: оба могут увидеть `count==1`? Нет — `INCR`
  атомарен, ровно один получит 1. Но окно считается от первого `INCR`, а не «скользит» — это
  fixed-window, на границе окна допускает до `2*rps` за ~1с. Для дешёвой анти-флуд-защиты
  приемлемо, но стоит знать.

**Fix.** Делать атомарно — Lua-скрипт (`INCR` + `EXPIRE` на первом инкременте) или
`SET key 1 EX 1 NX` + `INCRBY`/pipeline с `EXPIRE NX`. Минимально: `pipeline().incr(key).expire(key,
1, nx=True)` — `EXPIRE … NX` есть в redis ≥7, ставит TTL даже когда инкрементил не «первый».

### 4. [low / CONF=medium] DedupMiddleware: при отсутствии `bot` ключ схлопывается в `bot_id=0` (кросс-бот коллизия дедупа)

**Доказательство.** `bot = data.get("bot"); bot_id = getattr(bot, "id", 0)` (`dedup.py:31-32`).
В штатном пути `bot` всегда в workflow_data, так что практически безопасно. Но фолбэк на `0`
молчаливый: если когда-нибудь `bot` не прокинется (нестандартный фид), два разных бота с
совпавшим `update_id` дедупнут друг друга (`tg:dedup:0:{id}`). Лучше падать/логировать, чем
тихо коллизить. SEV=low т.к. в текущей проводке `bot` гарантирован.

**Fix.** `bot_id = bot.id` без `getattr`-фолбэка (пусть упадёт на None — это баг проводки, не
норма), либо явный лог при `bot is None`.

### 5. [info / CONF=medium] Recovery вызывает `on_unhandled` только для `isinstance(event, Update)` — фоновые dialog-события UX не получают (это ок, но молча)

**Доказательство.** `if isinstance(event, Update) and bot is not None` (`recovery.py:36`).
`DialogUpdate` — подкласс `Update` (`api/entities/update_event.py:62`), так что фон **проходит**
условие. Но `ErrorEvent(update=event)` с `DialogUpdate` внутри → `event.update.callback_query`
будет `None` (у фонового апдейта нет `message`/`callback_query`), и `DefaultErrorUX.on_unhandled`
тихо ничего не делает (`errorux.py:40-47`). Для фона это by design (некому отвечать), но паника в
фоновом dialog-апдейте схлопывается в «метрика + лог», без пользовательского сигнала. Приемлемо;
фиксирую как факт, не дефект. `panics_total` при этом считается с `type="aiogd_update"` — фон
наблюдаем.

### 6. [info / CONF=high] Лейблы span и метрик рассинхронизированы по ключу

**Доказательство.** span атрибут — `tg.update_type` (`observability.py:32`), метрики — лейбл
`type` (`:38`). Не баг, но при корреляции trace↔metric ключи разные. Косметика.

## Ответ на вопросы заказчика (в этой области)

**1. Можно ли строить нормальных ботов?** Да — механика middleware по сути правильная: дедуп
атомарен и закрывает Telegram at-least-once, request_id честно прокидывается в исходящие вызовы и
логи, observability считает RED-метрики и пишет span с exception'ом, фон идёт через ту же цепочку.
Это грамотная инфра. **Но** находка 1 — реальный дефект: из-за порядка `Recovery` внутри
`ErrorsMiddleware` штатное восстановление сломанного dialog-стека (aiogram_dialog) и tailored
«session expired»-UX **не работают**; протухшие inline-кнопки чинятся только ручным `/start`.
Лечится одной правкой в ките (пропустить dialog-исключения наверх). До этого — UX/recovery на
устаревших кнопках деградирован.

**2. Гибкость.** Цепочка собирается флагами конфига (`dedup_enabled`, `throttle_rps>0`) и UX
override'ится своим `ErrorUX`-Provider'ом без касания регистрации — это гибко и в духе «точек
расширения». Минус гибкости: набор и **порядок** middleware зашиты в `install_standard_middleware`
без хука вставить своё между ними; но для тонкого шаблона это осознанный trade-off (новая
middleware = PR в kit), не претензия.

**3. Несколько backend-клиентов** — вне моей области (это `platform/BackendClient`); по
middleware-слою замечу только, что request_id-contextvar один (`httpclient.request_id`), и при
нескольких httpclient'ах все они подхватят один и тот же `tg-<update_id>` — это как раз желаемо
(сквозной trace), не ограничение.

---

Итог по области: механика на 90% правильная и аккуратная, но порядок `Recovery`↔`dp.errors`
(находка 1) ломает заявленный в docstring'ах контракт error-handling и штатный stack-recovery
aiogram_dialog. Это чинибельно точечно в ките.
