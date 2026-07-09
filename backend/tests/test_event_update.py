"""Event update extraction tests."""

from backend.models import Extracted
from backend.services.event_update import apply_event_update


def test_event_update_returns_structured_trapped_result():
    ex = Extracted(category="受困救援", location="台北市信義區市府路1號")

    update = apply_event_update(ex, "仍受困，有人不舒服", "High")

    assert update is not None
    assert update.evidence == "仍受困，有人不舒服"
    assert update.updated_slots == {
        "danger_active": True,
        "people_injured": True,
    }
    assert ex.danger_active is True
    assert ex.people_injured is True
    assert "仍受困" in update.reply
    assert "樓層" in update.next_question


def test_event_update_preserves_existing_119_route_when_fallback_is_coarser():
    ex = Extracted(
        category="天然災害",
        dispatch_advice="建議通報：119 或地方災害應變單位",
    )

    update = apply_event_update(ex, "有人被壓住受困", "High")

    assert update is not None
    assert update.updated_slots == {"people_injured": True}
    assert ex.people_injured is True
    assert ex.dispatch_advice == "建議通報：119 或地方災害應變單位"


def test_event_update_returns_none_for_unmatched_detail():
    ex = Extracted(category="火災")

    update = apply_event_update(ex, "我先看一下", "Medium")

    assert update is None
