# Distinct News Bot

Telegram-бот, который собирает сводку новостей из ваших источников **без дублей**.

Пользователь добавляет источники командами, затем `/news` отдаёт новости **с момента предыдущего запроса**.

Поддерживаемые типы источников:

| Тип | Что указать | Как читаем |
| --- | --- | --- |
| `telegram` | `@channel` / `channel` / `https://t.me/channel` / несколько сразу / `https://t.me/addlist/…` | публичный превью `t.me/s/...` |
| `ria` | `main`, `politics`, `world`, … или URL RSS | официальный RSS РИА |
| `rss` | любой RSS/Atom URL | feedparser |
| `facebook` | имя страницы или URL RSS | RSSHub (`RSSHUB_BASE_URL`) либо прямой RSS |
| `twitter` | `@user` / URL профиля или RSS | RSSHub либо прямой RSS |

## Команды

- `/start`, `/help` — справка
- `/add <тип> <id|url> [название]` — добавить источник
- `/add telegram @a @b` — несколько Telegram-каналов сразу
- `/addlist https://t.me/addlist/…` — все публичные каналы из папки
- `/remove <id>` — удалить
- `/sources` — список
- `/news` (или `/digest`) — сводка с прошлого запроса
- `/reset` — сбросить курсор прошлого запроса
- `/tg_login +телефон`, `/tg_code`, `/tg_status` — вход для разбора addlist

### Темы (фильтры)

Если темы заданы, в `/news` попадают только материалы, где встречается **хотя бы одна** тема (в заголовке или тексте). Без тем — все новости.

- `/topic add seo` — добавить тему (`/topic seo` тоже работает)
- `/topic add marketing, ai` — несколько тем сразу
- `/topic del seo` — удалить
- `/topics` — список
- `/topic clear` — сбросить все фильтры

Синонимы: `/filter`, `/filters`.

### Кнопки

- Reply-кнопки внизу экрана: Сводка / Источники / Темы / Меню / Помощь / Сброс курсора
- `/menu` — inline-меню: сводка, управление источниками и темами (добавление/удаление)
- При добавлении бот просит прислать значение следующим сообщением (`/cancel` — отмена)

Примеры:

```text
/add telegram meduzalive
/add telegram @ch1 @ch2 https://t.me/ch3
/addlist https://t.me/addlist/_0flf9ViWOo0NjNi
/add ria main
/topic add seo
/news
```

### Папки каналов (`t.me/addlist`)

Telegram отдаёт состав папки только пользовательскому API (боту нельзя). Один раз:

1. Создайте приложение на [my.telegram.org](https://my.telegram.org) → API development tools
2. Пропишите `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` в `.env`
3. В боте: `/tg_login +79001234567` → `/tg_code 12345`
4. Дальше: `/addlist https://t.me/addlist/…` или просто пришлите ссылку

Сессия сохраняется в `TELEGRAM_SESSION_PATH` (по умолчанию рядом с SQLite). Добавляются только **публичные** каналы с `@username`.

Дубли отсекаются по нормализованному заголовку, URL и похожести текстов между источниками. Уже показанные пользователю новости не повторяются.

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
| `DEFAULT_LOOKBACK_HOURS` | окно для первого `/news`, если ещё не было запросов |
| `RSSHUB_BASE_URL` | базовый URL RSSHub для Facebook/Twitter |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | пользовательский API для `/addlist` |
| `TELEGRAM_SESSION_PATH` | файл сессии Telethon (по умолчанию рядом с БД) |
| `LOG_LEVEL` | `INFO` / `DEBUG` |

## Замечания по Facebook / Twitter

Официальные API Facebook и X требуют отдельных ключей и часто платные. Бот использует RSS:

1. поднимите [RSSHub](https://github.com/DIYgod/RSSHub) (или укажите публичный инстанс) в `RSSHUB_BASE_URL`;
2. либо передайте готовый RSS URL в `/add facebook …` / `/add twitter …` / `/add rss …`.

Telegram-каналы должны быть **публичными** (доступен `https://t.me/s/<channel>`).
