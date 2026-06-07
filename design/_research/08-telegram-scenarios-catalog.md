# 08 — Исчерпывающий каталог продакшн-ситуаций Telegram-бота (зона H)

> Каталог ситуаций, которые обязан предусмотреть прод-Telegram-бот, и где каждая
> обрабатывается в архитектуре шаблона sftbmb (aiogram 3.28 + aiogram_dialog 2.6
> поверх pylibinfra). Архитектурный инвариант: бот = «фронтенд» к бэкендам, своё у
> бота — только state (Redis через cachekit). Бизнес-логика — по HTTP (httpclient)
> и из событий (natskit).
>
> Дата: 2026-06-07. Источники: артефакты волны 1 (04 core-киты, 05 integration-киты,
> 06 dishka×aiogram, 07 modern-stack), полный референс aiogram_dialog
> (`aiogram-dialog-docs/`, develop @ `08abdf0`), Telegram Bot API changelog
> (web-проверка, см. ниже).
>
> **Метки колонки «Покрыто»:** `да` — есть готовый механизм в шаблоне/ките;
> `частично` — механизм есть, но требует прикладной настройки/кода; `гайд` — не код
> шаблона, а пункт документации/чеклиста, разработчик делает сам.
>
> **Метки достоверности фич Telegram:** `[✓web]` — подтверждено веб-поиском
> 2025–2026; `[~]` — по знаниям/коду aiogram, **требует точечной проверки на пине**;
> остальное — из локального кода pylibinfra/aiogram_dialog (первоисточник).

---

## Легенда слоёв шаблона

| Слой | Что это | Где |
|---|---|---|
| **entrypoint** | bootstrap: `make_async_container`, `Bot`, `Dispatcher`, режим polling/webhook, graceful shutdown | `app/main.py` (скелет) |
| **outer-middleware** | aiogram outer-middleware на «сырой» апдейт (до фильтров): dedup, throttle, request-id/locale bind, recovery | `app/middlewares/*` |
| **inner-middleware** | aiogram inner-middleware (после фильтров): i18n, DI-обогащение | `app/middlewares/*` |
| **error-handlers** | `dp.errors` + aiogram_dialog `IntentErrorMiddleware` + retry-обёртка сессии | `app/errors/*` |
| **handlers/routers** | команды, обычные апдейты, не-диалоговые хендлеры | `app/handlers/*` |
| **dialogs** | aiogram_dialog: `Dialog`/`Window`/виджеты/getter/on_click | `app/dialogs/*` |
| **services** | бизнес-сервисы (DI), ходят в бэкенды через httpclient | `app/services/*` |
| **webhook-route** | FastAPI/aiohttp-роут приёма апдейтов (только webhook-режим) | `app/web/*` (httpkit) |
| **bg/notify** | natskit-подписки → `bot.send_message`/`BgManager` | `app/notify/*` |
| **киты pylibinfra** | httpclient, cachekit, natskit, storagekit, telemetry, logkit, timerkit, bizmetric, httpkit | транзитивно |

**Всего ситуаций в каталоге: 120+** (по 14 категориям).

---

## Категория 1. Типы апдейтов (Dispatcher routing)

| Ситуация | Тип апдейта/триггер | Где обрабатывается (слой/кит/виджет) | Подводный камень | Покрыто? |
|---|---|---|---|---|
| Текстовое сообщение / команда | `message` | handlers (`Command`-фильтр) или dialogs (`MessageInput`/`TextInput`) | `MessageInput` грузит контекст только из `DEFAULT_STACK_ID`; в неосновном стеке нужен reply (gotcha 7.1) | да |
| Отредактированное сообщение | `edited_message` | handlers (отдельный observer `dp.edited_message`) | aiogram_dialog **игнорирует** edited_message (нет в списке observers диалога); если игнорируешь — кнопки на старом сообщении живут | частично |
| Нажатие inline-кнопки | `callback_query` | dialogs (`on_click` виджета) / handlers (`CallbackQuery`-фильтр) | Обязателен `answerCallbackQuery` (часики) ≤ ~30с; aiogram_dialog гасит автоматически (`answer_callback`), вручную в диалоге не звать | да |
| Inline-режим (запрос в строке) | `inline_query` | handlers (`InlineQuery`-фильтр) | `answerInlineQuery` обязателен; результаты кешируются по `cache_time`; aiogram_dialog inline **не** обслуживает | гайд |
| Выбор inline-результата | `chosen_inline_result` | handlers | Приходит только если включён feedback в @BotFather; для аналитики/follow-up | гайд |
| Бот добавлен/удалён/повышен в чате | `my_chat_member` | handlers (`MyChatMemberUpdated`); **есть в observers диалога** | Источник правды о правах бота; реагировать на `kicked`/`left`/`administrator`; aiogram_dialog слушает это событие для своих нужд | частично |
| Изменение статуса участника | `chat_member` | handlers | Требует `allowed_updates` явно (не входит в дефолт!) + бот должен быть админом | гайд |
| Заявка на вступление | `chat_join_request` | handlers; **есть в observers диалога** | `approveChatJoinRequest`/`declineChatJoinRequest`; идемпотентность (повторная заявка) | частично |
| Опрос (poll) обновился | `poll` | handlers | Приходит только для опросов, созданных ботом; состояние опроса — на бэкенде | гайд |
| Ответ в опросе | `poll_answer` | handlers | `poll_answer.user` может быть `None` для анонимных; маппинг на backend-user | гайд |
| Пречек платежа | `pre_checkout_query` | handlers (`PreCheckoutQuery`-фильтр) | **Ответить `answerPreCheckoutQuery` ≤ 10с** иначе платёж отменяется `[✓web]`; см. категорию 7 | да (скелет-handler) |
| Запрос доставки | `shipping_query` | handlers | Только если `is_flexible=True` в инвойсе; для Stars/цифровых товаров **не приходит** | гайд |
| Business: подключение бота к аккаунту | `business_connection` | handlers `[✓web]` | Хранить `business_connection_id` → нужен для отправки от имени бизнеса; включить в `allowed_updates` | гайд |
| Business: новое/ред./удал. сообщение | `business_message`/`edited_business_message`/`deleted_business_message` | handlers `[✓web]` | Отдельные observers; FSM-ключ должен учитывать `with_business_connection_id=True` (см. 07 §3); delete_message в business недоступен (gotcha 5.6) | гайд |
| Реакция на сообщение (не аноним.) | `message_reaction` (`MessageReactionUpdated`) | handlers `[✓web]` | Требует явного `allowed_updates`; только non-anonymous; не приходит в каналах с аноним. реакциями | гайд |
| Счётчик аноним. реакций | `message_reaction_count` (`MessageReactionCountUpdated`) | handlers `[✓web]` | Агрегированный, с задержкой; для аналитики | гайд |
| Куплено paid media | `purchased_paid_media` (`PaidMediaPurchased`) `[~]` | handlers | Свежий тип; проверить наличие в пине aiogram 3.28; `paid_media` также в `TransactionPartnerUser` `[✓web]` | гайд |
| Удаление набора реакций / прочие | `chat_boost`, `removed_chat_boost` `[~]` | handlers | Редко; включать в `allowed_updates` точечно | гайд |
| Фоновый апдейт диалога | `aiogd_update` (внутренний) | dialogs (BgManager → `Updater.notify`) | **Не проходит обычные middleware!** auth/i18n/throttle вешать на `observers[DIALOG_EVENT_NAME]` (gotcha 11.4) | частично |

