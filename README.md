# Distinct News Bot

Telegram-бот **SEO-дайджеста** из ваших публичных каналов и RSS-блогов: без дублей, рекламы и оффтопа.

Работает в **личке и в групповых чатах**. У каждого чата свои источники, темы и расписание; в группе настраивать могут администраторы.

`/news` собирает новости за период, раскладывает по блокам (Google / линкбилдинг / инструменты / аналитика / ИИ / контент), пишет выжимку и сортирует по реакциям.

Источники:
- **SEO-блоги (RSS)** — Ahrefs, Backlinko, Moz, SEJ, Search Engine Land, Semrush, Google Search Central, Screaming Frog, Aleyda Solis, Marie Haynes. Включены в каждую сводку у всех и **не занимают слоты плана**.
- свои публичные Telegram-каналы (`@channel` / `https://t.me/channel` / папка `t.me/addlist/…`);
- дополнительные RSS (`/add rss https://site.com/feed/`) — уже считаются в лимит плана.

---

## Логика работы

### Архитектура

| Компонент | Точка входа | Роль |
| --- | --- | --- |
| Бот | `python -m bot` → `bot/__main__.py` | Polling Telegram, сборка дайджестов, расписание |
| Dashboard | `python -m dashboard` | Read-only веб-статистика по той же SQLite |
| Docker | `docker-compose.yml` | Сервисы `bot` + `dashboard`, volume `bot-data` |

**Стек:** Python ≥3.11, `python-telegram-bot` (polling + JobQueue), SQLite, Starlette/Jinja2/uvicorn, httpx + BeautifulSoup/lxml.

**Старт бота:**
1. `Settings.from_env()` → флаг монетизации (`set_monetization_enabled`)
2. `Database` + `DigestService`
3. Регистрация хендлеров и error handler
4. `post_init`: джоба расписания + `set_my_commands`
5. `prefer_ipv4()` — обход проблемных IPv6-маршрутов к api.telegram.org
6. Polling: `message`, `callback_query`, `pre_checkout_query`, `my_chat_member`

**Workspace (`chat_scope.workspace_id`):** ключ данных = `chat.id` (личка — user id; группа — отрицательный id). Источники, темы, seen-fingerprints, план и расписание живут на чат, а не глобально на пользователя.

Карта модулей:

| Модуль | Ответственность |
| --- | --- |
| `handlers` | команды, роутер текста, регистрация |
| `menu` | inline/reply UI, callbacks, awaiting-состояния, отправка дайджеста |
| `keyboards` | reply/inline-разметки |
| `digest` | сборка и форматирование сводки |
| `analyzer` / `summarize` / `ai_summarize` / `dedupe` / `seo_prompt` | пайплайн контента |
| `fetchers/*` / `http_util` | загрузка Telegram/RSS |
| `builtin_sources` / `channel_presets` / `addlist` / `sources_ops` | источники |
| `topics` / `schedule` / `jobs` | фильтры и автозапуск |
| `plans` / `payments` | лимиты и Stars |
| `db` / `models` / `chat_scope` | SQLite и scope чата |
| `dashboard/*` | веб-статистика |
| `telegram_util` | soft errors, IPv4, безопасные callbacks |

### Пользовательские сценарии

**`/start`**
- Создаёт workspace (`db.ensure_user`) с планом `trial` (7 дней).
- В группе — только админы; приветствие + inline-меню.
- В личке без источников — режим `onboard`: просит 1–3 @channel/RSS и сразу делает пробную сводку.
- В личке с источниками — справка + `/menu`; reply-клавиатура по умолчанию скрыта.

**Меню**
- Reply-кнопки (личка): Сводка / Только новое / Источники / Темы / Расписание [/ Подписка] / Меню / Помощь / Скрыть кнопки.
- Inline (`/menu`, callbacks `m:*`): те же действия без постоянной клавиатуры.
- «Скрыть кнопки» / «Показать кнопки» управляют reply-клавиатурой.

