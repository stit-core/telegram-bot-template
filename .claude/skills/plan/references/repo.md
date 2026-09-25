# Профиль репо для /plan — telegram-bot-template

- **Роль:** сервис — Telegram-бот (`<org>/<bot>`, образ `<org>/bot`). Работа приходит фазой программы
  из хаба `<org>/infra` (`parent: infra:<slug>`) или прямым заходом. Итог — образ в registry
  (`/release`); выкатка тега — только из хаба (`make bump SVC=bot`).
- **Гейт перед «готово»:** `make check`.
- **Проверка планов:** `make plan-check` (её же вызывает `make doctor`).
- **Сводка планов:** `make status` → `== Plan ==`.
- **Типовые проверки шагов:** `uv run pytest tests/unit/test_<x>.py` → PASS · `make test` → PASS ·
  `make typecheck` → без ошибок · `make lint` → чисто · `make check` → зелёный.
- **Особые шаги:** изменение `StatesGroup`/`State` ведётся по skill `/state-migration` (deprecation
  вместо удаления: живые диалоги пользователей должны пережить деплой); новый флоу диалога с нуля —
  сначала `/dialog-deep-dive`, план строится поверх его артефакта; новая инфра-механика (middleware,
  runtime, helper кита) — не правка шаблона, а PR в `pylibinfra` (`tgbotkit`) через `/infra-handoff`.
- **Handoff:** в хаб `<org>/infra` — INFRA-HANDOFF (skill `/infra-handoff`, правило `infra-impact`):
  env и секреты, webhook или polling, NATS-subject, runtime-зависимости; мейнтейнеру `pylibinfra` —
  PR с механикой. Пишется в раздел `## Handoff` плана; `make release` собирает его из активных планов.
- **Разбор падений:** skill `/triage-failure` — сначала падающий тест.
- **До плана выясни:** банк вопросов по областям — `references/questions.md` (скоуп, диалог-флоу,
  эволюция состояний, порты бэкенда, cross-feature, платежи/WebApp/i18n, фон и события, тесты,
  выкатка, инфра-поверхность). Бери только вопросы, ответ на которые меняет план.
