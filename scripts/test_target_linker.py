from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import target_linker


def write_json(root: Path, name: str, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


class TargetLinkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        locks = {key: False for key in target_linker.LOCKS}
        target = {"target_id": "TGT-MATH-K-0001", "subject": "数学", "canonical_name": "合成目标"}
        write_json(self.root, "release/targets.json", {"targets": [target], **locks})
        record = {"record_id": "BJ-GK-2026-MATH-Q01", "subject": "数学", "year": 2026,
                  "source_pdf": "合成/题.pdf", "question_pages": [1],
                  "target_occurrences": [{"target_id": target["target_id"], "source_label_id": "L1"}]}
        write_json(self.root, "release/record-target-map.json", {"records": [record], **locks})
        write_json(self.root, "release/known-risks.json", {"items": [], **locks})
        evidence = {"subject": "数学", **locks, "evidence": [{
            "evidence_id": "E1", "event_id": "EVENT1", "source_file": "合成/原图.jpg",
            "source_location": "合成第1题", "evidence_type": "written_response",
            "independence": "independent", "observed_fact": "仅用于程序测试",
            "learning_judgement": "candidate_observation",
            "candidate_targets": [{"target_id": target["target_id"], "mapping_role": "primary_focus",
                                   "mapping_reason": "合成判据"}]}]}
        path = write_json(self.root, "input/evidence.json", evidence)
        (self.root / "input/review.md").write_text("TEST_SIGNATURE", encoding="utf-8")
        self.manifest = write_json(self.root, "input/manifest.json", {"sources": [{
            "evidence_path": "input/evidence.json", "review_path": "input/review.md",
            "signature": "TEST_SIGNATURE", "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]})

    def tearDown(self):
        self.temp.cleanup()

    def run_build(self):
        return target_linker.build(self.root, self.root / "release", self.manifest, self.root / "out")

    def test_build_reuses_records_and_keeps_locks(self):
        report = self.run_build()
        self.assertEqual(report["mapping_count"], 1)
        self.assertEqual(report["question_record_count"], 1)
        self.assertFalse(report["image_or_pdf_read"])
        output = json.loads((self.root / "out/target-question-candidates.json").read_text(encoding="utf-8"))
        self.assertFalse(output["targets"][0]["records"][0]["student_use_allowed"])
        self.assertFalse((self.root / "合成/题.pdf").exists())

    def test_tampered_source_is_rejected(self):
        path = self.root / "input/evidence.json"
        path.write_text(path.read_text(encoding="utf-8").replace("仅用于程序测试", "已被改变"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "指纹"):
            self.run_build()

    def test_unlocked_input_is_rejected(self):
        path = self.root / "release/targets.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["student_release"] = True
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "student_release"):
            self.run_build()

    def test_inventory_separates_week_and_aggregate(self):
        week = self.root / "周复盘/高二上/2026-10-19_至_2026-10-25"
        week.mkdir(parents=True)
        (week / "资料与知识点覆盖核对.md").write_text("合成旧报告", encoding="utf-8")
        month = self.root / "周复盘/高二上/2026-10月复盘"
        month.mkdir(parents=True)
        (month / "月复盘.md").write_text("合成汇总", encoding="utf-8")
        report = target_linker.inventory(self.root, [self.root / "周复盘/高二上"], self.root / "out")
        self.assertEqual(report["natural_week_count"], 1)
        self.assertEqual(report["aggregate_review_count"], 1)
        self.assertEqual(report["status"], "INVENTORY_ONLY_NOT_MAPPING_COMPLETED")


if __name__ == "__main__":
    unittest.main()
