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

- Период (фикс interval / cron-выражение)? Что джоба делает?
- Идемпотентна ли (запуск может пересечься/повториться при рестарте)?
- Шлёт ли что-то пользователю в Telegram (тогда — фоновая доставка, см. §4)?
- Где живёт логика — у существующей фичи (её usecase) или нужна новая?

## 2. Логика — в usecase (не в самой джобе)

Джоба — тонкий триггер; работа — в usecase фичи (тестируется без таймера):

```python
# features/cleanup/usecase.py
class CleanupUsecase:
    def __init__(self, store: DraftStore, log: Logger) -> None:
        self._store, self._log = store, log
    async def purge_expired(self) -> int:
        n = await self._store.delete_expired()
        self._log.info("cleanup.purged", count=n)
        return n
```

## 3. Объявить джобу (timerkit) + точка расширения

`timerkit` собирает периодические задачи через тип-обёртку (идиома `list[PeriodicJob]`, как `RouterBundle`/`CommandBundle`). Шаблон **декларирует** джобу и регистрирует в точке расширения; рантайм планировщика — в kit'е.

`PeriodicJob` — `dataclass(name, interval, handler)`; `handler` это `Callable[[], Awaitable[None]]` (Runner зовёт `handler()` **без аргументов**), поэтому зависимости захватываются замыканием через фабрику, а не инъекцией в сигнатуру.

```python
# features/cleanup/jobs.py
from pylibinfra.timerkit import PeriodicJob
from bot.features.cleanup.usecase import CleanupUsecase

def build_cleanup_job(uc: CleanupUsecase) -> PeriodicJob:
    async def _run() -> None:                  # uc захвачен замыканием
        await uc.purge_expired()
    return PeriodicJob(name="cleanup-drafts", interval=300.0, handler=_run)
```

> `timerkit` — опциональный kit (`docs/stack/dependencies.md`). Если в проекте джоб ещё не было — точка расширения (`list[PeriodicJob]`) могла не существовать в `app.py`: её добавление в kit-интеграцию — `infra-handoff` (`runtime-dep`).

## 4. Если джоба шлёт в Telegram — фоновая доставка

Фоновая отправка идёт **не через апдейт**, а через `BgManager`/`Delivery` (как notifications). Грабли request_id/пустой стек/throttle закрыты в `Delivery` (kit); **локаль фон не резолвит сам** — бери её через `LocalePrefStore.get(user_id)` и рендери ключ через `Delivery.localize(locale, key, args)`. Не дёргай `bot.send_message` напрямую из джобы без обёртки — потеряешь корреляцию и наткнёшься на throttle. Переиспользуй паттерн `features/notifications/deliver.py`, резолвя `chat_id` по `platform/links.py` (`chat_link_key`).

## 5. Регистрация

- экспортируй `build_cleanup_job` из фасада фичи;
- собери `list[PeriodicJob]` в `ExtensionProvider` (`app.py`; резолвит `CleanupUsecase` → `build_cleanup_job(uc)`), по образцу метода `notifiers` (`NotifierBundle`);
- провайдер фичи (`CleanupProvider`) — в `build_container()` (`make_async_container(...)`).

## 6. Тесты + верификация

- usecase-тест: `purge_expired()` на фейк-store удаляет просроченное, возвращает count (без таймера).
- идемпотентность: повторный вызов на пустом наборе → 0, не падает.
- джоба-обёртка тривиальна — отдельный тест не обязателен.
- `make check`.

`feat(cleanup): add periodic draft purge job`

## Anti-patterns

- ❌ Бизнес-логика в самой джобе вместо usecase — нетестируемо без таймера.
- ❌ `bot.send_message` напрямую из джобы — фон вне middleware; шли через `Delivery` (как notifications).
- ❌ Неидемпотентная джоба, которая дублирует эффект при рестарте/наложении запусков.
- ❌ Подключить `timerkit`, не отразив новую runtime-зависимость в `**Infra impact.**` (`infra-handoff`).
- ❌ Тяжёлая блокирующая работа в джобе, конкурирующая с обработкой апдейтов (один процесс).
