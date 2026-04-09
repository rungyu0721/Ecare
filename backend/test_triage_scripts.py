import os
import unittest

os.environ["ECARE_SKIP_INIT_DB"] = "1"

from backend.main import (  # noqa: E402
    Extracted,
    enrich_extracted_details,
    merge_extracted,
    next_question,
)


class TriageScriptTests(unittest.TestCase):
    def test_enrich_extracted_details_keeps_third_party_medical_context(self):
        extracted = Extracted(category="醫療急症")

        enrich_extracted_details(extracted, "他意識清楚，可是一直說呼吸困難，而且有發燒")

        self.assertEqual(extracted.reporter_role, "代他人通報")
        self.assertTrue(extracted.conscious)
        self.assertTrue(extracted.breathing_difficulty)
        self.assertTrue(extracted.fever)
        self.assertIn("呼吸困難", extracted.symptom_summary)

    def test_merge_extracted_remembers_confirmed_medical_slots(self):
        base = Extracted(category="醫療急症", reporter_role="代他人通報", conscious=True)
        incoming = Extracted(category="醫療急症", breathing_difficulty=True, symptom_summary="呼吸困難")

        merged = merge_extracted(base, incoming)

        self.assertEqual(merged.reporter_role, "代他人通報")
        self.assertTrue(merged.conscious)
        self.assertTrue(merged.breathing_difficulty)
        self.assertEqual(merged.symptom_summary, "呼吸困難")

    def test_next_question_for_medical_uses_confirmed_slots(self):
        extracted = Extracted(
            category="醫療急症",
            location="內埔鄉中林村中林路13巷",
            reporter_role="代他人通報",
            conscious=True,
            breathing_difficulty=True,
            fever=True,
        )

        question = next_question(extracted, "High")

        self.assertIn("對方現在能正常說完整句子嗎", question)
        self.assertIn("立刻撥 119", question)

    def test_next_question_for_fire_uses_fire_script(self):
        extracted = Extracted(
            category="火災",
            location="內埔鄉中林村中林路13巷",
            danger_active=None,
        )

        question = next_question(extracted, "High")

        self.assertIn("火勢或濃煙", question)
        self.assertNotIn("呼吸困難", question)

    def test_next_question_for_violence_asks_weapon_first(self):
        extracted = Extracted(
            category="暴力事件",
            location="內埔鄉中林村中林路13巷",
            weapon=None,
        )

        question = next_question(extracted, "High")

        self.assertIn("持刀", question)


if __name__ == "__main__":
    unittest.main()
