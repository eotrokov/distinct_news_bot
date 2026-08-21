# Distinct News Bot

Telegram-бот для **SEO-дайджеста из публичных Telegram-каналов**:
собирает посты, убирает рекламу и дубли, раскладывает по темам и отдаёт одну выжимку.

- Период: `/news` (по умолчанию 3 дня) или `/news 5`
- Пагинация: больше 10 пунктов — стрелки ◀ ▶ в одном сообщении
- Фильтры: ✅ показывать / 🚫 скрывать
- Лимит: 20 каналов бесплатно, дальше 10⭐ / канал / 30 дней

Пока в меню и командах доступны **только Telegram-каналы**.

## Команды

- `/news [дни]` — выжимка
- `/add @channel` — добавить публичный канал
- `/sources`, `/remove <id>`
- `/topic + seo` — белый список (показывать)
- `/topic - крипта` — чёрный список (скрывать)
- `/topic del …`, `/topics`, `/topic clear`
- `/menu`, `/help`, `/cancel`

## Локальный запуск

```bash
cp .env.example .env
# TELEGRAM_BOT_TOKEN=...

python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
python -m bot
pytest -q
```

## Docker / деплой

```bash
cp .env.example .env
docker compose up -d --build
```

На VPS:

```bash
export DEPLOY_HOST=your.server.ip
export DEPLOY_USER=root
./deploy/deploy.sh
```

## Переменные окружения

| Переменная | Описание | По умолчанию |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | токен BotFather | — |
| `BOT_DB` | SQLite путь | `data/bot.sqlite3` |
| `DIGEST_LIMIT` | макс. новостей в выжимке | 30 |
| `DIGEST_PAGE_SIZE` | новостей на страницу | 10 |
| `DEFAULT_DIGEST_DAYS` | период по умолчанию | 3 |
| `FREE_SOURCE_LIMIT` | бесплатных каналов | 20 |
| `STARS_PER_EXTRA_SOURCE` | ⭐ за доп. слот | 10 |
| `PAID_SLOT_DAYS` | срок слота | 30 |
| `LOG_LEVEL` | `INFO` / `DEBUG` | `INFO` |
