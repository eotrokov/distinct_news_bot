# Distinct News Bot

Telegram-бот для **SEO-дайджеста из публичных Telegram-каналов**:
собирает посты, убирает рекламу и дубли, раскладывает по темам и отдаёт подробную выжимку.

- Период: `/news` (по умолчанию 3 дня) или `/news 5`
- Подробная выжимка: несколько предложений на новость (rule-based + опционально Gemini AI)
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

## AI-сводки (Google Gemini, бесплатно)

1. Получите API key на [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
2. Добавьте в `.env`:

   ```
   AI_SUMMARY_ENABLED=1
   AI_PROVIDER=gemini
   GEMINI_API_KEY=...
   ```

3. Без ключа бот работает как раньше — rule-based сводка остаётся fallback.

Альтернатива: `AI_PROVIDER=groq` + `GROQ_API_KEY` (если Groq доступен у вас).

AI вызывается только для финальных пунктов дайджеста (до `DIGEST_LIMIT`), не для каждого сырого поста.

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
| `AI_SUMMARY_ENABLED` | включить AI-сводку (0/1) | 1 |
| `AI_PROVIDER` | провайдер AI (`gemini` / `groq`) | `gemini` |
| `GEMINI_API_KEY` | ключ Google Gemini | — |
| `GROQ_API_KEY` | ключ Groq (если `AI_PROVIDER=groq`) | — |
| `AI_MODEL` | модель | `gemini-2.0-flash` |
| `AI_MAX_CONCURRENT` | параллельных AI-запросов | 4 |
| `AI_TIMEOUT_SECONDS` | таймаут AI-запроса | 15 |
| `LOG_LEVEL` | `INFO` / `DEBUG` | `INFO` |
