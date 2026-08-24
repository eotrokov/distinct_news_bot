from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from bot.models import Feedback, Source

BTN_NEWS = "Сводка"
BTN_SOURCES = "Источники"
BTN_TOPICS = "Темы"
BTN_MENU = "Меню"
BTN_HELP = "Помощь"
BTN_RESET = "Сброс курсора"
BTN_FEEDBACK = "Обратная связь"

REPLY_BUTTONS = {BTN_NEWS, BTN_SOURCES, BTN_TOPICS, BTN_MENU, BTN_HELP, BTN_RESET, BTN_FEEDBACK}


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [BTN_NEWS, BTN_SOURCES],
            [BTN_TOPICS, BTN_FEEDBACK],
            [BTN_MENU, BTN_HELP],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def main_inline_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("Сводка новостей", callback_data="m:news")],
        [
            InlineKeyboardButton("Источники", callback_data="m:sources"),
            InlineKeyboardButton("Темы", callback_data="m:topics"),
        ],
        [InlineKeyboardButton("Обратная связь", callback_data="m:feedback")],
        [
            InlineKeyboardButton("Сброс курсора", callback_data="m:reset"),
            InlineKeyboardButton("Помощь", callback_data="m:help"),
        ],
    ]
    if is_admin:
        rows.append(
            [InlineKeyboardButton("⚙ Админ-панель", callback_data="m:admin")]
        )
    return InlineKeyboardMarkup(rows)


def sources_keyboard(sources: list[Source]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for source in sources:
        label = f"Удалить #{source.id} {source.source_type}:{source.title}"[:60]
        rows.append(
            [InlineKeyboardButton(label, callback_data=f"m:src_del:{source.id}")]
        )
    rows.append(
        [InlineKeyboardButton("Добавить источник", callback_data="m:src_add")]
    )
    rows.append([InlineKeyboardButton("« Меню", callback_data="m:home")])
    return InlineKeyboardMarkup(rows)


def source_type_keyboard() -> InlineKeyboardMarkup:
    types = [
        ("Telegram", "telegram"),
        ("РИА", "ria"),
        ("RSS", "rss"),
        ("Facebook", "facebook"),
        ("Twitter/X", "twitter"),
    ]
    rows = [
        [InlineKeyboardButton(label, callback_data=f"m:src_type:{stype}")]
        for label, stype in types
    ]
    rows.append([InlineKeyboardButton("« К источникам", callback_data="m:sources")])
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


def admin_panel_keyboard(new_count: int = 0) -> InlineKeyboardMarkup:
    new_label = f"Новые ({new_count})" if new_count else "Новые"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(new_label, callback_data="m:adm_list:new")],
            [InlineKeyboardButton("Рассмотренные", callback_data="m:adm_list:reviewed")],
            [InlineKeyboardButton("Выполненные", callback_data="m:adm_list:done")],
            [InlineKeyboardButton("Все заявки", callback_data="m:adm_list:all")],
            [InlineKeyboardButton("« Меню", callback_data="m:home")],
        ]
    )


def feedback_list_keyboard(
    items: list[Feedback], status_filter: str
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for fb in items[:20]:
        label = f"#{fb.id} [{fb.status}] {fb.text[:40]}"
        rows.append(
            [InlineKeyboardButton(label, callback_data=f"m:adm_view:{fb.id}")]
        )
    rows.append(
        [InlineKeyboardButton("« Админ-панель", callback_data="m:admin")]
    )
    return InlineKeyboardMarkup(rows)


def feedback_detail_keyboard(fb: Feedback) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if fb.status != "reviewed":
        rows.append(
            [InlineKeyboardButton("Отметить: рассмотрено", callback_data=f"m:adm_status:{fb.id}:reviewed")]
        )
    if fb.status != "done":
        rows.append(
            [InlineKeyboardButton("Отметить: выполнено", callback_data=f"m:adm_status:{fb.id}:done")]
        )
    if fb.status != "new":
        rows.append(
            [InlineKeyboardButton("Вернуть в новые", callback_data=f"m:adm_status:{fb.id}:new")]
        )
    rows.append(
        [InlineKeyboardButton("« К списку", callback_data="m:adm_list:all")]
    )
    return InlineKeyboardMarkup(rows)


SOURCE_PROMPTS = {
    "telegram": (
        "Пришлите публичный канал:\n"
        "• @channel или https://t.me/channel\n"
        "• несколько каналов через пробел/строки\n"
        "• ссылку папки https://t.me/addlist/… "
        "(затем список @каналов из папки)"
    ),
    "ria": "Пришлите ленту РИА: main / politics / world / … или URL RSS",
    "rss": "Пришлите URL RSS/Atom ленты",
    "facebook": "Пришлите имя страницы Facebook, URL страницы или URL RSS",
    "twitter": "Пришлите @user, URL профиля X/Twitter или URL RSS",
}