**Источники**
- `/add`, awaiting `source`, пресеты, bulk из текста.
- Типы: `telegram`, `rss` (устаревшие `ria`/`facebook`/`twitter` при fetch дают ошибку).
- `/remove <id>`, `/sources`, удаление кнопками.
- В лимит плана входят только **свои** источники; builtin SEO-RSS — нет.

**Дайджесты**
- `/news` | `/digest` [`new`] [`N`] — окно в днях (по умолчанию `DEFAULT_DIGEST_DAYS`), режим «топ по реакциям» или «только новое».
- Пагинация по `DIGEST_PAGE_SIZE` (callbacks `m:dg:N`); страницы держатся в памяти и в таблице `digest_sessions` (переживают рестарт).

**Темы**
- OR-фильтр: материал попадает в сводку, если в заголовке/тексте есть **хотя бы одна** тема.
- Без тем — все SEO-релевантные новости.
- `/topic add|del|clear`, `/topics`, синонимы `/filter` / `/filters`.

**Расписание**
- `/schedule on|off|time|tz` (по умолчанию 09:55, UTC+3).
- Авто-сводка — за **вчерашний календарный день** в TZ пользователя.
- Джоба каждую минуту (`jobs.scheduled_digest_tick`).

**Awaiting-состояния** (`menu`):

| kind | Когда | Что делает |
| --- | --- | --- |
| `onboard` | первый `/start` без источников | add + пробный digest |
| `source` | «Добавить источник» | канал / RSS / addlist |
| `topic` | «Добавить тему» | `db.add_topic` |
| `addlist_channels` | после названия папки | ручной список `@handles` |

`/cancel` сбрасывает ожидание.

**Группы**
- Настраивать могут только admin/owner.
- Авто-сводка уходит **в группу**.
- Оплата Stars только в личке; план группе — `/grant <chat_id> pro|plus`.

### Пайплайн дайджеста

Оркестратор: `DigestService.collect_for_user` → форматирование → доставка в чат.

```
sources = merge_sources(user)          # builtin RSS + свои
  → parallel fetch (HttpService)
  → filter по окну [since, until)
  → filter topics (если заданы)
  → NewsAnalyzer.process
       filter_noise → filter_relevant → deduplicate
       → clean_and_summarize → categorize → sort_by_reactions
  → only_unseen? filter_unseen(fingerprints)
  → truncate DIGEST_LIMIT
  → optional AI enrich_items
  → format HTML pages → mark_digest_delivered
```

**Fetch**
- Telegram (`TelegramChannelFetcher`): публичная страница `https://t.me/s/<handle>`, пагинация `?before=`, реакции/просмотры из виджета. Число страниц: 2 (короткое окно) / 5 (≥5 дней).
- RSS (`RssFetcher`): RSS 2.0 / Atom / RDF; реакций нет — при нуле реакций сортировка по дате.
- Общий HTTP: concurrency, retries, TTL-кэш (`FETCH_*`).

**Шум и релевантность** (`analyzer`)
- Отсев коротких текстов, рекламы, вакансий, курсов, покупки ссылок (RU+EN stop-phrases).
- SEO-релевантность по `SEO_RELEVANCE_KEYWORDS` из `seo_prompt`.

**Дедуп** (`dedupe`)
- Точный URL, похожесть заголовков/текста (SequenceMatcher ≥0.86), Jaccard токенов по смыслу (без стоп-слов вроде «как/для/seo»).
- Кросс-язык RU↔EN: перевод известных синонимов (`гугл`↔`google`, `программатик`↔`programmatic`, …), затем сравнение **переведённого текста**. Совпадение только по тематическим тегам (`seo`+`guide`, `google`+`serp`) дублем не считается — нужны общие отличительные якоря истории и высокий Jaccard/sequence overlap.
- Merge дублей: больше реакций/просмотров, объединение urls, более длинный title/summary, более ранняя дата.
- «Уже видели»: SHA256 нормализованного title (fallback — url); очистка старше 30 дней.
- `/reset` сбрасывает seen и `last_digest_at`, чтобы «Только новое» снова показало материалы.

**Категории** (порядок в сводке):
1. 🔍 Google и Поиск
2. 🔗 Линкбилдинг и E-E-A-T
3. 🛠 Инструменты и Сервисы
4. 📈 Аналитика и Метрики
5. 🤖 ИИ в SEO
6. 📝 Контент и Копирайтинг