**Сквозной камень категории:** `allowed_updates` по умолчанию **не включает**
`chat_member`, `message_reaction`, `message_reaction_count`, business-апдейты. Шаблон
должен звать `dp.resolve_used_update_types()` (авто-вывод по зарегистрированным
хендлерам, совместим с aiogram_dialog) и при необходимости **дополнять список вручную**
для тех типов, что определяются не наличием хендлера, а намерением.

---

## Категория 2. Команды и deep-link `/start <payload>`

| Ситуация | Тип апдейта/триггер | Где обрабатывается | Подводный камень | Покрыто? |
|---|---|---|---|---|
| `/start` без payload | `message` + `CommandStart()` | handlers → `manager.start(MainSG.main, mode=StartMode.RESET_STACK)` | **Без `RESET_STACK` стек копится → `DialogStackOverflow` (лимит 100)** (gotcha 1.1/1.2); +`ShowMode.SEND` для свежего сообщения | да (скелет) |
| `/start <payload>` (deep-link) | `CommandStart(deep_link=True)` | handlers → разбор payload → start нужного диалога | Payload ≤ 64 символа, `A-Za-z0-9_-`; не доверять содержимому (валидировать) | частично |
| Deep-link с JWT связывания аккаунта | `/start <jwt>` | handlers → authnkit `JWTParser.parse` → cachekit `link:tg:<id>` | JWT_SECRET должен совпадать с бэкендом (HS256 only); ловить `ErrTokenExpired`/`TokenError` (05 §5) | частично |
| `/start` с одноразовым токеном (replay) | deep-link | services + cachekit (mark used) | Идемпотентность: токен пометить использованным в Redis (TTL), повтор → отказ | гайд |
| Прочие команды (`/help`, `/menu`, `/cancel`) | `Command(...)` | handlers / `Cancel`-кнопка в диалоге | `/cancel` на корневом диалоге: `done()` не зовёт `on_process_result` (gotcha 1.9) | частично |
| Команда внутри активного диалога | `message` в окне диалога | **порядок роутеров**: команд-роутер ДО dialog-роутера или фильтр в окне | Иначе команда «съестся» `MessageInput`-ом окна; катч-all input — последним (gotcha 7.4) | гайд |
| Меню команд (`setMyCommands`) | startup | entrypoint (startup hook) | Локализованные команды по `language_code` (scope); ставить на старте | гайд |
| Неизвестная команда / мусор | `message` (fallback) | handlers (fallback-router последним) | Fallback-хендлер ДОЛЖЕН быть, иначе «бот молчит»; не плодить лишние сообщения | гайд |

---

## Категория 3. Типы чатов и topics/threads

