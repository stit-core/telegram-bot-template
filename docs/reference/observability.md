# Observability

Наблюдаемость бота — **структурные JSON-логи в stdout** через `pylibinfra.logkit`; метрики/трейсы по
OTLP шаблон не экспортирует. Kit пишет технические логи апдейтов автоматически — шаблон добавляет
бизнес-логи. Логи собирает рантайм контейнера (`docker/compose logs`).

## Что даёт logkit автоматически

- **Структурные логи** — **только** через `pylibinfra.logkit.Logger` (`print`/stdlib `logging`
  забанены ruff), JSON в stdout (`LOG_LEVEL`/`LOG_STDOUT`). На старте —
  `"starting" service=<bot> version=<v> commit=<sha>` (`VERSION`/`GIT_SHA` зашиты при `make release`).
- **Trace-correlation** — сквозной `X-Request-ID = tg-<update_id>` middleware протягивает в поля
  логов и в исходящие запросы к бэкендам (`pkg/http_client`); по нему сшивается цепочка одного
  апдейта в логах.
- **PII-redact** — секреты/чувствительные поля вырезаются на выводе (`RedactConfig`).
- **Health** — httpkit `/health` (в polling биндится health-порт `HTTP_*`); инфра проверяет
  `make ps` → `healthy`.

## Бизнес-логи (что добавляешь сам)

`log.info("profile.renamed", tg_id=…)` — структурные поля, не строковая интерполяция. Осмысленные
доменные события (успешная оплата, отправка уведомления) эмить из usecase/handler. Секреты/PII не
логируем (redact-конфиг kit'а, `RedactConfig`).

## Чтение

Логи — в stdout, собираются рантаймом контейнера. Чтение/агрегация прод-логов (`make logs` и куда они
складываются) — забота деплой-репо `<org>/infra`, не этого репо.

## Локально (e2e)

`make test-integration` поднимает стек (testcontainers redis/nats). Дев-наблюдаемость — те же логи в
stdout.