**Выжимки**
- Rule-based (`summarize`): чистка HTML/хештегов/URL, отсев интро, scoring «новостных» глаголов, опционально sumy LSA.
- AI (`ai_summarize`, если `AI_SUMMARY_ENABLED=1` + ключ): Gemini Flash (default) или Groq; ровно N предложений **на русском**; при сбое — fallback на rule-based.
- По умолчанию `SUMMARY_MAX_SENTENCES=2`.

**Публикация**
- HTML в Telegram (категории `<b>`, ссылки `<a>`), без web preview.
- Статусы прогресса: «Читаю…» → «Фильтрую…» → «Пишу выжимки…».
- Перед сбором списывается дневная квота; на чат — lock против параллельных сборок.
- После доставки: `mark_seen`, `set_last_digest_at`, `log_digest_event(trigger)`.

Публичных HTML-страниц дайджестов нет: «SEO» здесь — тематика контента и промпты (`seo_prompt`), а не отдельный сайт.

### Builtin-источники, пресеты, addlist

- **Builtin RSS** (`builtin_sources` / пресет `seo-blogs`): подмешиваются в каждый digest через `merge_sources`, не пишутся в таблицу `sources`, id отрицательные, слоты плана не занимают.
- **Пресет каналов** `seo-igaming`: набор TG-каналов + addlist URL; кнопка `m:src_preset:seo-igaming`.
- **Addlist** (`t.me/addlist/…`): Telegram не отдаёт список каналов папки ботам. Бот читает название (og:title) и просит прислать публичные `@username` вручную — либо принимает handles сразу в команде.

### База данных

Таблицы SQLite:
- `users` — workspace, schedule, plan, digest quota, `last_digest_at`
- `sources` — UNIQUE(user_id, type, identifier)
- `seen_items` — fingerprint уже показанных материалов
- `topics` — фильтры тем
- `digest_events` — аналитика срабатываний
- `digest_sessions` — JSON страниц для пагинации после рестарта

Ключевые операции: CRUD источников/тем, `mark_seen` / `filter_unseen` / `clear_seen`, schedule due-list, `consume_digest_quota`, статистика для dashboard, `delete_user_data` (CASCADE).

Модели: `Source`, `NewsItem` (title, url, published_at, summary/body, reactions/views, urls[], external_id).

### Расписание (jobs)

- Repeating job каждые **60 с** (первый тик через ~20 с).
- `list_due_schedules`: локальное время ≥ заданного и `last_schedule_date != today`.
- Перед отправкой — `mark_schedule_sent` (антидубль).
- Окно: вчерашний день в TZ пользователя; preface «Авто-сводка за YYYY-MM-DD».
- Trigger в логе: `scheduled`. Без JobQueue авто-сводок нет (warning в лог).

### Планы и монетизация

Kill-switch `MONETIZATION_ENABLED` (сейчас по умолчанию **выключен** → эффективный план `open`, лимиты и Stars не действуют).

| План | Свои источники | Сводки/день | Окно дней | Schedule | Stars |
| --- | --- | --- | --- | --- | --- |
| trial (7д) | 30 | 10 | 7 | да | — |
| free | 15 | 10 | 7 | да | — |
| pro | 30 | 20 | 7 | да | ~350/мес |
| plus | 100 | 50 | 14 | да | ~700/мес |
| open (monetization off) | 10k | 10k | 30 | да | — |

- Trial → free по истечении; pro/plus → free по `plan_expires_at`.
- Оплата: `/buy pro|plus` → invoice XTR → `pre_checkout` → `successful_payment` → `set_plan`.
- Дневная квота по UTC-дате (`digest_day` / `digests_today`).
- `/plan` — статус; `/delete_me` — удалить данные workspace.
- Админ (`ADMIN_USER_IDS`): `/grant`, `/stats`.

### Dashboard

Starlette, **без auth** (рассчитывает на reverse-proxy / localhost). Та же БД, монтируется read-only.

