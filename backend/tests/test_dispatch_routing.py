"""110/119 分流規則測試。"""

import pytest

from backend.services.extraction.classify import get_dispatch_advice
from backend.services.extraction.entities import simple_extract


@pytest.mark.parametrize(
    ("category", "people_injured", "expected_terms"),
    [
        ("自殺危機", None, ["救護車", "警察"]),
        ("失蹤走失", None, ["警察", "119"]),
        ("受困救援", None, ["消防救援"]),
        ("天然災害", True, ["消防救災", "救護車"]),
        ("山域水域救援", None, ["消防救援"]),
    ],
)
def test_dispatch_advice_routes_emergency_categories(category, people_injured, expected_terms):
    advice = get_dispatch_advice(category, weapon=None, people_injured=people_injured)

    for term in expected_terms:
        assert term in advice


@pytest.mark.parametrize(
    ("text", "expected_category", "expected_terms"),
    [
        ("有人在頂樓說要跳樓", "自殺危機", ["119", "110"]),
        ("阿嬤在市場附近走失找不到人", "失蹤走失", ["110", "119"]),
        ("朋友在山區走失，手機快沒電也沒訊號", "山域水域救援", ["119"]),
        ("我們困在電梯裡門打不開", "受困救援", ["119"]),
        ("地震後大樓倒塌有人被壓住", "天然災害", ["119"]),
    ],
)
def test_simple_extract_routes_real_world_emergency_text(text, expected_category, expected_terms):
    extracted = simple_extract(text)

    assert extracted.category == expected_category
    assert extracted.dispatch_advice
    for term in expected_terms:
        assert term in extracted.dispatch_advice
