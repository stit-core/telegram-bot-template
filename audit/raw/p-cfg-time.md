# Аудит области p-cfg-time — config + flagkit + clockkit + timerkit

Область: четыре «кита» инфры в `pylibinfra/src/pylibinfra/`:

- `config/` (loader / vault / module) — композиция источников конфигурации (env + Vault KV v2).
- `flagkit/` — feature-флаги из ENV.
- `clockkit/` — порт времени (`Clock`) + production-реализация + тестовые фейки.
- `timerkit/` — периодические джобы поверх asyncio с lifecycle через dishka.

## Что смотрел

- Все исходники четырёх китов (loader.py, vault.py, module.py, flag.py, clock.py, fakes.py,
  timerkit.py, соответствующие `__init__.py`).
- Их тесты: `tests/config/test_config.py`, `tests/flagkit/test_flag.py`,
  `tests/clockkit/test_clock.py`, `tests/timerkit/test_runner.py`, `tests/timerkit/test_module.py`.
- Реальные потребители в `pylibinfra/src` и в шаблоне `telegram-bot-template/src/bot` (grep по
  всем именам экспортов), чтобы отделить «живой контракт» от «построено, но не подключено».
- Шаблонную обвязку конфига (`src/bot/config.py`, `src/bot/app.py`) и scaffold-доку джобы
  (`.claude/skills/scaffold/references/job.md`).
- Прогнал `ruff check` и `mypy` по всем четырём китам — **чисто** (0 замечаний). Проверил
  парсинг bool во flagkit на живом интерпретаторе.

Гейты сами по китам зелёные; находки — про дизайн/контракт/тестируемость/подключённость, не про
формальные нарушения линтеров.

## Сильные стороны

- **clockkit — образцовый testability-примитив.** Тонкий `Clock` Protocol (`runtime_checkable`),
  `Real` на `datetime.now(UTC)` (всегда tz-aware — `clock.py:18`), фейки `Fixed`/`Tickable` лежат
  рядом, а не в отдельном пакете (`fakes.py`). И это **реально используется**: `bruteforcekit.Guard`
  принимает `Clock` и считает истечение lockout через него (`bruteforcekit/guard.py:32`,
  `bruteforcekit/module.py:16`). Тест покрывает оба фейка и tz-aware-инвариант
  (`tests/clockkit/test_clock.py`). Это правильный паттерн «время — зависимость, а не вызов».
- **timerkit — корректный supervisor джоб.** `_loop` ловит `Exception`, но **пробрасывает**
  `asyncio.CancelledError` (`timerkit.py:41-44`) — одна падающая джоба не валит процесс и не глотает
  отмену. `stop()` дожидается `gather(..., return_exceptions=True)` (`timerkit.py:34`) — нет
  «task was destroyed but it is pending». Lifecycle через async-generator-провайдер
  (`module.py:16-20`) — `container.close()` детерминированно гасит задачи. Тесты покрывают все три
  инварианта: продолжение тиков, изоляция падающей джобы, идемпотентность `stop()`
  (`tests/timerkit/test_runner.py`). Логи — через `logkit.Logger`, не `print` (соблюдён banned-api).
- **config — чистая композиция с приоритетом «env-base → source-override».** `load()` накладывает
  Source'ы как init-kwargs, которые в pydantic-settings приоритетнее env (`loader.py:18-25`) — это
  совпадает с заявленной семантикой golibinfra (env-defaults → vault-override). Ошибка любого
  источника оборачивается с индексом (`loader.py:23-24`), тест на это есть. `VaultSource` корректно
  работает в no-op-режиме при `client is None` (`vault.py:48-50`) — Vault опционален и не ломает
  локальный запуск. `read_secret_version(..., raise_on_deleted_version=True)` — fail-loud на
  удалённой версии секрета (`vault.py:54`).
- **Единый dishka-паттерн «asymmetry».** Все четыре кита (как pgkit/cachekit/logkit) НЕ provide'ят
  свой `Config` — его регистрирует caller, чтобы не навязывать источник; дают `new_config()`-фолбэк.
  Паттерн консистентен по всей библиотеке (комментарии перекрёстно ссылаются друг на друга). Это
  осознанное, единообразное решение, а не разнобой.
- **mypy strict + ruff чисто**, типизация полная (generic `load[T: BaseModel]`, Protocol-порты
  `Clock`/`Store`/`Source` проверяются структурно).