| Route | Содержание |
| --- | --- |
| `/` | обзор: пользователи (личка/группа), планы, активность 7/30д, дайджесты, новые |
| `/users` | таблица workspace; клик по заголовку столбца — сортировка |
| `/health` | `ok` |

### Языки (RU / EN)

- UI бота и dashboard — **русский** (команды, help, кнопки, статусы).
- Контент источников — RU и EN; noise/relevance/categories — двуязычные ключевые слова.
- Дедуп учитывает RU↔EN синонимы SEO-терминов.
- AI-выжимки **всегда на русском**, даже для английских постов.
- Русские алиасы команд: `новое`, `вкл`/`выкл`, `час`, `пояс`.

---

## Команды

- `/start`, `/help` — справка
- `/add @channel [название]` — добавить канал
- `/add telegram @a @b` — несколько каналов сразу
- `/add rss https://site.com/feed/ [название]` — RSS/Atom-фид
- `/addlist https://t.me/addlist/…` — импорт папки (затем список @каналов)
- `/remove <id>` — удалить
- `/sources` — список
- `/news` (или `/digest`) — SEO-дайджест за период (по умолчанию `DEFAULT_DIGEST_DAYS`)
- `/news 7` — топ по реакциям за 7 дней
- `/news new` — только посты, которых ещё не было в сводках
- `/schedule on 9:55` — ежедневная авто-сводка за вчерашний день (время и часовой пояс)
- `/reset` — сбросить просмотренное (чтобы «Только новое» снова их показало)
- `/menu` — inline-меню
- `/cancel` — отмена awaiting-режима

### Темы (фильтры)

- `/topic add ai` — добавить тему (`/topic ai` тоже работает)
- `/topic add marketing, ai` — несколько тем сразу
- `/topic del ai` — удалить
- `/topics` — список
- `/topic clear` — сбросить все фильтры

Синонимы: `/filter`, `/filters`.

### Кнопки

- Reply-кнопки: Сводка / Только новое / Источники / Темы / Расписание / Меню / Помощь / Скрыть кнопки
- Inline-меню: режим сводки, источники, темы, расписание
- При первом `/start` без источников бот просит прислать 1–3 @channel или RSS и сразу делает пробную сводку
- Авто-сводка: `/schedule on 9:55` (по умолчанию UTC+3, новости за вчера)

Примеры:

```text
/add meduzalive
/add @ch1 @ch2 https://t.me/ch3
/add rss https://ahrefs.com/blog/feed/
/addlist https://t.me/addlist/_0flf9ViWOo0NjNi
/topic add ai
/news
```

### Групповые чаты

1. Добавьте бота в группу (лучше сразу админом).
2. Админ: `/start` → `/add @channel` → `/news`.
3. `/schedule on 9` — авто-сводка приходит **в группу**.
4. Оплата Stars (`/buy`) — только в личке с ботом; для группы план можно выдать через `/grant <chat_id> pro`.

В BotFather для групп обычно достаточно Privacy Mode = ON (бот видит команды).

### Папки каналов (`t.me/addlist`)

1. Пришлите `/addlist https://t.me/addlist/…` (или просто ссылку).
2. Бот покажет название папки.
3. Пришлите публичные `@username` каналов из папки вручную (через пробел или с новой строки).

Либо сразу: `/add @ch1 @ch2 https://t.me/ch3`.

### Подписка (Telegram Stars)

Сейчас монетизация **временно выключена** (`MONETIZATION_ENABLED=0`): лимиты и оплата Stars не действуют. Чтобы включить снова — `MONETIZATION_ENABLED=1`.

При включённой монетизации:
- Trial 7 дней: 30 источников, расписание доступно
- Free: 15 своих источников, 10 сводок/день, окно 7 дней, расписание (SEO-блоги RSS всё равно в сводке и слоты не занимают)
- Pro / Plus: больше источников и сводок, расписание — оплата Stars (`/buy pro`, `/buy plus`)
- `/plan` — статус; `/delete_me` — удалить данные
- Админ: `ADMIN_USER_IDS`, команды `/grant`, `/stats`
- Веб-морда со статистикой: сервис `dashboard` в Docker Compose (см. ниже)

