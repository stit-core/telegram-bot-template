---
id: stack.auth
kind: auth
name: auth
status: draft
---

# Auth — identity и роли

## Identity
<`BotIdentity` (REQUEST-scope): `tg_id` (из Telegram), `backend_user_id` (связанный аккаунт на
бэкенде — identity-link), `role`. Как резолвится из Update (`IdentityProvider`).>

## Roles & access
<Роли (`user` / `admin` / `banned`) и что они открывают/закрывают. Admin-allowlist — `APP_ADMIN_IDS`
(csv tg_id → роль admin). Бизнес-доступ решает `policy` фичи (PURE), не presentation.>

## Identity-link
<Как tg-пользователь связывается с аккаунтом бэкенда (если есть): когда и где проставляется
`backend_user_id`, что при отсутствии связки.>

## Generates
<Что de-template родит:
- `platform/identity/` (`BotIdentity` + `IdentityProvider`) — wiring
- `AppConfig.admin_ids` + `admin_id_set()` в `config.py`
- env: `APP_ADMIN_IDS`>