## Находки

### [medium] `pylibinfra.config` (loader+vault+module) — построено, но НИ ОДНОГО потребителя

`config/` экспортирует `load`, `Source`, `VaultSource`, `VaultClientConfig`, `ConfigProvider`,
`new_vault_client*` — но в `pylibinfra/src` и в шаблоне **нет ни одного импорта** этого пакета
(grep по всем именам: совпадения только внутри самого `config/` и в тестах). Все `from .config
import Config` в других китах ссылаются на **их собственный локальный** `config.py`, а не на этот
пакет (проверено: `logkit/config.py`, `natskit/config.py`, …). Шаблонный `AppConfigProvider`
читает все `*Config` напрямую через `BaseSettings()` из env, а секреты, по docstring,
«на проде подаёт vault-agent в env» (`src/bot/config.py:6`) — то есть Vault-композиция обходится
side-car'ом и `VaultSource`/`load()` не задействованы вообще.

Доказательство: `config/__init__.py:1-15` (экспорты) vs пустой результат grep потребителей
(только `src/pylibinfra/config/*`).

Почему важно: это не баг, а **forward-provision** (механизм есть на случай прямого чтения Vault из
процесса). Но как «живой контракт» он непроверен сценарием end-to-end: `load()` ни разу не
прогоняется с реальным `model_cls(**overrides)`, где override — секрет. Для заказчика это значит:
если он захочет читать секреты из Vault **из процесса бота** (не через vault-agent), он наступит на
непротоптанную тропу. Сам код выглядит корректно, но «работает» здесь = «проходит юнит-тесты на
фейках», а не «используется в проде».
Confidence: high (факт неподключённости), medium (оценка риска).
Fix: либо подключить `VaultSource` в шаблонный `AppConfigProvider` хотя бы для одного секрета как
reference-пример (и закрыть e2e-тестом `load(model, VaultSource(...))` с валидацией pydantic), либо
явно задокументировать в `docs/stack/config.md`, что прямое чтение Vault — нетронутый опциональный
путь и канон — vault-agent→env.

### [medium] Секрет может утечь в текст исключения при ошибке валидации pydantic / Source

`load()` делает `model_cls(**overrides)` (`loader.py:25`), где `overrides` содержит значения
секретов из Vault. Если секрет не проходит валидацию (например, поле ждёт `int`, а секрет — строка,
или кастомный validator падает), `pydantic.ValidationError` по умолчанию **включает само значение в
текст ошибки** (`input_value`). Эта ошибка ничем не оборачивается и поднимется наверх — в трейсбек,
а трейсбек на старте бота обычно летит в логи/stderr. Аналогично ошибка `Source.apply` оборачивается
как `RuntimeError(f"config: source[{i}]: {exc}")` (`loader.py:23-24`): если hvac в `exc` положит
тело ответа с секретом — оно попадёт в сообщение. logkit-redact включается только если значение
прошло через структурный лог-вызов; голый трейсбек на старте его не проходит.

Доказательство: `loader.py:23-25`; pydantic v2 (`>=2.13`) по умолчанию печатает `input_value` в
`ValidationError`.

Почему важно: ровно в config-слое, который держит секреты, нет ни `SecretStr`-обёрток, ни
скрытия значений в ошибках. Контракт «секреты не текут в логи/repr» здесь не гарантирован — он
держится только на дисциплине «не логировать конфиг целиком» и на vault-agent (который выводит
config из этого пути). В самих kit-Config'ах (`VaultClientConfig.token`, `flagkit.Config`) поля —
обычный `str`, не `SecretStr`, поэтому их `repr()`/`model_dump()` покажут значение открытым текстом.
Confidence: medium (зависит от того, логируется ли когда-нибудь конфиг/трейсбек старта целиком).
Fix: (1) для секретных полей использовать `pydantic.SecretStr` (`token: SecretStr`) — даёт
`repr`-маскирование «из коробки»; (2) в `load()` ловить `ValidationError` и переподнимать без
`input_value` (или с именами полей, но без значений); (3) при оборачивании Source-ошибки не
интерполировать `exc` целиком, а только тип/безопасное сообщение.

### [low] `VaultSource` жёстко привязан к KV v2; парсинг path без валидации

