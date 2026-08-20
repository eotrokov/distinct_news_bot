# Distinct News Bot

Telegram-бот, который собирает сводку из ваших **Telegram-каналов** без дублей.

Пользователь добавляет каналы, затем `/news` отдаёт посты **с момента предыдущего запроса**.

| Что указать | Как читаем |
| --- | --- |
| `@channel` / `channel` / `https://t.me/channel` | публичный превью `t.me/s/...` |
| несколько каналов сразу | то же |
| `https://t.me/addlist/…` | название папки + список `@каналов` от вас |

## Команды

- `/start`, `/help` — справка
- `/add @channel` — добавить канал
- `/add @a @b` — несколько сразу
- `/addlist https://t.me/addlist/…` — импорт папки (затем список @каналов)
- `/remove <id>` — удалить
- `/sources` — список каналов
- `/news` (или `/digest`) — сводка с прошлого запроса
- `/reset` — сбросить курсор прошлого запроса

### Темы (фильтры)

Если темы заданы, в `/news` попадают только материалы, где встречается **хотя бы одна** тема (в заголовке или тексте). Без тем — все посты.

- `/topic add seo` — добавить тему (`/topic seo` тоже работает)
- `/topic add marketing, ai` — несколько тем сразу
- `/topic del seo` — удалить
- `/topics` — список
- `/topic clear` — сбросить все фильтры

Синонимы: `/filter`, `/filters`.

### Кнопки

- Reply-кнопки внизу экрана: Сводка / Каналы / Темы / Меню / Помощь / Сброс курсора
- `/menu` — inline-меню
- При добавлении бот просит прислать значение следующим сообщением (`/cancel` — отмена)

Примеры:

```text
/add @meduzalive
/add @ch1 @ch2 https://t.me/ch3
/addlist https://t.me/addlist/_0flf9ViWOo0NjNi
/topic add seo
/news
```

### Папки каналов (`t.me/addlist`)

1. Пришлите `/addlist https://t.me/addlist/…` (или просто ссылку).
2. Бот покажет название папки.
3. Пришлите публичные `@username` каналов из папки.

Дубли отсекаются по нормализованному заголовку, URL и похожести текстов. Уже показанные посты не повторяются.

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

## Деплой на VPS

```bash
sudo bash deploy/setup-server.sh /opt/distinct-news-bot
```

```bash
export DEPLOY_HOST=your.server.ip
export DEPLOY_USER=ubuntu
./deploy/deploy.sh
```

## Переменные окружения

| Переменная | Описание |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | токен от BotFather |
| `BOT_DB` | путь к SQLite |
| `DIGEST_LIMIT` | максимум новостей в одной сводке (по умолчанию 30) |
| `DEFAULT_LOOKBACK_HOURS` | окно для первого `/news` |
| `LOG_LEVEL` | `INFO` / `DEBUG` |