| Ситуация | Тип/триггер | Где обрабатывается | Подводный камень | Покрыто? |
|---|---|---|---|---|
| Приватный чат (1-на-1) | `chat.type == private` | dialogs/handlers | AUTO ShowMode: на сообщение → SEND, на кнопку → EDIT (gotcha 5.2) | да |
| Группа / супергруппа | `group`/`supergroup` | handlers; dialogs с оговорками | aiogram_dialog: дефолтный стек в группе становится **персональным** (`stack_id="<user_id>"`, архитектура §3); AUTO всегда EDIT в неприватном чате | частично |
| Канал (channel post) | `channel_post`/`edited_channel_post` | handlers (отдельные observers) | Нет `from_user`; диалоги в каналах неприменимы; reply-клавиатуры нет | гайд |
| Topic/thread в супергруппе | `message_thread_id` в message | handlers; отправка с `message_thread_id` | FSM/диалог-ключ **не** разделяет по thread по умолчанию (ключ по chat+user); ответы слать в тот же thread; aiogram_dialog хранит `thread_id` в EventContext, но один стек на (chat,user) | частично |
| General topic / закрытие топика | service-message | handlers | Игнорировать сервисные сообщения о топиках, если не нужны | гайд |
| Бизнес-чат | `business_message` + `business_connection_id` | handlers; отправка с `business_connection_id` | delete_message недоступен (gotcha 5.6); FSM-ключ `with_business_connection_id=True` | гайд |
| Reply-клавиатура в группе | любой show с `ReplyKeyboardFactory` | dialogs | Reply-клавиатура принадлежит чату целиком; запрещена вне DEFAULT_STACK_ID → `InvalidKeyboardType` (gotcha 8.1) | да (валидация в либе) |

---

## Категория 4. Права админа/бота, бан/разбан

| Ситуация | Тип/триггер | Где обрабатывается | Подводный камень | Покрыто? |
|---|---|---|---|---|
| Бот сделан админом / лишён прав | `my_chat_member` | handlers | Единственный надёжный источник прав; кешировать статус в Redis | частично |
| Действие требует прав, которых нет | исходящий вызов → `400`/`403` | error-handlers (`TelegramBadRequest`) | «not enough rights» — поймать, сообщить админу, не падать | частично |
| Бан/кик участника | команда/бизнес-правило → `banChatMember` | services | Идемпотентность (повторный бан — no-op); права бота; `until_date` для temp-бана | гайд |
| Разбан | `unbanChatMember` | services | `only_if_banned=True` чтобы не «приглашать» обратно | гайд |
| Бот заблокирован пользователем | исходящий → `403 "bot was blocked by the user"` | error-handlers + outer-middleware | Помечать пользователя «недоступен» в Redis; **исключить из рассылок** (категория 9) | частично |
| Пользователь деактивирован | `403 "user is deactivated"` | error-handlers | То же — пометить, не ретраить | частично |
| Проверка членства (gated-контент) | `getChatMember` | services | Лишний API-вызов; кешировать; `BgManager(load=True)` делает до 2 вызовов (gotcha 11.5) | гайд |
| Доступ к стеку/контексту диалога | внутренняя проверка | dialogs (`DefaultAccessValidator`) | `access_settings` через `start(...)`; на уровне стека не сохраняется (gotcha 2.4) | да |

---

## Категория 5. Входящие/исходящие медиа и media groups

| Ситуация | Тип/триггер | Где обрабатывается | Подводный камень | Покрыто? |
|---|---|---|---|---|
| Входящее фото/документ/видео | `message` (photo/document/...) | dialogs (`MessageInput(content_types=...)`) / handlers | Фото — взять `message.photo[-1]` (макс. размер) | да |
| Входящая media group (альбом) | несколько `message` с одним `media_group_id` | handlers + album-middleware (свой) | **Альбом приходит N апдейтами**; `MessageInput` сработает по разу на каждое (gotcha 7.5); нужна агрегация по `media_group_id` (Redis-буфер + debounce) | гайд |
| Скачать медиа из Telegram | `getFile` + `download_file` | services | `file_path` живёт ограниченно; файлы > 20 MB через getFile не скачать (лимит bot API) | частично |
| Загрузить медиа в S3 → стабильный URL | после download | storagekit `Storage.put` → `Ref.url` | storagekit пишет байты как есть — **mime/размер валидирует бот** (05 §4); опционально (только если бэкенду нужен URL) | частично |
| Отправить фото/документ | `send_photo`/`answer_*` | handlers / dialogs (`StaticMedia`/`DynamicMedia`) | Один media-виджет на окно (gotcha 6.1); медиагруппы окном не поддерживаются | да |
| Кеш file_id (не перезаливать) | рендер медиа | dialogs (`MediaIdStorage`, LRU 10240) | **In-memory, per-process**: при multi-worker/рестарте прогрев заново (gotcha 3.2); кеш по URL **бессрочен** — версионировать URL (gotcha 6.2) | частично |
| Сравнение медиа при перерисовке | `MessageManager` дифф | dialogs | По `file_unique_id`; **сохранять оба id** `MediaId(file_id, file_unique_id)` (gotcha 6.4) | да |
| Редактирование медиа | `edit_media` | dialogs | Только 5 типов editable; VIDEO_NOTE/STICKER/DICE → `KeyError`; текст↔медиа → delete+send «моргание» (gotcha 6.3) | частично |
| Отправка media group (альбом) | `send_media_group` | services/handlers (вне диалога) | aiogram_dialog не умеет; слать напрямую; 2–10 элементов; общий лимит | гайд |
| Paid media (платный контент) | `send_paid_media` `[~]` | services | XTR-цена; покупка → `purchased_paid_media` (категория 1) | гайд |
| Большой апдейт (webhook body) | webhook POST | httpkit `MaxBodyMiddleware` (1 MiB default) | Update обычно мал, но при больших captions/inline — поднять лимит или `=0` (04 §8 warning) | частично |

---

## Категория 6. Платежи (включая Telegram Stars / XTR, refund)