`apply()` всегда зовёт `secrets.kv.v2.read_secret_version` (`vault.py:51`) — KV v1 и иные движки не
поддержаны (расширяемость via наследование, но из коробки только v2). Path парсится как
`mount, _, key = path.partition("/")` (`vault.py:43`): если в path нет `/` (например `"myapp"`),
получится `mount="myapp", key=""` — запрос уйдёт с пустым `path` и упадёт уже в hvac, без понятной
ошибки уровня kit. Вложенные пути (`secret/app/sub`) дадут `key="app/sub"` — это валидно для KV, но
поведение нигде не зафиксировано тестом.

Доказательство: `vault.py:43`, `vault.py:51`.
Почему важно: расширяемость на другие движки секретов потребует копипасты класса. Молчаливая порча
при path без `/` — мелкая, но недружелюбная ошибка конфигурации.
Confidence: high.
Fix: валидировать, что `key` непуст (явный `ValueError` с понятным текстом); вынести `kv.v2` за
точку расширения или хотя бы задокументировать ограничение «только KV v2».

### [low] timerkit: fixed-delay вместо fixed-rate, нет jitter, нет валидации интервала

`_loop` делает `await handler()` затем `await asyncio.sleep(interval)` (`timerkit.py:38-45`):

- Это **fixed-delay** (пауза между концом обработчика и началом следующего), а не fixed-rate. Если
  handler идёт долго, реальный период «плывёт». Для «каждые N минут почистить» это ок, но если
  заказчик ждёт точного расписания (cron-семантику) — её здесь нет, и это не задокументировано.
- **Первый запуск — немедленный** (тик до первого sleep). На старте все джобы стартуют разом; при
  ≥2 инстансов бота — синхронный залп по бэкенду (thundering herd), **jitter отсутствует**.
- `interval` — голый `float` без валидации (`timerkit.py:16`): `0` даст busy-loop (sleep(0) уступает
  цикл, но крутит handler без передышки), отрицательный — тоже sleep(0). Нет защиты.

Доказательство: `timerkit.py:14-17` (dataclass), `timerkit.py:37-45` (`_loop`).
Почему важно: для шаблона как «фундамент нормальных ботов» периодические задачи — ходовой кейс
(reminders, cleanup, reconciliation). Текущая модель покрывает простое, но молчит про fixed-delay,
немедленный первый тик и отсутствие jitter — это сюрпризы при масштабировании.
Confidence: high (поведение), medium (значимость зависит от нагрузки).
Fix: задокументировать семантику (fixed-delay + immediate-first) в docstring; опционально добавить
поля `jitter`/`run_immediately`/валидацию `interval > 0`. Для cron-расписания — отдельный примитив
(или явно «не наша зона, бери внешний шедулер»).

### [low] timerkit не тестируемо по времени (минует свой же clockkit)

`Runner._loop` спит реальным `asyncio.sleep` (`timerkit.py:45`) — нет инъекции `Clock`/sleeper.
Поэтому тесты вынуждены гонять реальное время (`await asyncio.sleep(0.1); assert count >= 3` в
`tests/timerkit/test_runner.py:18-19`) — это **wall-clock-зависимые, флака-склонные** тесты с
магическими порогами. При этом в той же библиотеке есть `clockkit` именно для устранения такой
зависимости, но timerkit им не пользуется.

Доказательство: `timerkit.py:45`; `tests/timerkit/test_runner.py:18,47`.
Почему важно: иронично, что kit про «джобы по времени» сам не сделан тестируемым по времени, хотя в
этой же области есть готовый `Clock`. Расширяемость на «детерминированный прогон джобы в тесте»
сейчас закрыта.
Confidence: high.
Fix: принимать sleeper/`Clock` как зависимость `Runner` (дефолт — `asyncio.sleep`), в тестах
подменять управляемым; убрать wall-clock-пороги.

### [low] flagkit: узкий bool-контракт молча роняет `yes`/`on`/`2` в False

`EnvStore.bool` считает истиной только `"true"` (case-insensitive) или `"1"` (`flag.py:37-41`).
Проверено вживую: `yes→False`, `on→False`, `2→False`, при этом `TRUE→True`, `True→True`, `1→True`.

