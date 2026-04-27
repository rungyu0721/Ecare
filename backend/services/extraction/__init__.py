"""
事件抽取套件：重新匯出所有公開符號，保持 `from backend.services.extraction import X` 向下相容。
"""

from .classify import (  # noqa: F401
    CATEGORY_NORMALIZATION_MAP,
    CATEGORY_QUESTION_KEYWORDS,
    DANGER_QUESTION_KEYWORDS,
    INJURY_QUESTION_KEYWORDS,
    LOCATION_QUESTION_KEYWORDS,
    WEAPON_QUESTION_KEYWORDS,
    asks_about_category,
    asks_about_danger,
    asks_about_injury,
    asks_about_location,
    asks_about_weapon,
    build_incident_acknowledgement,
    get_dispatch_advice,
    normalize_category_name,
    should_ask_scene_danger,
)
from .entities import (  # noqa: F401
    apply_turn_context,
    build_medical_acknowledgement,
    collect_symptoms,
    enrich_extracted_details,
    extract_conversation_state,
    generate_incident_summary,
    infer_reporter_role,
    is_likely_incident_detail,
    medical_follow_up_question,
    merge_extracted,
    merge_symptom_summary,
    simple_extract,
    subject_possessive_reference,
    subject_reference,
)
from .location import (  # noqa: F401
    LANDMARK_HINT_TOKENS,
    LOCATION_HINT_TOKENS,
    VAGUE_LOCATION_PHRASES,
    extract_location_from_text,
    get_client_location_text,
    has_strong_location_signal,
    is_likely_location_response,
    location_quality_score,
    normalize_location_candidate,
)
