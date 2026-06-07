---
id: stack.auth
kind: auth
name: auth
status: draft
---

# Auth — identity, admin, WebApp

Бот не держит пароли — пользователь уже аутентифицирован Telegram. «Auth» здесь = связать
Telegram-юзера с аккаунтом на бэкенде, определить роль, проверить WebApp-данные.

## Identity-link (tg ↔ backend)
<`BotIdentity` (REQUEST-scope, `platform/identity/`) резолвится из Update:
- `tg_id` — из `event_from_user` (middleware_data aiogram).
- `backend_user_id` — из `link:tg:<id>` в cachekit (пишется при линковке аккаунта); фолбэк до
  линковки — сам `tg_id`.
- `role` — из admin-allowlist (см. ниже).
Опиши, **когда и как** происходит линковка (онбординг/deep-link/WebApp) и кто пишет `link:tg:*`.>

## Admin allowlist
<`APP_ADMIN_IDS` (csv tg_id) → роль `admin` в identity (`AppConfig.admin_id_set()`). Используется
в `policy` фич (доступ к админ-действиям). Опиши список ролей бота (`user`/`admin`/`banned`/…) и
кто их назначает.>

## WebApp initData
<Если есть Mini App: HMAC-валидация initData (`tgbotkit.validate_init_data`, секрет=`HMAC(key=
"WebAppData", data=bot_token)`, проверка хеша + `auth_date ≤ max_age`). Продуктовый парсинг
проверенного user — `platform/webapp/init_data.py: validate_webapp_user`. Канал доставки — путь B
(свой бэкенд-эндпоинт принимает initData, в webhook-режиме поверх httpkit). Опиши, что бот делает
с проверенными данными (identity-link, передача на бэкенд).>

## Anti-abuse
<throttle (`BOT_THROTTLE_RPS`, Redis-счётчик в kit-middleware), dedup апдейтов (`BOT_DEDUP_ENABLED`).
Бан — роль `banned` в identity → `policy` отказывает. Опиши пороги и как банится пользователь.>

## Generates
<Что de-template родит:
- `platform/identity/` (Update→BotIdentity) + `IdentityProvider` в `app.py`
- `APP_ADMIN_IDS` в `.env.example` + `AppConfig.admin_ids`
- (WebApp) `platform/webapp/` валидатор + identity-link
- `link:tg:*` key-builder в `platform/links.py`>
