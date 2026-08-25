# Distinct News Bot

Telegram-бот, который собирает сводку новостей из **ваших публичных Telegram-каналов** без дублей.

Пользователь добавляет каналы, затем `/news` отдаёт **главные новости за период** — с выжимкой, без дублей, отсортированные по реакциям.

Источники: только публичные Telegram-каналы (`@channel` / `https://t.me/channel` / папка `t.me/addlist/…`). Читаем через публичный превью `t.me/s/...`.

## Команды

- `/start`, `/help` — справка
- `/add @channel [название]` — добавить канал
- `/add telegram @a @b` — несколько каналов сразу
- `/addlist https://t.me/addlist/…` — импорт папки (затем список @каналов)
- `/remove <id>` — удалить
- `/sources` — список
- `/news` (или `/digest`) — главные новости за период (по умолчанию `DEFAULT_DIGEST_DAYS`)
- `/news 7` — топ по реакциям за 7 дней
- `/news new` — только посты, которых ещё не было в сводках
- `/schedule` — ежедневная авто-сводка (час и часовой пояс)
- `/reset` — сбросить просмотренное (чтобы «Только новое» снова их показало)

### Темы (фильтры)

Если темы заданы, в `/news` попадают только материалы, где встречается **хотя бы одна** тема (в заголовке или тексте). Без тем — все новости.

- `/topic add ai` — добавить тему (`/topic ai` тоже работает)
- `/topic add marketing, ai` — несколько тем сразу
- `/topic del ai` — удалить
- `/topics` — список
- `/topic clear` — сбросить все фильтры

Синонимы: `/filter`, `/filters`.

### Кнопки

- Reply-кнопки: Сводка / Только новое / Источники / Темы / Расписание / Меню / Помощь
- `/menu` — inline-меню: выбор режима сводки, каналы, темы, расписание
- При первом `/start` без каналов бот просит прислать 1–3 @channel и сразу делает пробную сводку
- Авто-сводка: `/schedule on 9` (по умолчанию UTC+3), джоба проверяет расписание каждые 5 минут
- При добавлении бот просит прислать каналы следующим сообщением (`/cancel` — отмена)

Примеры:

```text
/add meduzalive
/add @ch1 @ch2 https://t.me/ch3
/addlist https://t.me/addlist/_0flf9ViWOo0NjNi
/topic add ai
/news
```

### Папки каналов (`t.me/addlist`)

1. Пришлите `/addlist https://t.me/addlist/…` (или просто ссылку).
2. Бот покажет название папки.
3. Пришлите публичные `@username` каналов из папки вручную (через пробел или с новой строки). Telegram не отдаёт список каналов папки ботам.

Либо сразу: `/add @ch1 @ch2 https://t.me/ch3`.

### Подписка (Telegram Stars)

- Trial 7 дней (как Pro)
- Free: 3 канала, 3 сводки/день, без расписания
- Pro / Plus: больше каналов и сводок, расписание — оплата Stars (`/buy pro`, `/buy plus`)
- `/plan` — статус; `/delete_me` — удалить данные
- Админ: `ADMIN_USER_IDS`, команды `/grant`, `/stats`

Дубли отсекаются по заголовку, URL и похожести текстов. Сводка ранжирует оставшиеся посты по реакциям и просмотрам.

Каналы должны быть **публичными** (доступен `https://t.me/s/<channel>`).

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
| `PRO_STARS_PRICE` / `PLUS_STARS_PRICE` | цена подписки в Stars |
| `LOG_LEVEL` | `INFO` / `DEBUG` |