| Ситуация | Тип/триггер | Где обрабатывается | Подводный камень | Покрыто? |
|---|---|---|---|---|
| Выставить инвойс (фиат) | `sendInvoice` | services (provider_token из бэкенда/Vault) | provider_token — секрет (Vault через config-кит); цена в минимальных единицах | частично |
| Выставить инвойс Stars (XTR) | `sendInvoice(currency="XTR")` `[✓web]` | services | **provider_token пустой/не нужен для XTR**; `prices` в Stars; нет shipping | частично |
| Пречек платежа | `pre_checkout_query` | handlers → `answerPreCheckoutQuery(ok=...)` | **Ответ ≤ 10 секунд** иначе отмена `[✓web]`; идемпотентная валидация заказа на бэкенде до `ok=True` | да (скелет-handler) |
| Успешная оплата | `message.successful_payment` | handlers → backend (httpclient) | **At-least-once**: дедуп по `telegram_payment_charge_id`; провести заказ идемпотентно | частично |
| Возврат Stars | `refundStarPayment(user_id, charge_id)` `[✓web]` | services | Добавлен в Bot API 7.4 `[✓web]`; хранить `charge_id`; refund идемпотентен по charge_id | гайд |
| Запрос доставки (фиат, flexible) | `shipping_query` | handlers → `answerShippingQuery` | Только при `is_flexible=True`; для Stars не приходит | гайд |
| Оплата провалилась/отменена | отсутствие `successful_payment` | services (timeout/reconcile-джоба) | Не считать заказ оплаченным без `successful_payment`; reconcile через timerkit | гайд |
| Двойное списание (ретрай вебхука) | дубль `successful_payment` | outer-middleware dedup + backend idempotency | `update_id`-dedup + бизнес-дедуп по `charge_id` (двойная защита) | частично |
| Звёздный баланс / выплаты | `getStarTransactions` `[~]` | services | Для сверки; редко в боте-фронтенде | гайд |

---

## Категория 7. WebApp / Mini App + валидация initData

| Ситуация | Тип/триггер | Где обрабатывается | Подводный камень | Покрыто? |
|---|---|---|---|---|
| Кнопка запуска Mini App | inline/menu button `web_app` | dialogs (`WebApp`-кнопка) / handlers | WebApp-кнопка конвертируется в reply (web_app сохраняется), в отличие от Url (gotcha 8.4) | да |
| Данные из WebApp через кнопку меню | `message.web_app_data` | handlers | Приходит как сервисное сообщение (не у всех способов запуска) | гайд |
| **Валидация initData** | HTTP-запрос от Mini App к бэкенду/боту | webhook-route / services | HMAC-SHA256: `secret = HMAC(bot_token, "WebAppData")`, затем сверка `hash` по data-check-string `[✓web]`; **проверять `auth_date` ≤ 5 мин** `[✓web]` (anti-replay) | частично |
| initData → identity-link | после валидации | services + cachekit/authnkit | Маппинг `tg_user → backend_user`; не доверять `user.id` без валидации hash | частично |
| Mini App вызывает backend API | HTTP | httpkit (если бот хостит) / прямо к бэкенду | constant-time сравнение hash (против timing); rate-limit на эндпоинт | гайд |
| answerWebAppQuery (inline-результат из MiniApp) | `answerWebAppQuery` | services | `query_id` живёт коротко; одноразовый | гайд |

> **Камень WebApp:** валидация initData — это **не aiogram-апдейт**, а отдельный
> HTTP-эндпоинт (webhook-режим, httpkit). Секрет — тот же `BOT_TOKEN`. Сравнение
> hash делать constant-time; `auth_date`-окно обязательно.

---

## Категория 8. Rate-limit, flood control, throttling

| Ситуация | Тип/триггер | Где обрабатывается | Подводный камень | Покрыто? |
|---|---|---|---|---|
| Исходящий 429 `Too Many Requests` | `TelegramRetryAfter` | error-handlers / session-middleware (retry через tenacity) | **Outer/session-middleware ловит `TelegramRetryAfter`, ждёт `e.retry_after`** (07 §4.3); в ядре aiogram throttling нет | частично (скелет) |
| Глобальный лимит ~30 msg/s | исходящие сообщения | services/notify (свой rate-limiter) | Лимит на бота; при рассылках — токен-бакет; см. категория 9 | гайд |
| Лимит ~20 msg/min на группу | исходящие в один групповой чат | notify | Отдельный лимит per-chat для групп; учитывать в рассылках | гайд |
| Входящий флуд от пользователя | `message`/`callback_query` | outer-middleware `ThrottlingMiddleware` (свой, Redis-счётчик) | **Готового в ядре aiogram нет** (07 §4.3); делать на cachekit `INCR`+TTL (дешевле, чем bruteforcekit+Postgres, 05 §6) | гайд (скелет-заготовка) |
| Anti-spam / lockout | повторные нарушения | cachekit `INCR`/TTL или bruteforcekit | bruteforcekit тянет **Postgres** — для бота избыточно; свой Redis-счётчик (05 §6) | гайд |
| GetUpdates rate-limit (polling) | сетевые сбои | aiogram (внутри) | aiogram ретраит сам (07 §2.1) | да |
| Частые `bg.update()` (прогресс) | фоновые edit | dialogs (`BgManager`) | Дросселировать (`sleep`) против flood-limit (gotcha 11.2); bg-методы асинхронны (`call_soon`) | гайд |
| Webhook per-IP rate-limit | входящие POST | httpkit `RateLimitMiddleware` (rps=100/burst=200) | Telegram шлёт с **ограниченного пула IP** → при высоком трафике 429! Поднять лимиты или `rps=0` (04 §8 warning 4) | частично |

