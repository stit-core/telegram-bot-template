# scaffold › job — периодическая джоба (timerkit)

Добавляет периодическую фоновую задачу (напоминание, cleanup, реконсиляция) через `timerkit` `pylibinfra`. Джоба крутится **в том же процессе бота** (отдельного worker-образа нет, как и migrate — см. skill `release`). Если джоба шлёт сообщение в Telegram — она фоновая и не проходит обычные middleware (rule `background-updates`).

> Аналог «часть event/job» у go-template. `timerkit` — опциональный kit; если в стеке его нет (`docs/stack/dependencies.md`), подключение джоб — изменение инфра-поверхности (`infra-handoff`: `runtime-dep`).

## Когда применять

- «Каждые N минут чистить просроченные черновики/локи».
- «Раз в день слать дайджест/напоминание».
- «Периодически сверять состояние с бэкендом».

## Когда НЕ применять

- Реакция на событие бэкенда (не по таймеру) → `references/notification.md` (NATS-подписчик).
- Side-effect в контексте апдейта (синхронно) → просто метод usecase.
- Одноразовое отложенное действие — это не периодическая джоба; рассмотри отдельный механизм.

## 1. Подтвердить вход

- Период (интервал в секундах)? Что джоба делает? Дедлайн одного запуска?
- Идемпотентна ли (запуск может повториться при рестарте; наложений kit не допускает — интервал отсчитывается от конца предыдущего запуска)?
- Шлёт ли что-то пользователю в Telegram (тогда — фоновая доставка, см. §4)?
- Где живёт логика — у существующей фичи (её usecase) или нужна новая?

## 2. Логика — в usecase (не в самой джобе)

Джоба — тонкий триггер; работа — в usecase фичи (тестируется без таймера). У периодики нет апдейта, поэтому usecase джобы собирается из **APP-scope** зависимостей (кэш, pkg-клиент, логгер), не из REQUEST (`BotIdentity`):

```python
# features/cleanup/usecase.py
class CleanupUsecase:
    def __init__(self, store: DraftStore, log: Logger) -> None:
        self._store, self._log = store, log

    async def purge_expired(self) -> None:
        n = await self._store.delete_expired()
        self._log.info("cleanup.purged", count=n)
```

## 3. Объявить джобу (timerkit) + точка расширения

`timerkit` собирает периодические задачи кортежем `timerkit.Jobs` (DI-ключ, как `RouterBundle`/`CommandBundle`); каждая — структура `Job(name, interval, run, timeout=, jitter=, run_on_start=)`. `run` — `Callable[[], Awaitable[None]]` **без аргументов**, поэтому зависимости захватываются bound-методом/замыканием, а не инъекцией в сигнатуру. Шаблон **декларирует** джобу; планировщик (`timerkit.Runner`: валидация набора на старте, интервал от конца предыдущего запуска, дедлайн `timeout`, ожидание идущих запусков на остановке, спан и метрики `timer_job_*`) — в kit'е.

```python
# features/cleanup/jobs.py
from pylibinfra.timerkit import Job

from bot.features.cleanup.usecase import CleanupUsecase


def cleanup_job(uc: CleanupUsecase) -> Job:
    return Job(
        name="cleanup-drafts",
        interval=300.0,  # секунды от КОНЦА предыдущего запуска
        timeout=60.0,  # дедлайн одного запуска; 0 — без дедлайна
        run=uc.purge_expired,  # без аргументов: uc захвачен bound-методом
    )
```

Исключение внутри `run` kit логирует (`timerkit: job error`) и не прерывает цикл; ретрай/backoff — внутри `run`, kit их не делает. Невалидная джоба (пустое имя, `interval <= 0`, дубль имени) — `JobError` на старте, бот не поднимается.

> `timerkit` — опциональный kit (`docs/stack/dependencies.md`). Если в проекте джоб ещё не было — `TimerkitProvider()` и `timerkit.Jobs` в `app.py` отсутствуют: их добавление — `infra-handoff` (`runtime-dep`).

## 4. Если джоба шлёт в Telegram — фоновая доставка

Фоновая отправка идёт **не через апдейт**, а через `BgManager`/`Delivery` (как notifications). Грабли request_id/пустой стек/throttle закрыты в `Delivery` (kit); **локаль фон не резолвит сам** — бери её через `LocalePrefStore.get(user_id)` и рендери ключ через `Delivery.localize(locale, key, args)`. Не дёргай `bot.send_message` напрямую из джобы без обёртки — потеряешь корреляцию и наткнёшься на throttle. Переиспользуй паттерн `features/notifications/deliver.py`, резолвя `chat_id` по `platform/links.py` (`chat_link_key`); если рассылка может повториться после рестарта — дедуп через `DeliveryDedup` (резерв с токеном → отправка → `commit`).

## 5. Регистрация

- экспортируй `cleanup_job` из фасада фичи; провайдер фичи (`CleanupProvider`, APP-scope зависимости) — в `build_container()` (`app.py`);
- `TimerkitProvider()` — в `build_container()` **до** `ExtensionProvider()`: его пустой дефолт `Jobs` перекрывает провайдер, зарегистрированный позже; `Clock` и `Logger` у него уже есть (`ClockProvider`/`LogkitProvider` в контейнере);
- собери `timerkit.Jobs` в `ExtensionProvider` (`app.py`) по образцу `notifiers`:
  `@provide def jobs(self, uc: CleanupUsecase) -> timerkit.Jobs: return (cleanup_job(uc),)`;
- **резолви `Runner` явно** в `app.run()` перед `runner.run()`: `await container.get(timerkit.Runner)` — dishka ленив, без запроса расписание не поднимется. Остановка (`Runner.stop`: ожидание идущих запусков в дедлайн) — на `container.close()`, который делает `BotRunner` на shutdown.

## 6. Тесты + верификация

- usecase-тест: `purge_expired()` на фейк-store удаляет просроченное, логирует count (без таймера).
- идемпотентность: повторный вызов на пустом наборе — no-op, не падает.
- расписание — только если джоба нетривиальна: `Runner((cleanup_job(uc),), nop(), clock=Tickable(...))` → `start()` → `await clock.wait_sleepers(1)` → `clock.advance(300)` → запуск прошёл (README timerkit § Тестирование); сама обёртка `Job` теста не требует.
- `make check`.

`feat(cleanup): add periodic draft purge job`

## Anti-patterns

- ❌ Бизнес-логика в самой джобе вместо usecase — нетестируемо без таймера.
- ❌ `bot.send_message` напрямую из джобы — фон вне middleware; шли через `Delivery` (как notifications).
- ❌ Неидемпотентная джоба, которая дублирует эффект при рестарте.
- ❌ REQUEST-scope зависимость (`BotIdentity`, per-update usecase) в джобе — у периодики нет апдейта.
- ❌ Подключить `timerkit`, не отразив новую runtime-зависимость в `**Infra impact.**` (`infra-handoff`).
- ❌ `TimerkitProvider()` после `ExtensionProvider()` — пустой дефолт `Jobs` победит, джобы молча не запустятся.
- ❌ Не резолвить `timerkit.Runner` в `app.run()` — расписание не поднимется.
- ❌ Тяжёлая блокирующая работа в джобе, конкурирующая с обработкой апдейтов (один процесс).
