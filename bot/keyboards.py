from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from bot.channel_presets import CHANNEL_PRESETS, ChannelPreset
from bot.models import Source
from bot.rss_presets import SEO_RSS_FEEDS

# Reply keyboard labels (must match handlers)
BTN_NEWS = "Сводка"
BTN_NEW_ONLY = "Только новое"
BTN_SOURCES = "Источники"
BTN_TOPICS = "Темы"
BTN_SCHEDULE = "Расписание"
BTN_PLAN = "Подписка"
BTN_MENU = "Меню"
BTN_HELP = "Помощь"

REPLY_BUTTONS = {
    BTN_NEWS,
    BTN_NEW_ONLY,
    BTN_SOURCES,
    BTN_TOPICS,
    BTN_SCHEDULE,
    BTN_PLAN,
    BTN_MENU,
    BTN_HELP,
}

TELEGRAM_SOURCE_PROMPT = (
    "Пришлите публичный канал или RSS-ленту:\n"
    "• @channel или https://t.me/channel\n"
    "• несколько каналов через пробел/строки\n"
    "• RSS: https://site.com/feed/ или /add rss https://site.com/feed/ Название\n"
    "• ссылку папки https://t.me/addlist/… — затем список @каналов из папки "
    "(автоимпорт списка каналов Telegram не отдаёт)"
)

ONBOARD_PROMPT = (
    "Привет! Я собираю сводку из ваших Telegram-каналов и RSS-лент без дублей.\n\n"
    "Пришлите 1–3 публичных канала (@name) или RSS URL, "
    "и я сразу сделаю пробную сводку."
)


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [BTN_NEWS, BTN_NEW_ONLY],
            [BTN_SOURCES, BTN_TOPICS],
            [BTN_SCHEDULE, BTN_PLAN],
            [BTN_MENU, BTN_HELP],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def main_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Сводка новостей", callback_data="m:news")],
            [
                InlineKeyboardButton("Источники", callback_data="m:sources"),
                InlineKeyboardButton("Темы", callback_data="m:topics"),
            ],
            [
                InlineKeyboardButton("Расписание", callback_data="m:schedule"),
                InlineKeyboardButton("Подписка", callback_data="m:plan"),
            ],
            [InlineKeyboardButton("Помощь", callback_data="m:help")],
        ]
    )


def digest_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔥 Главное за период", callback_data="m:news:top"
                )
            ],
            [
                InlineKeyboardButton(
                    "🆕 Только новое", callback_data="m:news:new"
                )
            ],
            [InlineKeyboardButton("« Меню", callback_data="m:home")],
        ]
    )


def schedule_keyboard(*, enabled: bool) -> InlineKeyboardMarkup:
    toggle = (
        InlineKeyboardButton("Выключить", callback_data="m:sched:off")
        if enabled
        else InlineKeyboardButton("Включить (09:55)", callback_data="m:sched:on")
    )
    return InlineKeyboardMarkup(
        [
            [toggle],
            [
                InlineKeyboardButton("08:00", callback_data="m:sched:t:8:0"),
                InlineKeyboardButton("09:00", callback_data="m:sched:t:9:0"),
                InlineKeyboardButton("09:55", callback_data="m:sched:t:9:55"),
            ],
            [
                InlineKeyboardButton("10:00", callback_data="m:sched:t:10:0"),
                InlineKeyboardButton("12:00", callback_data="m:sched:t:12:0"),
                InlineKeyboardButton("18:00", callback_data="m:sched:t:18:0"),
            ],
            [
                InlineKeyboardButton("UTC+3", callback_data="m:sched:tz:180"),
                InlineKeyboardButton("UTC+0", callback_data="m:sched:tz:0"),
            ],
            [InlineKeyboardButton("« Меню", callback_data="m:home")],
        ]
    )


def plan_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Купить Pro ⭐", callback_data="m:buy:pro")],
            [InlineKeyboardButton("Купить Plus ⭐", callback_data="m:buy:plus")],
            [InlineKeyboardButton("« Меню", callback_data="m:home")],
        ]
    )


def sources_keyboard(sources: list[Source]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for source in sources:
        label = f"Удалить #{source.id} {source.title}"[:60]
        rows.append(
            [InlineKeyboardButton(label, callback_data=f"m:src_del:{source.id}")]
        )
    rows.append([InlineKeyboardButton("Добавить источник", callback_data="m:src_add")])
    rows.append(
        [InlineKeyboardButton("Готовые наборы", callback_data="m:src_presets")]
    )
    rows.append([InlineKeyboardButton("« Меню", callback_data="m:home")])
    return InlineKeyboardMarkup(rows)


def channel_presets_keyboard(
    presets: tuple[ChannelPreset, ...] = CHANNEL_PRESETS,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{preset.title} ({preset.count})",
                callback_data=f"m:src_preset:{preset.slug}",
            )
        ]
        for preset in presets
    ]
    rows.append(
        [
            InlineKeyboardButton(
                f"SEO RSS новости ({len(SEO_RSS_FEEDS)})",
                callback_data="m:src_rss_preset:seo-news",
            )
        ]
    )
    rows.append([InlineKeyboardButton("« Источники", callback_data="m:sources")])
    return InlineKeyboardMarkup(rows)


def topics_keyboard(topic_rows: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for topic_id, topic in topic_rows:
        label = f"Удалить: {topic}"[:60]
        rows.append(
            [InlineKeyboardButton(label, callback_data=f"m:topic_del:{topic_id}")]
        )
    rows.append(
        [InlineKeyboardButton("Добавить тему", callback_data="m:topic_add")]
    )
    if topic_rows:
        rows.append(
            [InlineKeyboardButton("Очистить все темы", callback_data="m:topic_clear")]
        )
    rows.append([InlineKeyboardButton("« Меню", callback_data="m:home")])
    return InlineKeyboardMarkup(rows)


def back_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("« Меню", callback_data="m:home")]]
    )


def digest_page_keyboard(page: int, total: int) -> InlineKeyboardMarkup:
    """Inline pager for digest pages (0-based page index)."""
    total = max(1, total)
    page = max(0, min(page, total - 1))
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(InlineKeyboardButton("◀", callback_data=f"m:dg:{page - 1}"))
    row.append(
        InlineKeyboardButton(f"{page + 1}/{total}", callback_data="m:dg:noop")
    )
    if page < total - 1:
        row.append(InlineKeyboardButton("▶", callback_data=f"m:dg:{page + 1}"))
    rows = [row, [InlineKeyboardButton("« Меню", callback_data="m:home")]]
    return InlineKeyboardMarkup(rows)