---

## Категория 9. Рассылки / broadcast

| Ситуация | Тип/триггер | Где обрабатывается | Подводный камень | Покрыто? |
|---|---|---|---|---|
| Массовая рассылка | команда/событие | notify (свой broadcaster) + timerkit | Соблюдать ~30 msg/s глобально; токен-бакет; **не** в одном `gather` на всех | гайд |
| Получатель заблокировал бота | `403 bot blocked` в цикле | broadcaster + error-handlers | Ловить per-получателя, помечать «мёртвым» в Redis, **продолжать** рассылку | частично |
| Чат не найден / удалён | `400 chat not found` | broadcaster | Аналогично — пометить, не падать | частично |
| Прогресс длинной рассылки | периодический отчёт | bizmetric (`biz_tg_broadcast_*`) + bg | Метрики отправлено/ошибок; не спамить статусом | гайд |
| Возобновление после рестарта | прерванная рассылка | services + бэкенд/Redis (cursor) | Состояние рассылки — на бэкенде/Redis, не в памяти (timerkit не персистентен, 04 §6) | гайд |
| Дедуп доставки (не слать дважды) | повтор джобы | cachekit (mark sent per recipient) | Идемпотентность: `sent:<campaign>:<user>` с TTL | гайд |
| Сегментация / таргет | бизнес-запрос | services → бэкенд | Список получателей — с бэкенда (httpclient), не хранить в боте | гайд |

---

## Категория 10. Webhook-безопасность и дедупликация апдейтов

