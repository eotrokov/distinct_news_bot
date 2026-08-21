# Distinct News Bot

Telegram-бот для **SEO-дайджеста из публичных Telegram-каналов**:
собирает посты, убирает рекламу и дубли, раскладывает по темам и отдаёт подробную выжимку.

- Период: `/news` (по умолчанию 3 дня) или `/news 5`
- Подробная выжимка: несколько предложений на новость
- Топ недели: `/weekly` — главные посты за 7 дней по реакциям (авто-рассылка раз в неделю)
- Массовое добавление: `/add @a @b @c` (запятые / новые строки)
- Пагинация: больше 10 пунктов — стрелки ◀ ▶ в одном сообщении
- Фильтры: ✅ показывать / 🚫 скрывать
- Лимит: 20 каналов бесплатно, дальше 10⭐ / канал / 30 дней

Пока в меню и командах доступны **только Telegram-каналы**.

## Команды

- `/news [дни]` — выжимка
- `/weekly` — топ за 7 дней по реакциям
- `/weekly on|off` — авто-рассылка топа раз в неделю
- `/add @a @b @c` — добавить каналы пачкой
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
| `SUMMARY_MAX_SENTENCES` | предложений в выжимке на новость | 3 |
| `WEEKLY_TOP_LIMIT` | пунктов в топе недели | 10 |
| `WEEKLY_DIGEST_HOUR_UTC` | час авто-топа (UTC) | 9 |
| `WEEKLY_DIGEST_WEEKDAY` | день недели авто-топа (0=пн … 6=вс) | 0 |
| `LOG_LEVEL` | `INFO` / `DEBUG` | `INFO` |
