from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from bot.models import Source

# Reply keyboard labels (must match handlers)
BTN_NEWS = "Выжимка"
BTN_SOURCES = "Каналы"
BTN_TOPICS = "Темы"
BTN_MENU = "Меню"
BTN_HELP = "Помощь"
BTN_RESET = "Сброс меток"

REPLY_BUTTONS = {BTN_NEWS, BTN_SOURCES, BTN_TOPICS, BTN_MENU, BTN_HELP, BTN_RESET}


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [BTN_NEWS, BTN_SOURCES],
            [BTN_TOPICS, BTN_MENU],
            [BTN_HELP, BTN_RESET],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def main_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Выжимка постов", callback_data="m:news")],
            [
                InlineKeyboardButton("Каналы", callback_data="m:sources"),
                InlineKeyboardButton("Темы", callback_data="m:topics"),
            ],
            [
                InlineKeyboardButton("Сброс меток", callback_data="m:reset"),
                InlineKeyboardButton("Помощь", callback_data="m:help"),
            ],
        ]
    )


def sources_keyboard(
    sources: list[Source],
    *,
    show_buy_slot: bool = False,
    stars: int = 10,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for source in sources:
        label = f"Удалить #{source.id} {source.title}"[:60]
        rows.append(
            [InlineKeyboardButton(label, callback_data=f"m:src_del:{source.id}")]
        )
    rows.append(
        [InlineKeyboardButton("Добавить канал", callback_data="m:src_add")]
    )
    if show_buy_slot:
        rows.append(
            [
                InlineKeyboardButton(
                    f"Купить слот ({stars}⭐ / мес.)",
                    callback_data="m:buy_slot",
                )
            ]
        )
    rows.append([InlineKeyboardButton("« Меню", callback_data="m:home")])
    return InlineKeyboardMarkup(rows)


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


def source_type_keyboard() -> InlineKeyboardMarkup:
    """Kept for compatibility; UI now adds Telegram channels directly."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Telegram-канал", callback_data="m:src_type:telegram"
                )
            ],
            [InlineKeyboardButton("« К каналам", callback_data="m:sources")],
        ]
    )


def topics_keyboard(
    topic_rows: list[tuple[int, str, str]],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for topic_id, topic, kind in topic_rows:
        mark = "✅" if kind == "include" else "🚫"
        label = f"{mark} Удалить: {topic}"[:60]
        rows.append(
            [InlineKeyboardButton(label, callback_data=f"m:topic_del:{topic_id}")]
        )
    rows.append(
        [
            InlineKeyboardButton("✅ Показывать", callback_data="m:topic_add:include"),
            InlineKeyboardButton("🚫 Скрывать", callback_data="m:topic_add:exclude"),
        ]
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


SOURCE_PROMPTS = {
    "telegram": "Пришлите публичный Telegram-канал: @channel или https://t.me/channel",
}