Доказательство: `flag.py:40-41`; прогон `FEATURE_FLAGS='B=yes,D=on,E=2'` → все `False`.
Почему важно: распространённые «человеческие» написания (`yes`/`on`/`enabled`) молча трактуются как
выключено — оператор включит флаг, а он не сработает, без предупреждения. Для kill-switch'а на
рестарт это тихий футган.
Confidence: high.
Fix: расширить truthy-набор (`yes/on/enabled/y`) ИЛИ задокументировать узость прямо в docstring
рядом с примером (сейчас пример `foo=true` это лишь подсказывает). Невалидное значение можно
логировать на старте.

### [low] DX-дрейф: scaffold-док джобы показывает неверный API `PeriodicJob`

`.claude/skills/scaffold/references/job.md:53` приводит
`PeriodicJob(_run_cleanup, interval_seconds=300)`. Реальный `PeriodicJob` —
`@dataclass(frozen=True)` с полями `(name: str, interval: float, handler)` в этом порядке
(`timerkit.py:13-17`): нет `interval_seconds`, `name` обязателен первым, `handler` — не первый
позиционный. Доковый пример не сработает as-is.

Доказательство: `timerkit.py:14-17` vs `references/job.md:53`.
Почему важно: это reference, по которому scaffold-скилл строит джобу; рассинхрон с фактическим API
ведёт к падению на первом же `make check`. В доке есть хедж «сверь с docs/stack/dependencies.md /
API timerkit», что смягчает, но не отменяет дрейф.
Confidence: high.
Fix: привести пример к реальной сигнатуре: `PeriodicJob(name="cleanup", interval=300.0,
handler=_run_cleanup)`.

### [info] flagkit построен, но в шаблоне/ките не подключён

Единственное упоминание `flagkit` вне самого пакета — комментарий-ссылка в `cachekit/module.py:13`.
Ни один провайдер не регистрирует `FlagkitProvider`, ни одна фича не читает `Store`. Это, как и
`config`-пакет, forward-provision (точка расширения «на будущее»). Само по себе не проблема, но в
сумме с config-находкой даёт паттерн: в этой области заметная доля кода — «построено впрок, не
обкатано сценарием».
Доказательство: grep `flagkit|FlagkitProvider|EnvStore` → только `cachekit/module.py:13`.
Confidence: high.

## Ответ на вопросы заказчика (в этой области)

**1. Получится ли строить нормальных ботов?** В части этой области — да, для типового кейса.
`clockkit` и `timerkit` — крепкие, реально используемые внутри библиотеки примитивы (Guard,
outbox partition-keeper), с правильной семантикой supervisor'а джоб и тестируемым временем. Простой
бот с парой периодических задач и kill-switch-флагами собирается. Оговорки: периодические джобы —
fixed-delay с немедленным первым тиком и без jitter (масштабирование на ≥2 инстанса даст залп);
сами джобы не тестируемы по времени (флака-тесты).

**2. Насколько гибкая система?** Конфиг-слой гибкий по дизайну: `Source`-Protocol + `load()`
позволяют наслаивать произвольные источники поверх env, приоритет предсказуем. Но гибкость
**неравномерно обкатана**: env-путь живой, Vault-путь (`VaultSource`/`load`) и `flagkit` —
построены, но без единого потребителя, то есть «гибкость на бумаге». `VaultSource` жёстко завязан
на KV v2 — другой движок секретов потребует нового класса. timerkit негибок к расписанию (только
интервал, не cron) и к jitter'у.

**3. Несколько клиентов к разным API.** Прямо моей области не касается (это httpclient/backend), но
ровно тот же структурный паттерн виден здесь и он **обнадёживает**: kit'ы намеренно НЕ provide'ят
свои `Config` (asymmetry), оставляя caller'у решать, сколько и каких инстансов регистрировать. То
есть инфраструктурно ничто не мешает поднять несколько `VaultSource`/несколько `Config` под разные
адресаты — единственность `BackendProvider` в шаблоне это **выбор шаблона**, а не ограничение kit'а.
Сигнал скорее «норм by design», а не «негибкость кита».

**Главное по безопасности секретов:** контракт «секреты не текут в логи/repr» в config-слое
**не гарантирован кодом** — поля секретов это обычный `str` (не `SecretStr`), а `load()` может
поднять `ValidationError`/обёрнутую Source-ошибку со значением секрета в тексте. Сейчас спасает то,
что прод-секреты идут через vault-agent→env и конфиг целиком не логируется, но это держится на
дисциплине, а не на типах. Это самая весомая находка области.