Каналы должны быть **публичными** (доступен `https://t.me/s/<channel>`). RSS-фид должен отдавать XML (RSS или Atom).

Опционально AI-выжимки (Gemini Flash / Groq): `AI_SUMMARY_ENABLED=1` + `GEMINI_API_KEY` (или `GROQ_API_KEY`). Без ключа — rule-based саммаризация.

---

## Локальный запуск

```bash
cp .env.example .env
# заполните TELEGRAM_BOT_TOKEN

python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
python -m bot
```

Тесты:

```bash
pytest -q
```

## Docker

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f bot
```

Контейнер `distinct-news-bot` и volume `bot-data` изолированы — можно ставить рядом с уже работающими ботами на том же сервере.

### Веб-морда (статистика)

После деплоя dashboard доступен по HTTP и HTTPS:

```bash
open "http://your.server/"
open "https://your.server/"   # самоподписанный сертификат
```

Страницы:
- `/` — обзор (пользователи, планы, активность, дайджесты)
- `/users` — таблица workspace; клик по заголовку столбца сортирует (повторный клик — обратный порядок)

## Деплой на VPS (рядом с существующим ботом)

На сервере (один раз, если Docker уже есть — достаточно создать каталог):

```bash
sudo bash deploy/setup-server.sh /opt/distinct-news-bot
```

С вашей машины:

```bash
export DEPLOY_HOST=your.server.ip
export DEPLOY_USER=ubuntu
# export DEPLOY_SSH_KEY=~/.ssh/id_ed25519
# export DEPLOY_PATH=/opt/distinct-news-bot

# один раз на сервере создайте .env:
#   cp deploy/env.production.example /opt/distinct-news-bot/.env
#   и пропишите TELEGRAM_BOT_TOKEN

./deploy/deploy.sh
```

Скрипт синхронизирует файлы в `/opt/distinct-news-bot`, собирает образ и перезапускает только этот compose-проект. Другие контейнеры не трогает.

## Переменные окружения

| Переменная | Описание |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | токен от BotFather |
| `BOT_DB` | путь к SQLite (по умолчанию `data/bot.sqlite3`) |
| `DIGEST_LIMIT` | максимум новостей в одной сводке (по умолчанию 30) |
| `DIGEST_PAGE_SIZE` | сколько пунктов в одном сообщении сводки (по умолчанию 10) |
| `DEFAULT_DIGEST_DAYS` | окно сводки в днях (по умолчанию из `DEFAULT_LOOKBACK_HOURS`) |
| `DEFAULT_LOOKBACK_HOURS` | запасное окно, если `DEFAULT_DIGEST_DAYS` не задан (24 → 1 день) |
| `SUMMARY_MAX_SENTENCES` | предложений в выжимке одного поста (по умолчанию 2) |
| `FETCH_TIMEOUT_SECONDS` | таймаут HTTP (по умолчанию 20) |
| `FETCH_CONCURRENCY` | параллельных запросов (по умолчанию 5) |
| `FETCH_CACHE_TTL_SECONDS` | TTL кэша HTML/фидов в секундах (по умолчанию 120) |
| `ADMIN_USER_IDS` | telegram user id через запятую для `/grant` и `/stats` |
| `MONETIZATION_ENABLED` | `0` — лимиты/Stars выключены; `1` — включить |
| `PRO_STARS_PRICE` / `PLUS_STARS_PRICE` | цена подписки в Stars (350 / 700) |
| `AI_SUMMARY_ENABLED` | `1` — AI-выжимки |
| `AI_PROVIDER` | `gemini` (default) или `groq` |
| `GEMINI_API_KEY` / `GROQ_API_KEY` | ключ провайдера |
| `AI_MODEL` | модель (default: `gemini-2.0-flash` / `llama-3.3-70b-versatile`) |
| `AI_MAX_CONCURRENT` / `AI_TIMEOUT_SECONDS` | параллелизм и таймаут AI (4 / 15) |
| `DASHBOARD_PORT` | порт внутри контейнера (по умолчанию 8080) |
| `LOG_LEVEL` | `INFO` / `DEBUG` |
