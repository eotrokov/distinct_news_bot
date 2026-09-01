# Distinct News Bot

Telegram-бот **SEO-дайджеста** из ваших публичных каналов и RSS-блогов: без дублей, рекламы и оффтопа.

Работает в **личке и в групповых чатах**. У каждого чата свои источники, темы и расписание; в группе настраивать могут администраторы.

`/news` собирает новости за период, раскладывает по блокам (Google / линкбилдинг / инструменты / аналитика / ИИ / контент), пишет выжимку из 2 предложений и сортирует по реакциям.

Источники:
- **SEO-блоги (RSS)** — Ahrefs, Backlinko, Moz, SEJ, Search Engine Land, Semrush, Google Search Central, Screaming Frog, Aleyda Solis, Marie Haynes. Включены в каждую сводку у всех и **не занимают слоты плана**.
- свои публичные Telegram-каналы (`@channel` / `https://t.me/channel` / папка `t.me/addlist/…`);
- дополнительные RSS (`/add rss https://site.com/feed/`) — уже считаются в лимит плана.

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

### Темы (фильтры)

Если темы заданы, в `/news` попадают только материалы, где встречается **хотя бы одна** тема (в заголовке или тексте). Без тем — все SEO-релевантные новости.

- `/topic add ai` — добавить тему (`/topic ai` тоже работает)
- `/topic add marketing, ai` — несколько тем сразу
- `/topic del ai` — удалить
- `/topics` — список
- `/topic clear` — сбросить все фильтры

Синонимы: `/filter`, `/filters`.

### Кнопки

- Reply-кнопки: Сводка / Только новое / Источники / Темы / Расписание / Меню / Помощь
- `/menu` — inline-меню: выбор режима сводки, источники, темы, расписание
- При первом `/start` без источников бот просит прислать 1–3 @channel или RSS-фид и сразу делает пробную сводку
- Авто-сводка: `/schedule on 9:55` (по умолчанию UTC+3, новости за вчера), джоба проверяет расписание каждую минуту
- При добавлении бот просит прислать каналы или RSS следующим сообщением (`/cancel` — отмена)

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
3. Пришлите публичные `@username` каналов из папки вручную (через пробел или с новой строки). Telegram не отдаёт список каналов папки ботам.

Либо сразу: `/add @ch1 @ch2 https://t.me/ch3`.

### Подписка (Telegram Stars)

- Trial 7 дней: 30 источников, расписание доступно
- Free: 15 своих источников, 10 сводок/день, окно 7 дней, расписание (SEO-блоги RSS всё равно в сводке и слоты не занимают)
- Pro / Plus: больше источников и сводок, расписание — оплата Stars (`/buy pro`, `/buy plus`)
- `/plan` — статус; `/delete_me` — удалить данные
- Админ: `ADMIN_USER_IDS`, команды `/grant`, `/stats`
- Веб-морда со статистикой: сервис `dashboard` в Docker Compose (см. ниже)

Каналы должны быть **публичными** (доступен `https://t.me/s/<channel>`). RSS-фид должен отдавать XML (RSS или Atom).

Дубли отсекаются по заголовку, URL и похожести текстов. Оффтоп и реклама (курсы, вакансии, покупка ссылок) отфильтровываются. Сводка группирует по SEO-блокам и ранжирует по реакциям. Записи RSS без реакций попадают в те же блоки и сортируются по дате публикации.

Опционально AI-выжимки (Gemini Flash / Groq): `AI_SUMMARY_ENABLED=1` + `GEMINI_API_KEY`. Без ключа — rule-based саммаризация (2 предложения).

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
- `/users` — таблица workspace с источниками, темами и последней активностью

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
| `BOT_DB` | путь к SQLite |
| `DIGEST_LIMIT` | максимум новостей в одной сводке (по умолчанию 30) |
| `DIGEST_PAGE_SIZE` | сколько пунктов в одном сообщении сводки (по умолчанию 10) |
| `DEFAULT_DIGEST_DAYS` | окно сводки в днях (по умолчанию из `DEFAULT_LOOKBACK_HOURS`) |
| `DEFAULT_LOOKBACK_HOURS` | запасное окно, если `DEFAULT_DIGEST_DAYS` не задан |
| `SUMMARY_MAX_SENTENCES` | сколько предложений в выжимке одного поста (по умолчанию 3) |
| `FETCH_CONCURRENCY` | параллельных запросов к t.me (по умолчанию 5) |
| `FETCH_CACHE_TTL_SECONDS` | TTL кэша HTML каналов в секундах (по умолчанию 120) |
| `ADMIN_USER_IDS` | telegram user id через запятую для `/grant` и `/stats` |
| `DASHBOARD_PORT` | порт внутри контейнера (по умолчанию 8080; снаружи проброшен 443) |
| `PRO_STARS_PRICE` / `PLUS_STARS_PRICE` | цена подписки в Stars |
| `LOG_LEVEL` | `INFO` / `DEBUG` |
