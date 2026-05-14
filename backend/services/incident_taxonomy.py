"""Incident taxonomy helpers for E-CARE routing and advice."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


@lru_cache(maxsize=1)
def load_incident_taxonomy() -> dict[str, Any]:
    path = Path(__file__).parent.parent / "data" / "incident_taxonomy.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _is_negated_keyword(text: str, keyword: str) -> bool:
    if keyword not in {"受傷", "傷害", "流血", "武器", "刀", "槍", "持刀", "持槍"}:
        return False

    negations = ["沒有", "沒", "無", "未發現", "沒看到", "沒有看到"]
    for index in _keyword_indexes(text, keyword):
        prefix = text[max(0, index - 6):index]
        if any(neg in prefix for neg in negations):
            return True
    return False


def _keyword_indexes(text: str, keyword: str) -> list[int]:
    indexes: list[int] = []
    start = 0
    while True:
        index = text.find(keyword, start)
        if index == -1:
            return indexes
        indexes.append(index)
        start = index + len(keyword)


def match_incident_taxonomy(text: str) -> Optional[dict[str, Any]]:
    normalized = text or ""
    if not normalized.strip():
        return None

    best: Optional[dict[str, Any]] = None
    best_score = 0
    for group in load_incident_taxonomy().get("groups", []):
        for subtype in group.get("subtypes", []):
            matched_keywords = [
                keyword
                for keyword in subtype.get("keywords", [])
                if keyword and keyword in normalized and not _is_negated_keyword(normalized, keyword)
            ]
            if not matched_keywords:
                continue
            subtype_name = subtype.get("name")
            if subtype_name == "家庭暴力" and all(
                keyword in {"打罵", "摔東西"} for keyword in matched_keywords
            ):
                family_context = [
                    "家暴", "家庭", "小孩", "孩子", "兒童", "老人", "夫妻",
                    "爸爸", "媽媽", "父親", "母親", "兒子", "女兒", "哭叫",
                    "哀號", "求救", "受虐", "虐待",
                ]
                if not any(term in normalized for term in family_context):
                    continue
            if subtype_name == "病人安全事件" and any(
                keyword in {"跌倒", "墜床"} for keyword in matched_keywords
            ):
                medical_context = [
                    "醫院", "院內", "病房", "住院", "護理", "護士",
                    "醫師", "病人", "患者", "診所", "照護機構",
                ]
                if not any(term in normalized for term in medical_context):
                    continue
            score = max(len(keyword) for keyword in matched_keywords)
            if score <= best_score:
                continue
            best_score = score
            best = {
                "group_id": group.get("id"),
                "group_name": group.get("name"),
                "primary_agency": group.get("primary_agency"),
                "primary_contact": group.get("primary_contact"),
                "subtype": subtype.get("name"),
                "app_category": subtype.get("app_category"),
                "advice": subtype.get("advice"),
                "matched_keywords": matched_keywords,
            }
    return best


def taxonomy_prompt_summary() -> str:
    return """台灣事件分類與建議單位：
- 刑事案件：暴力、竊盜、毒品、家暴、性侵、特殊刑案優先 110；詐欺/網路詐騙提醒 165，若有人身危險再 110；家暴、兒少、性侵可提醒 113。
- 災害救護事件：火災、天然災害、緊急救護、交通事故、山域水域救援、危險物品事故優先 119；交通事故若需交通管制也可能需要 110。
- 醫療事件：若是立即生命危險或急症走 119；若是醫療疏失、病安、醫療糾紛，先確保病人安全並保存資料，洽院方、地方衛生局或申訴程序。
- 民事/社會事件：民事、家事、少年、行政爭議通常不是緊急報案；若無立即危險，建議保存證據並洽法院、調解、法律諮詢或相關行政機關。
分類時先判斷是否有「立即人身危險」。有立即危險時，安全與 110/119 優先；沒有立即危險時，給出保存證據與對應單位建議。"""
