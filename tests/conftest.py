from __future__ import annotations

import pytest

from bot.plans import set_monetization_enabled


@pytest.fixture(autouse=True)
def _enable_monetization_for_tests():
    """Plan/limit tests assume monetization is on; product default is off."""
    set_monetization_enabled(True)
    yield
    set_monetization_enabled(False)
