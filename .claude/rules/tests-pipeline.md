---
name: tests-pipeline
description: Инварианты тестов, фейков, маркеров, TDD. Грузится при работе с tests/. Процедура скаффолда тестов — skill scaffold; разбор падений — skill triage-failure.
paths:
  - "tests/**"
---

# Тесты

Гейт — `make test` (`pytest -m "not integration and not e2e"`), входит в `make check`. Маркеры
объявлены в `pyproject.toml` (`--strict-markers` — незарегистрированный маркер = ошибка). Здесь —
инварианты; процедура (скаффолд теста при добавлении блока) — skill `scaffold`.

## Пирамида и раскладка

- `tests/unit/` (`@pytest.mark`? нет — маркер `unit`): чистое — `policy`/`views`/валидаторы.
- `tests/flows/` (маркер **`dialog`**): сценарии диалогов через `BotClient` +
  `MockMessageManager` + `JsonMemoryStorage` (`pylibinfra.testkit.bottest`), без реального
  Telegram. Сборка контейнера/dp — `tests/_fakes/harness.py` (`make_container`/`build_dp`).
- `tests/pkg/`: pkg-клиенты (`ProfileAPI`/`BookingAPI`/`PaymentsAPI`) через `respx`
  (мок httpx на транспорт-границе).
- маркер `integration` (Docker, testcontainers redis/nats) и `e2e` — **вне** `make check`,
  гоняет CI (`make test-integration`).

## Мокаем границу бэкенда, не транспорт

- Подменяй **фейк бэкенда** (`tests/_fakes/backend.py: FakeApiClient` — in-memory заглушка
  kit-`ApiClient`; `tests/_fakes/harness.py` отдаёт поверх него `ProfileAPI`/`BookingAPI`/
  `PaymentsAPI`), не `httpx`/`Bot`/`Dispatcher`. Исключение — `tests/pkg/` намеренно тестирует
  транспорт-границу через `respx`.
- Фон — фейк `Delivery` (`tests/_fakes/delivery.py`) + фейк `Cache`/`Redis`
  (`tests/_fakes/cache.py`/`redis.py`), не реальный NATS.
- `JsonMemoryStorage` сериализует тем же json-кодеком, что прод-Redis → ловит несериализуемое в
  `dialog_data` (rule `storage-serialization`). Не подменяй его in-memory dict'ом.

## Локаторы кнопок

- Кликай по `callback_data`/тексту: `InlineButtonTextLocator("<key-или-текст>")` из
  `aiogram_dialog.test_tools.keyboard`. i18n в тесте не установлен → `I18NFormat` рендерит **ключ**
  — локай по ключу (`"profile-edit-name"`), не по переводу.
- После клика — `mm.reset_history()` перед следующим шагом; ассерт окна — `mm.one_message()`.

## TDD для багфиксов — обязательно

RED→GREEN: падающий тест, воспроизводящий баг (падает **по причине бага**) → фикс → зелёный →
оба одним коммитом. Ведёт skill `triage-failure`.

## Anti-patterns

- ❌ Мокать `Bot`/`Dispatcher`/`httpx` вместо `FakeApiClient`/фейка (кроме `respx` в `tests/pkg/`).
- ❌ Незарегистрированный маркер (упадёт на `--strict-markers`) или тест без маркера слоя.
- ❌ Подменять `JsonMemoryStorage` — потеряешь проверку JSON-сериализуемости state.
- ❌ Локатор по переведённому тексту вместо i18n-ключа (i18n в тестах выключен).
- ❌ Закомментированный/`skip` без причины — удали или почини.
- ❌ Утечка контейнера: `make_container(...)` закрывай в `finally: await container.close()`.