| Ситуация | Тип/триггер | Где обрабатывается | Подводный камень | Покрыто? |
|---|---|---|---|---|
| Проверка `secret_token` | входящий POST | webhook-route (`X-Telegram-Bot-Api-Secret-Token`) | aiohttp `SimpleRequestHandler` проверяет сам; **в ручном FastAPI-роуте проверять руками** (07 §2.3, issue #1024) | частично |
| `set_webhook` с `allowed_updates` | startup | entrypoint | `dp.resolve_used_update_types()` + ручные типы (категория 1); `drop_pending_updates=True` при старте | частично |
| Дедуп `update_id` (at-least-once) | повтор вебхука при таймауте | outer-middleware + cachekit | Telegram ретраит апдейт при таймауте ответа → **дубли**; ключ `tg:update:<id>` короткий TTL (05 §2 пример A) | частично (скелет) |
| Идемпотентность действия | дубль апдейта прошёл dedup-окно | services + cachekit `IdempotencyStore` | Для действий с эффектом (платёж, заказ) — хранить и **ответ** (`IdempotencyStore`), не только факт | частично |
| Webhook отвечает быстро (200) | долгая обработка | webhook-route | **Не блокировать ответ** долгой работой → Telegram повторит; тяжёлое — в фон/очередь | гайд |
| Спуфинг (чужой POST без секрета) | POST без/с неверным секретом | webhook-route → 403 | Секрет 1–256 символов `A-Za-z0-9_-`; обязателен в проде | частично |
| HTTPS / валидный TLS | требование Telegram | инфра (reverse-proxy) | Telegram шлёт вебхуки только на HTTPS (443/80/88/8443) | гайд |
| Health/readiness вебхук-сервиса | `GET /health`,`/ready` | httpkit (из коробки) | `/ready` гоняет probes (Redis ping и т.п.); k8s liveness/readiness (04 §8) | да |
| Защита эндпоинта (security headers) | входящий | httpkit `SecurityHeadersMiddleware` | HSTS/nosniff/frame-options из коробки (04 §8) | да |

---

## Категория 11. Долгие операции, прогресс, chat action

| Ситуация | Тип/триггер | Где обрабатывается | Подводный камень | Покрыто? |
|---|---|---|---|---|
| Индикатор «typing»/«upload» | долгий хендлер | handlers (`bot.send_chat_action`) / `ChatActionSender` | Действие живёт ~5с — для длинных операций повторять (aiogram `ChatActionSender` делает loop) | гайд |
| Прогресс-бар в диалоге | фоновая задача | dialogs (`Progress`-виджет + `bg().update()`) | `Progress`: `percent=None` → `TypeError`, не клампится (gotcha 12.3); дросселировать update (11.2) | частично |
| Долгий вызов бэкенда | httpclient request | services (httpclient: timeout 10s, retry, breaker) | Ловить `BreakerOpenError` → «сервис занят» вместо 500 (05 §1); не блокировать event-loop | да |
| Периодическая джоба (напоминания) | timer | timerkit `PeriodicJob` | **Fixed-interval, не cron, не персистентна**; handler сам сверяется с `clock.now()`/БД (04 §6); тяжёлый handler блокирует loop | да |
| Событие бэкенда → сообщение | NATS message | notify (natskit `subscribe_json`) | core-NATS at-most-once — **в даунтайм теряется**; нужен JetStream для гарантии (05 §3) | частично |
| Фоновый рендер для другого чата | вне хендлера | dialogs (`BgManager`/`fg()`) | Не протаскивать живой `dialog_manager` в фон → `IncorrectBackgroundError` (gotcha 1.6); только chat/user/stack id | да (механизм) |
| Корреляция входящий→исходящий | per-update | httpclient `request_id` contextvar | Установить `request_id.set(f"tg-{update_id}")` в middleware → X-Request-ID в бэкенд (05 §1) | частично (скелет) |

---

## Категория 12. Ошибки Telegram API

| Ситуация | Исключение aiogram | Где обрабатывается | Подводный камень | Покрыто? |
|---|---|---|---|---|
| Бот заблокирован | `403 "bot was blocked by the user"` | error-handlers / per-call | Пометить юзера, исключить из рассылок; не ретраить | частично |
| Чат не найден | `400 "chat not found"` | error-handlers | Удалённый чат/неверный id; пометить, не падать | частично |
| message not modified | `400 "message is not modified"` | aiogram_dialog ловит сам (`MessageNotModified`) | **Не глушить в кастомном show_message** — ядро строит на нём логику «не сохранять id» (gotcha 5.4) | да |
| message to edit not found | `400 "message to edit not found"` | aiogram_dialog (fallback на send) | EDIT — намерение, не гарантия; уйдёт новое сообщение (gotcha 5.3) | да |
| can't be edited / can't be deleted | `400` | aiogram_dialog (`edit_message_safe`/`remove_message_safe`) | >48ч / business — delete недоступен (gotcha 5.6); fallback send, остаётся «хвост» | да |
| 429 retry_after | `TelegramRetryAfter` | session-middleware (retry) | Ждать `retry_after`; см. категория 8 | частично |
| Сетевой сбой | `TelegramNetworkError` | session-middleware (retry tenacity) | Ретраить только сеть/flood, не бизнес-ошибки | частично |
| Невалидный токен | `TelegramUnauthorizedError` (401) | entrypoint (fail-fast на старте) | Проверять `get_me()` на старте; не уходить в polling с битым токеном | гайд |
| Превышен callback_data 64 байта | `400` при отправке окна | dialogs | **Не валидируется либой** (gotcha 4.1); короткие id + суррогаты | гайд |
| Несериализуемые данные в FSM | `TypeError` при save (после ответа!) | dialogs (`context_saver`) | Только JSON-примитивы в dialog_data/widget_data (gotcha 2.1); ISO-строки вместо datetime | гайд |
| Любое необработанное исключение хендлера | → `dp.errors` | error-handlers (`dp.errors.register`) | **Обязателен errors-router**; логировать (logkit), не ронять процесс; на user — вежливое сообщение | частично (скелет) |
| Ошибка в getter/on_click диалога | пробрасывается в `dp.errors` | error-handlers | `TextInput` ловит только `ValueError`, прочее → errors-router (gotcha 7.2) | частично |

---

## Категория 13. Жизненный цикл: shutdown, dedup стейта, протухшие кнопки

| Ситуация | Тип/триггер | Где обрабатывается | Подводный камень | Покрыто? |
|---|---|---|---|---|
| Graceful shutdown (polling) | SIGTERM/SIGINT | entrypoint (`try/finally`) | aiogram гасит polling по сигналам (07 §4.2); `finally`: `await container.close()` → `bot.session.close()` | да (скелет) |
| Graceful shutdown (webhook) | SIGTERM | entrypoint / FastAPI lifespan | httpkit `Server.stop` graceful (shutdown_timeout); **закрыть контейнер явно** (06 §4.2 gap) | частично |
| `container.close()` обязателен | shutdown | entrypoint | Иначе не отработают yield-cleanup: http aclose, **telemetry flush потеряется**, nats drain (06 §5) | да (скелет) |
| Draining активных апдейтов | shutdown | entrypoint | Сначала перестать принимать (snять webhook/stop polling), дать доработать, потом close | гайд |
| Протухшие кнопки после рестарта | клик по старой кнопке | dialogs (`IntentErrorMiddleware`) | `OutdatedIntent`/`UnknownIntent` — либа тихо чинит стек/гасит часики (gotcha 4.4); но юзер теряет диалог | да (механизм) |
| `UnknownIntent`/`UnknownState` | клик после миграции state | **error-handler (обязателен!)** → restart в главное меню (`RESET_STACK`) | Без хендлера — молчаливая потеря диалога; **критичный пункт чеклиста B.0** | гайд (скелет-handler) |
| Миграция `StatesGroup`/`State` | деплой с переименованием | дизайн + error-handler | Старые контексты → `UnknownState`; не удалять/переименовывать без миграции (gotcha 2.3) | гайд |
| Дедуп `update_id` при ретрае | webhook at-least-once | outer-middleware + cachekit | Короткий TTL (Telegram ретраит при таймауте); см. категория 10 | частично |
| `MemoryStorage` в проде | дефолт quickstart | entrypoint (использовать RedisStorage) | Теряет стеки при рестарте + маскирует ошибки сериализации (gotcha 2.2); **RedisStorage обязателен** | гайд |
| FSM TTL (Redis не пухнет) | долгие/брошенные диалоги | entrypoint (`RedisStorage(state_ttl, data_ttl)`) | Без TTL Redis копит контексты; `remove_context` пишет `{}`, не удаляет ключ (gotcha 2.5) | гайд |
| Multi-worker гонка за стек | 2 процесса, один стек | entrypoint (`RedisEventIsolation`) | Дефолт `SimpleEventIsolation` in-memory не синхронизирует процессы (gotcha 3.1) → distributed isolation | гайд |
| Коллизия StatesGroup → Dialog | старт поллинга | CI smoke-тест | `ValueError` всплывает в `registry.refresh()`/`emit_startup`, не на импорте (gotcha 1.7); **гонять `dp.emit_startup()` на CI** | гайд |

---

## Категория 14. Локализация (i18n), редактирование, таймауты

| Ситуация | Тип/триггер | Где обрабатывается | Подводный камень | Покрыто? |
|---|---|---|---|---|
| Выбор языка пользователя | per-update | inner-middleware (locale из `language_code`/настройки) | Вешать **и на `message`, и на `callback_query`**, иначе при клике фолбэк-язык (gotcha 13.4) | частично (скелет) |
| Локаль в фоновом рендере | `aiogd_update` | middleware на `observers[DIALOG_EVENT_NAME]` | bg-апдейты не проходят обычные middleware (gotcha 11.4); `from_user` в bg может быть только `id` (11.5) | гайд |
| Перевод в виджете | рендер окна | dialogs (`I18NFormat`/`Format` + locale-ключ) | **Не кешировать текст в виджете** — сломает переключение языка (gotcha 13.4); хранить ключ, рендерить каждый показ | гайд |
| Локализованные команды | startup | entrypoint (`setMyCommands` per scope/lang) | Разные команды по `language_code` | гайд |
| Структурное логирование с контекстом | per-update | logkit (`bind_contextvars`) | Биндить `tg_user_id`/`chat_id`/`update_id` в outer-middleware (04 §3); авто trace_id/span_id | частично (скелет) |
| Лимит редактирования 48ч | edit старого сообщения | dialogs | Удаление/правка > 48ч недоступны → delete+send «хвост» (gotcha 5.6) | да (либа) |
| answerCallbackQuery таймаут | клик по кнопке | dialogs (авто) / handlers | Часики гаснут ~30с; aiogram_dialog гасит сам (`answer_callback`); в reply-окне `.answer()` падает `ValueError` (gotcha 8.2) | да |
| answerPreCheckoutQuery таймаут | пречек | handlers | **≤ 10с** `[✓web]`; см. категория 6 | да (скелет) |
| answerInlineQuery таймаут | inline_query | handlers | Ответить быстро; `cache_time` для кеша результатов | гайд |
| Длинный текст > 4096 символов | отправка/рендер | dialogs/services | `ScrollingText` режет по символам — рвёт HTML-теги/слова (gotcha 12.2); делить осознанно | частично |
| HTML/Markdown разметка | parse_mode | entrypoint (`DefaultBotProperties(parse_mode=HTML)`) + Window | `Jinja` требует `parse_mode="HTML"` (gotcha 12.4); экранировать пользовательский ввод | частично |

---

## Раздел A. Что ОБЯЗАТЕЛЬНО заложить в скелет шаблона

Эти компоненты — каркас, без которого прод-бот ломается или теряет данные. Закладываем
кодом в шаблон (не гайдом).

### A.1. Bootstrap / entrypoint (`app/main.py`)
- **RedisStorage** (не MemoryStorage) с `DefaultKeyBuilder(with_bot_id=True,
  with_destiny=True, with_business_connection_id=True)` — destiny обязателен для
  aiogram_dialog; business — для бизнес-чатов. `state_ttl`/`data_ttl` заданы.
- **`RedisEventIsolation`** через `storage.create_isolation()` → `Dispatcher(events_isolation=...)`
  — для multi-worker (gotcha 3.1).
- **`make_async_container`** со всеми pylibinfra-провайдерами (`TelemetryProvider`
  ПЕРВЫМ — иначе метрики/логи no-op, 04 предупреждение 1) + `AppConfigProvider`
  (asymmetry note: все `*Config` регистрирует caller) + `AiogramProvider()`.
- **`setup_dishka(container, router=dp, auto_inject=True)`** + `dishka.integrations.aiogram_dialog`.
- **`setup_dialogs(dp, ...)`** — ПОСЛЕДНИМ, один раз, на корневом `Dispatcher`, после
  всех `include_router` (gotcha 13.3).
- **Graceful shutdown**: `try/finally` → `await container.close()` (telemetry flush,
  nats drain, http aclose) → `await bot.session.close()`. Зарегистрировать
  `dp.shutdown.register(container.close)`.
- **Fail-fast на старте**: `get_me()` (валидный токен), `allowed_updates =
  resolve_used_update_types()` + ручные типы.
- **Режимы**: polling (dev) / webhook (prod, aiohttp `SimpleRequestHandler` или
  httpkit-FastAPI-роут с ручной проверкой секрета).

### A.2. Outer-middleware (на «сырой» апдейт)
1. **Dedup `update_id`** (cachekit, короткий TTL) — at-least-once вебхуков (05 §2).
2. **Throttling** (свой, Redis `INCR`+TTL) — заготовка-каркас, антифлуд per-user
   (в ядре aiogram нет, 07 §4.3).
3. **Context-bind**: `request_id.set(f"tg-{update_id}")` (X-Request-ID в бэкенд) +
   `logkit.bind_contextvars(tg_user_id, chat_id, update_id)`.
4. **Recovery**: ловит необработанные исключения, логирует, не роняет процесс.
- Эти же (особенно throttle/i18n/dedup) — **продублировать на
  `observers[DIALOG_EVENT_NAME]`** для bg-апдейтов (gotcha 11.4).

### A.3. Session-middleware (исходящие вызовы)
- Ретрай **`TelegramRetryAfter`** (ждать `e.retry_after`) и `TelegramNetworkError`
  через tenacity (единый ретрай-стек pylibinfra). Покрывает все вызовы без правок
  хендлеров (07 §4.3).

### A.4. Error-handlers (`dp.errors` + диалоговые)
- **`UnknownIntent`/`UnknownState`/`OutdatedIntent`** → ответить на callback,
  `RESET_STACK` в главное меню (протухшие кнопки/миграции — критично, чеклист B.0).
- **`403 bot blocked` / `400 chat not found`** → пометить юзера в Redis, не падать.
- **`pre_checkout_query`-handler** → `answerPreCheckoutQuery` ≤ 10с с валидацией.
- Глобальный errors-router: логировать (logkit), вежливое сообщение пользователю.

### A.5. Health / observability
- **`/health` + `/ready`** (httpkit, из коробки; probes: Redis ping, опц. NATS/backend).
- **bizmetric**: `biz_tg_updates_total`, `biz_tg_commands_total{command}`,
  `biz_tg_dialog_completed_total{flow}`, `biz_tg_errors_total{kind}`.
- **telemetry**: OTLP traces/metrics/logs, trace_id/span_id авто в логах.

### A.6. CI-гейт
- **`await dp.emit_startup()`** smoke-тест — ловит коллизию StatesGroup↔Dialog и
  `UnregisteredDialogError` до прода (gotcha 1.7/13.3).

---

## Раздел B. Что оставить гайдом / опциональным

Не код скелета, а документация/чеклист/опциональные модули — включаются по
потребностям конкретного бота.

| Тема | Почему гайд/опционально |
|---|---|
| **Платежи (invoice/Stars/refund)** | Скелет даёт только `pre_checkout`-handler-заглушку; конкретный flow + provider_token + reconcile — прикладной |
| **WebApp/Mini App initData** | Нужен только при наличии Mini App; валидатор HMAC + auth_date — сниппет-гайд (httpkit-эндпоинт) |
| **Inline-режим** | `inline_query`/`chosen_inline_result` — опциональны; aiogram_dialog не обслуживает |
| **Рассылки/broadcast** | Токен-бакет ~30 msg/s, сегментация, resume — отдельный модуль `notify` (гайд + заготовка) |
| **Media groups (альбомы)** | Album-middleware (агрегация по `media_group_id`) — гайд; не всем нужно |
| **storagekit (медиа в S3)** | Опционально — только если бэкенду нужен стабильный URL (05 §4) |
| **natskit JetStream** | core-NATS достаточно для best-effort; JetStream — если уведомления нельзя терять (05 §3) |
| **bruteforcekit** | НЕ тащить (Postgres); anti-spam — на cachekit Redis-счётчике (05 §6) |
| **pgkit** | Боту не нужен — state в Redis, данные на бэкендах (05 §7) |
| **business-аккаунты** | Опционально; `business_connection_id` в FSM-ключе + отдельные observers — гайд |
| **message_reaction / chat_member / chat_boost** | Требуют ручного `allowed_updates`; включать точечно — гайд |
| **topics/threads** | Если бот работает в форум-супергруппах — ответы в `message_thread_id`, гайд |
| **i18n** | Каркас-middleware в скелете; FTL/каталоги переводов — прикладные |
| **Локализованные `setMyCommands`** | Гайд (per-scope/lang) |
| **render_transitions / web-preview** | Dev-инструменты, только `[tools]`-extras, не на старте бота (gotcha 13.1/13.2) |
| **Custom MediaIdStorage (Redis)** | Опционально — общий кеш file_id между воркерами (gotcha 3.2) |

---

## Открытые вопросы (требуют проверки на целевых пинах)

1. `[~]` `purchased_paid_media` / `PaidMediaPurchased`, `chat_boost` — наличие и точные
   типы в aiogram 3.28.2 (проверить по `aiogram.types`).
2. `[~]` Точное имя ключа REQUEST-контейнера в `manager.middleware_data` для
   fallback-инъекции в aiogram_dialog (dishka 1.10.x) — см. 06 §3.
3. `[~]` Поведение `with_destiny`/`with_business_connection_id` в `DefaultKeyBuilder`
   совместно с aiogram_dialog 2.6.0 — интеграционный прогон.
4. `[~]` httpkit `build_app()` ↔ dishka FastAPI-lifespan для webhook-режима (gap из 06 §4.2).
5. `[✓web]` answerPreCheckoutQuery ≤ 10с, refundStarPayment (Bot API 7.4), XTR-валюта,
   initData HMAC + auth_date 5 мин — подтверждено, но реализацию сверить с пином.

---

## Источники (web-проверка свежих фич Telegram)

- Telegram Stars / pre_checkout / refundStarPayment — [core.telegram.org/bots/payments-stars](https://core.telegram.org/bots/payments-stars), [Bot API changelog](https://core.telegram.org/bots/api-changelog)
- Business / message_reaction / paid_media update-типы — [core.telegram.org/bots/api](https://core.telegram.org/bots/api), [Business API](https://core.telegram.org/api/business)
- WebApp/Mini App initData validation (HMAC-SHA256 + auth_date) — [core.telegram.org/bots/webapps](https://core.telegram.org/bots/webapps), [Telegram Mini Apps — Validating](https://docs.telegram-mini-apps.com/packages/tma-js-init-data-node/validating)
- Локальные первоисточники: артефакты `_research/04..07`, `aiogram-dialog-docs/guides/{architecture,gotchas-and-production-checklist}.md`, `reference/01..20`.
