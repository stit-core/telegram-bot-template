# Observability

Метрики/логи/трейсы апдейтов эмитит `tgbotkit` автоматически — шаблон лишь добавляет бизнес-сигналы.
Чтение прод-телеметрии — skill `/query-logs` (корп-Loki/Tempo). Terse-инвариант доступа к токенам —
rule `env-local`.

## Что эмитится автоматически

Middleware-цепочка и runner kit'а на каждый апдейт дают:

- **Трейс.** Корневой span — `tg.update`; сшит `X-Request-ID = tg-<update_id>` (тот же id в логах и
  в исходящих запросах к бэкендам через `pkg/http_client`). HTTP-вызовы клиента — дочерние span'ы.
- **Метрики апдейтов** (`tg_*`): счётчики/латентность обработки апдейтов, ошибки/паники
  (recovery-middleware), circuit-breaker pkg-клиента `http_client_breaker_*{name}` (label = имя
  бэкенда, дефолт `core`).
- **Логи** — структурные, **только** через `pylibinfra.logkit.Logger` (`print`/stdlib `logging`
  забанены ruff). На старте — `"starting" service=<bot> version=<v> commit=<sha>`.
- **Health** — httpkit `/health` (в polling биндится health-порт `HTTP_*`); infra проверяет
  `make ps` → `healthy`.

Resource-attrs (`service.name`/`service.version`/`deployment.environment.name`) выставляются из
образа (`VERSION`/`GIT_SHA` зашиты при `make release`); `tenant` ставит корп-edge (`tenant-auth`).

## Бизнес-сигналы (что добавляешь сам)

- **Бизнес-метрики** (`biz_tg_*`): осмысленные доменные события (успешная оплата, отправка
  уведомления) — эмить из usecase/handler через telemetry kit'а, не плодить свой клиент.
- **Бизнес-логи**: `log.info("profile.renamed", tg_id=…)` — структурные поля, не строковая
  интерполяция. Секреты/PII не логируем (redact-конфиг kit'а, `RedactConfig`).

## Чтение прод-логов/трейсов — `/query-logs`

Логи задеплоенного бота — через корп-Loki read API под bearer из `./.env.local`:

- `STIT_LOKI_ADDR` (адрес read API, обязателен) + `STIT_OBS_TOKEN` (bearer) — в `./.env.local`
  (gitignored). Источник токена — корп-Vault `kv/projects/<p>/<env>/otel`.
- Скилл сам `grep`-ает значение и не печатает его в чат (rule `env-local`: `cat`/`Read` ради токена
  — необратимая утечка в transcript, придётся ротировать).
- Трейсы по trace-id — Tempo (`tempo.${DOMAIN}`), span корня `tg.update`.

## Локально (e2e)

`make test-integration` поднимает стек (testcontainers redis/nats); otel-agent в e2e использует
`OTEL_TENANT` (= `service_namespace`, корп-инвариант). Дев-наблюдаемость — логи в stdout.
