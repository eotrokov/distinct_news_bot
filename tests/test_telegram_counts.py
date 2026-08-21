from __future__ import annotations

from bot.fetchers.telegram import parse_count


def test_parse_count_abbreviations():
    assert parse_count("824") == 824
    assert parse_count("7.03K") == 7030
    assert parse_count("12.5M") == 12_500_000
    assert parse_count("1B") == 1_000_000_000
    assert parse_count("") == 0
    assert parse_count(None) == 0
