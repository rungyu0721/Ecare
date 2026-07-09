"""Event state updates from the user's latest turn.

This module turns explicit follow-up updates into structured state changes on
`Extracted`, plus an acknowledgement/next question pair for the dialogue layer.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from backend.models import Extracted
from backend.services.dialogue import next_question
from backend.services.extraction import get_dispatch_advice


@dataclass
class EventUpdateResult:
    updated_slots: Dict[str, Optional[bool]]
    evidence: str
    reply: str
    next_question: str

    def as_response(self) -> tuple[str, str]:
        return self.reply, self.next_question


@lru_cache(maxsize=1)
def load_event_update_rules() -> Dict[str, Dict[str, list[str]]]:
    path = Path(__file__).parent.parent / "data" / "event_update_rules.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _terms(category: str, group: str) -> list[str]:
    rules = load_event_update_rules()
    return rules.get(category, {}).get(group, [])


def apply_event_update(
    ex: Extracted,
    latest_user_text: str,
    risk_level: str,
) -> Optional[EventUpdateResult]:
    """Apply explicit user updates to state, then acknowledge the new fact."""
    category = ex.category or ""
    text = latest_user_text.strip()
    if not category or category == "待確認" or not text:
        return None

    def has(group: str) -> bool:
        return any(term in text for term in _terms(category, group))

    def set_dispatch() -> None:
        existing = ex.dispatch_advice or ""
        updated = get_dispatch_advice(ex.category, ex.weapon, ex.people_injured)
        existing_has_route = "119" in existing or "110" in existing
        updated_has_route = "119" in updated or "110" in updated
        ex.dispatch_advice = existing if existing_has_route and not updated_has_route else updated

    def result(updated_slots: Dict[str, Optional[bool]], reply: str, next_q: str) -> EventUpdateResult:
        return EventUpdateResult(
            updated_slots={key: value for key, value in updated_slots.items() if value is not None},
            evidence=text,
            reply=reply,
            next_question=next_q,
        )

    if category == "受困救援":
        trapped = has("trapped")
        discomfort = has("discomfort")
        released = has("released")
        if trapped or discomfort or released:
            if released:
                ex.danger_active = False
                reply = "收到，已經脫困。接下來先確認每個人的身體狀況，並請管理員停用異常電梯。"
            else:
                if trapped:
                    ex.danger_active = True
                if discomfort:
                    ex.people_injured = True
                if trapped and discomfort:
                    reply = "收到，現在仍受困，而且有人不舒服，這需要優先讓消防或管理員定位處理。"
                elif discomfort:
                    reply = "收到，電梯內有人不舒服，我會把這視為需要優先協助的狀況。"
                else:
                    reply = "收到，現在仍受困。請不要強行開門或攀爬，保持通話等待協助。"
            set_dispatch()
            if released:
                return result(
                    {"danger_active": ex.danger_active},
                    reply,
                    "有人受傷、不舒服、喘不過氣，或需要救護車嗎？",
                )
            if ex.location:
                next_q = "請同步撥打 119 或通知管理員，並補充樓層、電梯編號、受困人數，以及不舒服的人目前症狀。"
            else:
                next_q = "請先提供地址、樓層、電梯編號或明顯地標，方便 119 或管理員定位。"
            return result(
                {
                    "danger_active": ex.danger_active if trapped else None,
                    "people_injured": ex.people_injured if discomfort else None,
                },
                reply,
                next_q,
            )

    if category == "火災":
        active_fire = has("active_fire")
        fire_out = has("fire_out")
        trapped_or_injured = has("trapped_or_injured")
        if active_fire or fire_out or trapped_or_injured:
            if active_fire:
                ex.danger_active = True
            if fire_out:
                ex.danger_active = False
            if trapped_or_injured:
                ex.people_injured = True
            set_dispatch()
            if trapped_or_injured:
                reply = "收到，火災現場有人受困或不適，這會優先需要消防與救護協助。"
            elif active_fire:
                reply = "收到，火勢或濃煙還在持續。請先離開火煙範圍，不要搭電梯。"
            else:
                reply = "收到，目前沒有明顯火勢或濃煙，仍請保持距離並讓消防或管理員確認。"
            return result(
                {
                    "danger_active": ex.danger_active if (active_fire or fire_out) else None,
                    "people_injured": ex.people_injured if trapped_or_injured else None,
                },
                reply,
                next_question(ex, risk_level),
            )

    if category in ["暴力事件", "可疑人士", "噪音"]:
        weapon = has("weapon")
        no_weapon = has("no_weapon")
        active = has("active")
        gone = has("gone")
        injured = has("injured")
        if weapon or no_weapon or active or gone or injured:
            if weapon:
                ex.weapon = True
            if no_weapon:
                ex.weapon = False
            if active:
                ex.danger_active = True
            if gone:
                ex.danger_active = False
            if injured:
                ex.people_injured = True
            set_dispatch()
            if weapon:
                reply = "收到，現場可能有武器，請先保持距離，不要靠近或介入。"
            elif injured:
                reply = "收到，現場有人受傷，我會把救護需求一起納入通報重點。"
            elif active:
                reply = "收到，危險或衝突仍在持續，請先移到安全位置。"
            elif gone:
                reply = "了解，對方或衝突看起來已經離開或停止，仍請先保持警覺。"
            else:
                reply = "了解，目前沒有看到武器，仍以保持距離和確認安全為主。"
            return result(
                {
                    "weapon": ex.weapon if (weapon or no_weapon) else None,
                    "danger_active": ex.danger_active if (active or gone) else None,
                    "people_injured": ex.people_injured if injured else None,
                },
                reply,
                next_question(ex, risk_level),
            )

    if category == "交通事故":
        injured = has("injured")
        blocking = has("blocking")
        safer = has("safer")
        if injured or blocking or safer:
            if injured:
                ex.people_injured = True
            if blocking:
                ex.danger_active = True
            if safer:
                ex.danger_active = False
            set_dispatch()
            if injured:
                reply = "收到，事故現場有人受傷或受困，會優先需要救護與警方協助。"
            elif blocking:
                reply = "收到，事故仍在車道或有二次事故風險，請先保持安全距離。"
            else:
                reply = "收到，已移到較安全的位置。接下來確認是否有人受傷或車輛漏油冒煙。"
            return result(
                {
                    "people_injured": ex.people_injured if injured else None,
                    "danger_active": ex.danger_active if (blocking or safer) else None,
                },
                reply,
                next_question(ex, risk_level),
            )

    if category == "天然災害":
        danger = has("danger")
        trapped_or_injured = has("trapped_or_injured")
        safe = has("safe")
        if danger or trapped_or_injured or safe:
            if danger:
                ex.danger_active = True
            if trapped_or_injured:
                ex.people_injured = True
            if safe and not danger:
                ex.danger_active = False
            set_dispatch()
            if trapped_or_injured:
                reply = "收到，災害現場有人受困或受傷，需要優先讓消防救災與救護定位。"
            elif danger:
                reply = "收到，災害危險仍可能持續。請先遠離倒塌、淹水、土石流或瓦斯味區域。"
            else:
                reply = "收到，你們已經到較安全的位置。接下來確認是否有人受困或受傷。"
            return result(
                {
                    "danger_active": ex.danger_active if (danger or safe) else None,
                    "people_injured": ex.people_injured if trapped_or_injured else None,
                },
                reply,
                next_question(ex, risk_level),
            )

    if category == "失蹤走失":
        still_missing = has("still_missing")
        found = has("found")
        high_risk = has("high_risk")
        if still_missing or found or high_risk:
            if still_missing:
                ex.danger_active = True
            if found:
                ex.danger_active = False
            if high_risk:
                ex.people_injured = True
            set_dispatch()
            if found:
                reply = "收到，人已經找到了。先確認他的身體狀況，並通知已協尋的人員停止擴散。"
            elif high_risk:
                reply = "收到，走失者屬於高風險對象，建議盡快通報警方並準備照片、穿著和最後位置。"
            else:
                reply = "收到，目前仍聯絡不上或找不到人，我會先幫你整理最後位置和特徵。"
            return result(
                {
                    "danger_active": ex.danger_active if (still_missing or found) else None,
                    "people_injured": ex.people_injured if high_risk else None,
                },
                reply,
                next_question(ex, risk_level),
            )

    if category == "自殺危機":
        active = has("active")
        injured = has("injured")
        safer = has("safer")
        if active or injured or safer:
            if active:
                ex.danger_active = True
            if injured:
                ex.people_injured = True
            if safer and not active:
                ex.danger_active = False
            set_dispatch()
            if injured:
                reply = "收到，對方可能已受傷或有用藥風險，請立刻同步 119 和 110。"
            elif active:
                reply = "收到，對方仍在危險位置或有危險物。請保持安全距離，不要拉扯或刺激對方。"
            else:
                reply = "收到，現場看起來已有人陪同或離開危險位置，請持續陪伴並等待專業人員。"
            return result(
                {
                    "danger_active": ex.danger_active if (active or safer) else None,
                    "people_injured": ex.people_injured if injured else None,
                },
                reply,
                next_question(ex, risk_level),
            )

    return None


def apply_event_update_response(
    ex: Extracted,
    latest_user_text: str,
    risk_level: str,
) -> Optional[tuple[str, str]]:
    update = apply_event_update(ex, latest_user_text, risk_level)
    return update.as_response() if update else None
