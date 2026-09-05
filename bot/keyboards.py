from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from bot.channel_presets import CHANNEL_PRESETS, RSS_PRESETS, ChannelPreset, RssPreset
from bot.models import Source

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
    "Пришлите источник:\n"
    "• @channel или https://t.me/channel\n"
    "• RSS: https://ahrefs.com/blog/feed/\n"
    "• несколько каналов/фидов через пробел/строки\n"
    "• ссылку папки https://t.me/addlist/… — затем список @каналов из папки "
    "(автоимпорт списка каналов Telegram не отдаёт)"
)

ONBOARD_PROMPT = (
    "Привет! Я собираю сводку из ваших Telegram-каналов и RSS-блогов без дублей.\n\n"
    "Пришлите 1–3 публичных канала (@name) или RSS-фид "
    "(https://site.com/feed/), и я сразу сделаю пробную сводку."
)


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    from bot.plans import is_monetization_enabled

    rows = [
        [BTN_NEWS, BTN_NEW_ONLY],
        [BTN_SOURCES, BTN_TOPICS],
    ]
    if is_monetization_enabled():
        rows.append([BTN_SCHEDULE, BTN_PLAN])
    else:
        rows.append([BTN_SCHEDULE])
    rows.append([BTN_MENU, BTN_HELP])
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
    )


def main_inline_keyboard() -> InlineKeyboardMarkup:
    from bot.plans import is_monetization_enabled

    rows = [
        [InlineKeyboardButton("Сводка новостей", callback_data="m:news")],
        [
            InlineKeyboardButton("Источники", callback_data="m:sources"),
            InlineKeyboardButton("Темы", callback_data="m:topics"),
        ],
    ]
    if is_monetization_enabled():
        rows.append(
            [
                InlineKeyboardButton("Расписание", callback_data="m:schedule"),
                InlineKeyboardButton("Подписка", callback_data="m:plan"),
            ]
        )
    else:
        rows.append(
            [InlineKeyboardButton("Расписание", callback_data="m:schedule")]
        )
    rows.append([InlineKeyboardButton("Помощь", callback_data="m:help")])
    return InlineKeyboardMarkup(rows)


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
    from bot.plans import is_monetization_enabled

    if not is_monetization_enabled():
        return back_home_keyboard()
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
    rows.append(
        [InlineKeyboardButton("Добавить источник", callback_data="m:src_add")]
    )
    rows.append(
        [InlineKeyboardButton("Готовые наборы", callback_data="m:src_presets")]
    )
    rows.append([InlineKeyboardButton("« Меню", callback_data="m:home")])
    return InlineKeyboardMarkup(rows)


def channel_presets_keyboard(
    presets: tuple[ChannelPreset, ...] = CHANNEL_PRESETS,
    rss_presets: tuple[RssPreset, ...] = RSS_PRESETS,
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
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    f"{preset.title} ({preset.count})",
                    callback_data=f"m:src_preset:{preset.slug}",
                )
            ]
            for preset in rss_presets
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
