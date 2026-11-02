"""Behavioural regression cases. All sources and outputs are synthetic fixtures."""
from __future__ import annotations

import copy
import os
import shutil
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import fitz

import learning_run as workflow
import install_local_skill as installer
import process_inbox as inbox_workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.parent = Path(os.environ.get("XUELEMA_TEST_ROOT", tempfile.gettempdir())).resolve()
        self.parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="xuelema-check-", dir=self.parent)
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(self.parent) and self.root != self.parent)

    def tearDown(self):
        # Verify the absolute cleanup boundary before TemporaryDirectory removes it.
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(self.parent))
        self.assertNotEqual(Path(self.temp.name).resolve(), self.parent)
        self.temp.cleanup()

    def write(self, path, text):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def docx(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>')
            z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')

    def prepare(self, mode="notes", subjects=None, config_version=None, followup=False):
        subjects = subjects or ["数学"]
        self.write("学习总索引.md", "# 测试资料库\n只用于程序回归测试，不是真实孩子资料。")
        scope = {"mode": mode, "request": "隔离夹具：按所选科目完成本次任务。", "subjects": subjects,
                 "source_roots": ["输入"], "index_paths": [f"{s}/{s}索引.md" for s in subjects],
                 "time_budget_minutes": 25, "core_subject_limit": 2,
                 "period": {"start": "2026-09-07", "end": "2026-09-13", "as_of": "2026-09-12"}}
        if mode == "inbox":
            scope["material_kinds"] = ["notes"]
        if mode == "review":
            scope["period"]["as_of"] = "2026-09-14"
        if followup:
            scope["followup"] = True
        for raw in workflow.rule_paths(self.root, mode, scope):
            self.write(raw, "# 测试规范\n测试检查规则指纹和真实产物对应，不证明学科审核正确。")
        for path in workflow.contract()["modes"][mode]["updates"] + scope["index_paths"]:
            self.write(path, "# 原有记录\n原状态保持，所有证据来自测试夹具。")
        if config_version is not None:
            self.write("长期记忆/学了么配置.json", f"{{\"expected_skill_version\":\"{config_version}\"}}")
        for i, subject in enumerate(subjects):
            self.write(f"输入/{i}.txt", f"合成资料：{subject}的课堂提问；没有独立作答结果。")
        run = workflow.start(self.root, scope)
        workflow.read_rules(run)
        m = workflow.read_json(run / "run.json")
        if mode == "inbox":
            m["artifacts"] += [{"id": f"N{i}", "role": role, "subject": subjects[0], "path": "", "destination": ""}
                               for i, role in enumerate(workflow.contract()["input_roles"]["notes"])]
        for artifact in m["artifacts"]:
            suffix = artifact["role"].rsplit("_", 1)[-1]
            path = run / "staged" / (artifact["id"] + "." + suffix)
            text = "请独立说清概念适用的条件。以下材料仅用于程序测试。"
            if artifact["role"].startswith("answer_"):
                text = "标准答案：说明对象、条件和结论。本文件用于测试，不能给真实学生使用。"
            if suffix == "docx":
                self.docx(path, text)
            else:
                path.write_text(text, encoding="utf-8")
            artifact["path"] = workflow.relative(self.root, path)
            artifact["destination"] = "周复盘/测试/" + path.name
        for i, item in enumerate(m["inputs"]):
            subject = subjects[i]
            item.update(subject=subject, kind="notes", status="processed", event_id=f"E{i + 1}",
                        artifact_ids=[a["id"] for a in m["artifacts"] if not a["subject"] or a["subject"] == subject],
                        topics=[{"name": "概念条件", "treatment": "focus"}])
            if mode == "review":
                item["deep_review"] = {
                    "status": "completed",
                    "source_stage": "triage",
                    "work": "逐项核对原始资料并完成知识点归纳、证据记录。",
                    "evidence_locators": ["原材料第1行"],
                    "artifact_ids": item["artifact_ids"],
                }
            m["findings"].append({"id": f"F{i + 1}", "subject": subject, "topic": "概念条件", "state": "待观察", "priority": "P1",
                                  "evidence": [{"input_id": item["id"], "locator": "原材料第1行", "observation": "可见课堂提问，无独立作答证据"}],
                                  "next_check": "另找适配原题，检查能否独立说明条件", "attempts": []})
        for i, update in enumerate(m["updates"]):
            staged = run / "staged" / (f"memory-{i}.md")
            current = self.root / update["path"]
            current.parent.mkdir(parents=True, exist_ok=True)
            base = current.read_text(encoding="utf-8") if current.exists() else "# 原有记录\n暂无既有记录。"
            staged.write_text(base + "\n新增课堂接触记录，掌握状态仍待观察。", encoding="utf-8")
            update.update(decision="update", staged_path=workflow.relative(self.root, staged), reason="增加来源与待验证目标，不宣称掌握。")
        if mode in {"practice", "weekly", "exam"}:
            for i, subject in enumerate(subjects):
                source = self.write(f"测试题库/{subject}-原题.txt", "合成原题：说明给定定义的适用对象和条件。非真实考试题。")
                answer = self.write(f"测试题库/{subject}-答案.txt", "合成题配套答案：分别说明对象与条件。非真实考试答案。")
                sid = next(a["id"] for a in m["artifacts"] if a["role"] == "student_docx" and a["subject"] == subject)
                aid = next(a["id"] for a in m["artifacts"] if a["role"] == "answer_docx" and a["subject"] == subject)
                m["practice"].append({"id": f"Q{i + 1}", "subject": subject, "topic": "概念条件", "finding_ids": [f"F{i + 1}"],
                                      "source_type": "original", "source_category": "beijing_gaokao", "learning_level": "learned", "prerequisite_evidence": [m["inputs"][i]["id"]],
                                      "source": {"path": workflow.relative(self.root, source), "sha256": workflow.sha256(source), "citation": "合成北京高考夹具第1题", "locator": "第1行"},
                                      "answer_source": {"path": workflow.relative(self.root, answer), "sha256": workflow.sha256(answer), "citation": "合成夹具配套答案", "locator": "第1行"},
                                      "figure_required": False, "figure_paths": [], "student_artifact_id": sid, "answer_artifact_id": aid,
                                      "minutes": 8, "required": True})
            m["activities"] = [{"subject": subjects[0], "description": "先做概念提取卡", "minutes": 3, "required": True}]
        if mode == "review":
            source = self.write(f"测试题库/{subjects[0]}-原题.txt", "合成完整原题：说明给定定义的适用对象和条件。非真实考试题。")
            answer = self.write(f"测试题库/{subjects[0]}-答案.txt", "合成题配套答案：分别说明对象与条件。非真实考试答案。")
            sid = next(a["id"] for a in m["artifacts"] if a["role"] == "student_practice_docx")
            aid = next(a["id"] for a in m["artifacts"] if a["role"] == "answer_docx")
            m["practice"].append({"id": "Q1", "subject": subjects[0], "topic": "概念条件", "finding_ids": ["F1"],
                                  "source_type": "original", "source_category": "beijing_gaokao", "learning_level": "learned", "prerequisite_evidence": [m["inputs"][0]["id"]],
                                  "source": {"path": workflow.relative(self.root, source), "sha256": workflow.sha256(source), "citation": "合成北京高考夹具第1题", "locator": "第1行"},
                                  "answer_source": {"path": workflow.relative(self.root, answer), "sha256": workflow.sha256(answer), "citation": "合成夹具配套答案", "locator": "第1行"},
                                  "source_completeness": "complete", "source_components": ["stem", "conditions", "subquestions"],
                                  "figure_required": False, "figure_paths": [], "student_artifact_id": sid, "answer_artifact_id": aid,
                                  "minutes": 8, "required": True})
            m["review_plan"] = {
                "parent_deliverable": "none", "time_policy": "evidence_driven",
                "coverage": [{"id": "C1", "subject": subjects[0], "topic": "概念条件", "status": "待验证",
                              "fact": "本月资料出现概念提问，尚无独立作答证据。", "evidence_input_ids": ["I0001"],
                              "finding_ids": ["F1"], "error_point": "尚无可确认错误", "next_check": "完成本次原题验证。"}],
                "validation_tasks": [{"id": "V1", "subject": subjects[0], "finding_ids": ["F1"], "practice_ids": ["Q1"],
                                      "purpose": "验证能否独立说明对象和条件。", "suggested_sessions": ["可分段完成"]}],
            }
        if mode == "weekly":
            m["activities"][0].update(id="T1", finding_ids=["F1"])
            m["weekly_plan"] = {
                "previous_review": {"status": "no_previous_plan", "source": {}, "evidence": [],
                                    "summary": "隔离测试资料库无历史训练计划，本批仅建立待验证目标。"},
                "budget_note": "必做时间包含概念卡、作答及核对；后续以校内自然作答观察，不额外布置周末任务。",
                "focuses": [{"id": f"W{i + 1}", "subject": subject, "finding_ids": [f"F{i + 1}"],
                             "practice_ids": [f"Q{i + 1}"], "activity_ids": ["T1"] if i == 0 else [],
                             "success_criteria": "未看答案、无提示，说清对象及适用条件。",
                             "stop_rule": "本题时间到或提示一次仍卡住就停，记录具体位置。",
                             "recheck": {"trigger": "下次相关学校作业回传", "method": "核查不同题目的独立作答与条件说明。"}}
                            for i, subject in enumerate(subjects)], "no_required_reason": ""}
        if followup:
            self.add_feedback(run, m)
        workflow.write_json(run / "run.json", m)
        self.review_all(run)
        self.assertTrue(workflow.validate(run)["pass"], workflow.validate(run))
        return run

    def review_all(self, run):
        m = workflow.read_json(run / "run.json")
        record = run / "核验记录.md"
        record.write_text("本记录仅供程序回归测试。内容与原始合成夹具逐项对应，未把提问认作错误，状态保持待观察；所有拟更新记忆保留原文，增加来源。版式材料为程序夹具，不代表真实DOCX视觉验收。", encoding="utf-8")
        record_rel = workflow.relative(self.root, record)
        all_ids = [a["id"] for a in m["artifacts"]]
        workflow.record_review(run, "content", record_rel, all_ids)
        child_ids = [a["id"] for a in m["artifacts"] if a["role"] in workflow.STUDENT_ROLES | workflow.FEEDBACK_ROLES]
        if m["scope"]["mode"] == "weekly":
            child_ids += [a["id"] for a in m["artifacts"] if a["role"] in {"parent_md", "overview_md"}]
        if child_ids:
            workflow.record_review(run, "learning", record_rel, child_ids)
        question_ids = list({q[key] for q in m["practice"] for key in ("student_artifact_id", "answer_artifact_id")})
        question_ids += [a["id"] for a in m["artifacts"] if a["role"] in workflow.FEEDBACK_ROLES]
        if question_ids:
            workflow.record_review(run, "source", record_rel, question_ids)
        for artifact in m["artifacts"]:
            if artifact["role"].endswith("_docx"):
                pdf, png = run / (artifact["id"] + "-fixture.pdf"), run / (artifact["id"] + "-fixture.png")
                with fitz.open() as doc:
                    doc.new_page().insert_text((50, 50), "Synthetic layout fixture only")
                    doc.save(pdf)
                    doc[0].get_pixmap().save(png)
                workflow.record_review(run, "layout", record_rel, [artifact["id"]], rendered_pdf=workflow.relative(self.root, pdf), page_images=[workflow.relative(self.root, png)])

    def mutate(self, run, edit):
        m = workflow.read_json(run / "run.json")
        edit(m)
        workflow.write_json(run / "run.json", m)

    def add_feedback(self, run, manifest=None):
        m = manifest if manifest is not None else workflow.read_json(run / "run.json")
        m["feedback"] = {"status": "provided", "reason": "", "items": []}
        for i, item in enumerate(m["inputs"]):
            subject = item["subject"]
            ids = []
            for role in ("feedback_md", "feedback_docx"):
                art = next((a for a in m["artifacts"] if a["role"] == role and a["subject"] == subject), None)
                if art is None:
                    art = {"id": f"FB-{i}-{role}", "role": role, "subject": subject}
                    m["artifacts"].append(art)
                path = run / "staged" / (art["id"] + "." + role.rsplit("_", 1)[-1])
                text = "做完后核对。第1题：可见条件提问，作答待核。标准要点：说明对象和条件。先说清条件，下次在自然作业中独立说明。合成夹具。"
                if role.endswith("docx"):
                    self.docx(path, text)
                else:
                    path.write_text(text, encoding="utf-8")
                art.update(path=workflow.relative(self.root, path), destination="打印版/测试/" + path.name)
                ids.append(art["id"])
            answer = self.write(f"测试题库/{subject}-反馈标准.txt", "合成标准要点：说明对象和条件。")
            m["feedback"]["items"].append({
                "id": f"FB{i + 1}", "subject": subject, "input_id": item["id"], "locator": "第1题",
                "student_response": "可见条件提问，完整作答无法确认", "result": "uncertain",
                "observation": "本批尚不能确认本题对错", "independence": "unknown",
                "answer": {"status": "verified", "text": "说明对象和条件",
                           "source": {"path": workflow.relative(self.root, answer), "sha256": workflow.sha256(answer),
                                      "citation": "合成题标准要点", "locator": "第1行"}},
                "next_step": "先补清晰原始作答，不重复整套训练", "success_criteria": "下次自然作业中无提示说清条件",
                "artifact_ids": ids})
        if manifest is None:
            workflow.write_json(run / "run.json", m)

    def blocked(self, run, needle):
        result = workflow.validate(run)
        self.assertFalse(result["pass"], result)
        self.assertTrue(any(needle in e for e in result["errors"]), result)

    def test_triage_is_only_a_routing_stage(self):
        run = self.prepare("inbox")
        m = workflow.read_json(run / "run.json")
        # The triage contract is checked with the same source and routing artifact shape,
        # but must not silently become a notes/homework/exam completion.
        self.assertIn("triage", workflow.contract()["modes"])
        self.assertEqual(workflow.contract()["modes"]["triage"]["subject_artifacts"], [])
    def test_complete_notes_publish_and_receipt(self):
        run = self.prepare()
        result = workflow.release(run)
        self.assertTrue(result["pass"])
        self.assertEqual(workflow.status(run)["status"], "delivered")
        self.assertTrue(workflow.validate(run)["pass"])
        self.assertTrue((run / "previous" / "长期记忆" / "笔记追踪.md").is_file())

    def test_triage_publishes_routing_only(self):
        root = self.root
        subjects = ["数学"]
        self.write("学习总索引.md", "# 测试资料库")
        self.write("AGENTS.md", "# 测试入口")
        for raw in workflow.rule_paths(root, "triage", {"mode": "triage"}):
            self.write(raw, "# 测试规则\n只检查分拣，不判断学情。")
        self.write("临时文件/处理日志.md", "# 处理日志\n")
        self.write("临时文件/待处理/数学笔记.jpg", "synthetic photo")
        scope = {"mode": "triage", "request": "只分类归档本批照片", "subjects": subjects,
                 "source_roots": ["临时文件/待处理"], "index_paths": []}
        run = workflow.start(root, scope)
        workflow.read_rules(run)
        m = workflow.read_json(run / "run.json")
        routing = run / "staged" / "routing.md"
        routing.write_text("本批分拣：数学/笔记；照片模糊项另列待确认。未进行学情判断、OCR或出题。", encoding="utf-8")
        art = m["artifacts"][0]
        art.update(path=workflow.relative(root, routing), destination="临时文件/处理日志-2026-09-12.md")
        item = m["inputs"][0]
        item.update(subject="数学", kind="notes", status="processed", event_id="E1", route="数学/笔记/高二上/9.12",
                    artifact_ids=[art["id"]])
        update = m["updates"][0]
        staged_log = run / "staged" / "log.md"
        staged_log.write_text("# 处理日志\n| 本批 | 数学笔记 | 已归档 |", encoding="utf-8")
        update.update(decision="update", staged_path=workflow.relative(root, staged_log), reason="登记照片去向和待深度处理状态。")
        workflow.write_json(run / "run.json", m)
        record = run / "triage-review.md"
        record.write_text("本记录逐项对照输入照片和分拣日志，只核对学科、类型、目标去向及待确认说明；明确本阶段未做OCR、诊断、题库选题、掌握状态更新和学生交付。", encoding="utf-8")
        workflow.record_review(run, "content", workflow.relative(root, record), [art["id"]])
        result = workflow.release(run)
        self.assertTrue(result["pass"], result)
        self.assertEqual(workflow.status(run)["status"], "delivered")
        self.assertTrue((root / art["destination"]).is_file())

    def test_complete_practice_with_distinct_answer_and_layout(self):
        run = self.prepare("practice")
        result = workflow.release(run)
        self.assertTrue(result["pass"])
        self.assertEqual(result["required_minutes"], 11)

    def test_complete_review_has_student_map_without_parent_and_no_fixed_cap(self):
        run = self.prepare("review")
        result = workflow.release(run)
        self.assertTrue(result["pass"], result)
        self.assertEqual(result["time_policy"], "evidence_driven")
        self.assertEqual(workflow.status(run)["status"], "delivered")

    def test_review_allows_accounting_date_after_period_end(self):
        run = self.prepare("review")
        scope = workflow.read_json(run / "run.json")["scope"]
        self.assertLessEqual(scope["period"]["end"], scope["period"]["as_of"])

    def test_review_requires_deep_processing_record_for_each_input(self):
        run = self.prepare("review")
        self.mutate(run, lambda m: m["inputs"][0].pop("deep_review"))
        self.review_all(run)
        self.blocked(run, "deep_review")

    def test_review_cannot_reuse_triage_without_rechecking(self):
        run = self.prepare("review")
        self.mutate(run, lambda m: m["inputs"][0]["deep_review"].update(status="reused_and_rechecked"))
        self.review_all(run)
        self.blocked(run, "只有 triage 预索引")

    def test_review_cannot_defer_inputs_as_reference_entries(self):
        run = self.prepare("review")
        def defer(m):
            item = m["inputs"][0]
            item.update(status="deferred", reason="月度复盘引用入口", artifact_ids=[], deep_review={})
            item["review_block"] = {"status": "blocked", "next_action": "补做原始资料深度复核。"}
        self.mutate(run, defer)
        self.review_all(run)
        self.blocked(run, "不能用引用入口")

    def test_review_requires_complete_question_metadata(self):
        run = self.prepare("review")
        self.mutate(run, lambda m: m["practice"][0].pop("source_components"))
        self.review_all(run)
        self.blocked(run, "source_components")

    def test_complete_weekly_two_subjects(self):
        run = self.prepare("weekly", ["数学", "物理"])
        self.assertTrue(workflow.release(run)["pass"])

    def test_weekly_reads_review_workflow(self):
        run = self.prepare("weekly")
        paths = {r["path"] for r in workflow.read_rules(run)}
        self.assertIn("长期记忆/复盘工作流模板.md", paths)

    def test_weekly_cannot_publish_without_action_plan(self):
        run = self.prepare("weekly")
        self.mutate(run, lambda m: m.pop("weekly_plan"))
        self.review_all(run)
        self.blocked(run, "上期结果回看")
        self.assertFalse(workflow.release(run)["pass"])

    def test_weekly_requires_pass_and_stop_criteria(self):
        run = self.prepare("weekly")
        self.mutate(run, lambda m: m["weekly_plan"]["focuses"][0].update(success_criteria="", stop_rule=""))
        self.review_all(run)
        self.blocked(run, "独立通过标准或停止条件")

    def test_weekly_rejects_unassigned_required_activity(self):
        run = self.prepare("weekly")
        self.mutate(run, lambda m: m["activities"].append({"id": "T2", "subject": "数学", "finding_ids": ["F1"],
                                                        "description": "次日回做", "minutes": 4, "required": True}))
        self.review_all(run)
        self.blocked(run, "未完整对应周重点")

    def test_weekly_rejects_cross_subject_assignment(self):
        run = self.prepare("weekly", ["数学", "物理"])
        self.mutate(run, lambda m: m["weekly_plan"]["focuses"][0].update(practice_ids=["Q2"]))
        self.review_all(run)
        self.blocked(run, "不是同目标必做任务")

    def weekly_previous(self, run, status="no_feedback"):
        source = self.write("周复盘/上期/家长版周报.md", "# 合成上期计划\n独立解释概念条件，之后回传作答。")
        previous = {"status": status, "source": {"path": workflow.relative(self.root, source),
                    "sha256": workflow.sha256(source), "locator": "上期概念条件目标"},
                    "summary": "上期目标暂未收到可核对的训练回传，不能认定训练失败或退步。", "evidence": []}
        self.mutate(run, lambda m: m["weekly_plan"].update(previous_review=previous))
        self.review_all(run)
        return source

    def test_weekly_missing_feedback_allows_honest_delivery(self):
        run = self.prepare("weekly")
        self.weekly_previous(run)
        result = workflow.release(run)
        self.assertTrue(result["pass"], result)
        self.assertTrue(any("学习效果待验证" in x for x in result["limits"]))
        self.assertEqual(workflow.status(run)["status"], "delivered_with_limits")

    def test_weekly_result_review_needs_returned_evidence(self):
        run = self.prepare("weekly")
        self.weekly_previous(run, "reviewed")
        self.blocked(run, "实际回传证据")

    def test_weekly_can_review_actual_returned_work(self):
        run = self.prepare("weekly")
        self.weekly_previous(run, "reviewed")
        self.mutate(run, lambda m: m["weekly_plan"]["previous_review"].update(
            summary="合成回传显示孩子提出条件问题，目前仅待观察，本次做少量验证。",
            evidence=[{"input_id": "I0001", "locator": "原材料第1行", "observation": "有课堂提问，无独立正确结果。"}]))
        self.review_all(run)
        self.assertTrue(workflow.release(run)["pass"])

    def test_weekly_focus_requires_beijing_gaokao_question(self):
        run = self.prepare("weekly")
        self.mutate(run, lambda m: m["practice"][0].update(source_category="beijing_mock"))
        self.review_all(run)
        self.blocked(run, "缺已核验北京高考原题")

    def test_weekly_cards_and_limits_cannot_replace_gaokao_question(self):
        run = self.prepare("weekly")
        def edit(m):
            m["practice"] = []
            m["practice_limits"] = [{"subject": "数学", "reason": "只做卡片", "search_record": m["artifacts"][0]["path"]}]
            m["weekly_plan"]["focuses"][0]["practice_ids"] = []
        self.mutate(run, edit)
        self.review_all(run)
        self.blocked(run, "必须关联至少一道已核验北京高考原题")

    def test_weekly_without_focus_still_requires_one_gaokao_question(self):
        run = self.prepare("weekly")
        def edit(m):
            for task in m["practice"] + m["activities"]:
                task["required"] = False
            m["practice"] = []
            m["practice_limits"] = [{"subject": "数学", "reason": "没有明确重点", "search_record": m["artifacts"][0]["path"]}]
            m["weekly_plan"].update(focuses=[], no_required_reason="本周无明确强化重点。")
        self.mutate(run, edit)
        self.review_all(run)
        self.blocked(run, "周打印版至少须有一道已核验北京高考原题")

    def test_weekly_rejects_pre_generated_feedback(self):
        run = self.prepare("weekly")
        self.mutate(run, lambda m: m.update(feedback={"status": "provided", "reason": "", "items": []}))
        self.review_all(run)
        self.blocked(run, "周打印阶段不得预生成")

    def test_followup_cannot_only_update_internal_tracking(self):
        run = self.prepare("homework", followup=True)
        self.mutate(run, lambda m: m.pop("feedback"))
        self.review_all(run)
        self.blocked(run, "缺孩子反馈登记")
        self.assertFalse(workflow.release(run)["pass"])

    def test_followup_cannot_claim_no_submissions(self):
        run = self.prepare("homework", followup=True)
        self.mutate(run, lambda m: m.update(feedback={"status": "no_submissions", "reason": "已有回传但只改后台", "items": []}))
        self.review_all(run)
        self.blocked(run, "已有作答或回传不能免交")

    def test_feedback_covers_every_returned_subject(self):
        run = self.prepare("homework", ["数学", "物理"], followup=True)
        self.mutate(run, lambda m: m["feedback"]["items"].pop())
        self.review_all(run)
        self.blocked(run, "漏掉已处理作答/回传资料")

    def test_feedback_requires_actual_docx_not_just_tracking_md(self):
        run = self.prepare("homework", followup=True)
        self.mutate(run, lambda m: m["feedback"]["items"][0]["artifact_ids"].pop())
        self.review_all(run)
        self.blocked(run, "缺反馈归档 MD 或正式 DOCX")

    def test_feedback_rejects_non_feedback_file_as_child_feedback(self):
        run = self.prepare("homework", followup=True)
        self.mutate(run, lambda m: m["feedback"]["items"][0].update(
            artifact_ids=[next(a["id"] for a in m["artifacts"] if a["role"] == "correction_md")]))
        self.review_all(run)
        self.blocked(run, "反馈只能关联同科独立反馈文件")

    def test_feedback_wrong_answer_requires_error_and_cause(self):
        run = self.prepare("homework", followup=True)
        self.mutate(run, lambda m: m["feedback"]["items"][0].update(result="wrong"))
        self.review_all(run)
        self.blocked(run, "缺具体错点")
        self.blocked(run, "缺错因及确定程度")

    def test_feedback_does_not_force_invented_cause_or_independence(self):
        run = self.prepare("homework", followup=True)
        self.mutate(run, lambda m: m["feedback"]["items"][0].update(
            result="wrong", error_point="缺少适用条件", cause={"status": "unknown", "explanation": "原因待验证，先请孩子解释这一步"}))
        self.review_all(run)
        self.assertTrue(workflow.release(run)["pass"])

    def test_feedback_all_correct_still_delivers_without_fake_errors(self):
        run = self.prepare("homework", followup=True)
        self.mutate(run, lambda m: m["feedback"]["items"][0].update(result="correct", observation="纸面符合标准；独立性未知"))
        self.review_all(run)
        result = workflow.release(run)
        self.assertTrue(result["pass"], result)
        self.assertEqual(workflow.status(run)["status"], "delivered")
        m = workflow.read_json(run / "run.json")
        self.assertEqual(m["findings"][0]["state"], "待观察")
        self.assertTrue(all((self.root / a["destination"]).is_file() for a in m["artifacts"] if a["role"] in workflow.FEEDBACK_ROLES))

    def test_feedback_pending_answer_is_honest_partial_delivery(self):
        run = self.prepare("homework", followup=True)
        self.mutate(run, lambda m: m["feedback"]["items"][0].update(answer={"status": "pending", "reason": "原卷答案页缺失"}))
        self.review_all(run)
        result = workflow.release(run)
        self.assertTrue(result["pass"], result)
        self.assertEqual(workflow.status(run)["status"], "delivered_with_limits")
        self.assertTrue(any("原卷答案页缺失" in x for x in result["limits"]))

    def test_feedback_unverified_answer_cannot_determine_correctness(self):
        run = self.prepare("homework", followup=True)
        self.mutate(run, lambda m: m["feedback"]["items"][0].update(
            result="correct", answer={"status": "pending", "reason": "答案待核", "text": "猜测答案"}))
        self.review_all(run)
        self.blocked(run, "未核答案不能判定对错")

    def test_feedback_answer_source_is_bound_to_review(self):
        run = self.prepare("homework", followup=True)
        m = workflow.read_json(run / "run.json")
        raw = m["feedback"]["items"][0]["answer"]["source"]["path"]
        self.assertTrue(any(f["path"] == raw for r in m["reviews"] for f in r["files"]))
        self.write(raw, "合成答案已修订，须重审")
        self.blocked(run, "反馈答案来源已改变")
        self.blocked(run, "缺反馈作答与标准答案对照审核")

    def test_feedback_changes_invalidate_review(self):
        run = self.prepare("homework", followup=True)
        self.mutate(run, lambda m: m["feedback"]["items"][0].update(next_step="先解释条件再核对"))
        self.blocked(run, "缺对应当前文件的内容审核")

    def test_feedback_needs_learning_and_source_reviews(self):
        run = self.prepare("homework", followup=True)
        self.mutate(run, lambda m: m.update(reviews=[r for r in m["reviews"] if r["kind"] not in {"source", "learning"}]))
        self.blocked(run, "缺反馈作答与标准答案对照审核")
        self.blocked(run, "缺反馈正文")

    def test_feedback_needs_post_completion_label(self):
        run = self.prepare("homework", followup=True)
        m = workflow.read_json(run / "run.json")
        art = next(a for a in m["artifacts"] if a["role"] == "feedback_md")
        self.write(art["path"], "标准答案和分析，未注明使用时机。")
        self.review_all(run)
        self.blocked(run, "反馈须明确标注做完后核对")

    def test_weekly_submitted_homework_does_not_pre_generate_feedback(self):
        run = self.prepare("weekly")
        self.mutate(run, lambda m: m["inputs"][0].update(kind="homework"))
        self.review_all(run)
        self.assertNotIn("feedback", workflow.read_json(run / "run.json"))
        self.assertTrue(workflow.release(run)["pass"])

    def test_weekly_returned_evidence_is_summarized_without_new_feedback_file(self):
        run = self.prepare("weekly")
        self.weekly_previous(run, "reviewed")
        self.mutate(run, lambda m: m["weekly_plan"]["previous_review"].update(
            evidence=[{"input_id": "I0001", "locator": "第1题", "observation": "实际回传待核"}]))
        self.review_all(run)
        self.assertTrue(workflow.release(run)["pass"])

    def test_followup_updates_knowledge_tracking_and_review_log(self):
        run = self.prepare("homework", followup=True)
        baseline = workflow.read_json(run / "baseline.json")
        targets = {u["path"] for u in baseline["updates"]}
        self.assertTrue({"长期记忆/知识点追踪.md", "长期记忆/复盘日志.md"}.issubset(targets))
        self.assertIn("长期记忆/复盘工作流模板.md", {r["path"] for r in baseline["rules"]})
        self.assertTrue(workflow.release(run)["pass"])
        for target in ("长期记忆/知识点追踪.md", "长期记忆/复盘日志.md"):
            self.assertIn("待观察", (self.root / target).read_text(encoding="utf-8"))

    def test_weekly_previous_source_is_bound_to_review(self):
        run = self.prepare("weekly")
        source = self.weekly_previous(run)
        m = workflow.read_json(run / "run.json")
        parent_id = next(a["id"] for a in m["artifacts"] if a["role"] == "parent_md")
        self.assertTrue(any(parent_id in r["artifact_ids"] and any(
            f["path"] == workflow.relative(self.root, source) for f in r["files"]) for r in m["reviews"]))
        source.write_text("合成上期计划已被改动，需要重新核对。", encoding="utf-8")
        self.blocked(run, "文件已改变")

    def test_weekly_parent_plan_needs_learning_review(self):
        run = self.prepare("weekly")
        def edit(m):
            student_ids = {a["id"] for a in m["artifacts"] if a["role"] in workflow.STUDENT_ROLES}
            for review in m["reviews"]:
                if review["kind"] == "learning":
                    review["artifact_ids"] = [a for a in review["artifact_ids"] if a in student_ids]
        self.mutate(run, edit)
        self.blocked(run, "缺周计划与正文")

    def test_weekly_no_required_work_needs_reason(self):
        run = self.prepare("weekly")
        def edit(m):
            for task in m["practice"] + m["activities"]:
                task["required"] = False
            m["weekly_plan"].update(focuses=[], no_required_reason="已有学习任务足够，本次只提供选用材料，等待校内自然作答。")
        self.mutate(run, edit)
        self.review_all(run)
        self.assertTrue(workflow.validate(run)["pass"], workflow.validate(run))
        self.mutate(run, lambda m: m["weekly_plan"].update(no_required_reason=""))
        self.review_all(run)
        self.blocked(run, "无需必做")

    def test_weekly_plan_change_invalidates_review(self):
        run = self.prepare("weekly")
        self.mutate(run, lambda m: m["weekly_plan"]["focuses"][0].update(success_criteria="改为另一项能力，需要重新审核。"))
        self.blocked(run, "内容审核记录")

    def test_inbox_requires_learning_processing_after_moves(self):
        run = self.prepare("inbox")
        self.mutate(run, lambda m: m["inputs"][0].update(artifact_ids=[m["artifacts"][0]["id"]]))
        self.blocked(run, "仅归档")

    def test_missing_source_is_not_completed(self):
        run = self.prepare()
        self.mutate(run, lambda m: m["inputs"].clear())
        self.blocked(run, "清单被删减")

    def test_subject_cannot_silently_disappear(self):
        run = self.prepare("weekly", ["数学", "物理"])
        self.mutate(run, lambda m: m["artifacts"].__setitem__(slice(None), [a for a in m["artifacts"] if a["subject"] != "物理"]))
        self.blocked(run, "缺必交付项：物理")

    def test_empty_file_does_not_count_as_deliverable(self):
        run = self.prepare()
        m = workflow.read_json(run / "run.json")
        (self.root / m["artifacts"][0]["path"]).write_text("", encoding="utf-8")
        self.blocked(run, "空交付物")

    def test_changed_output_invalidates_review(self):
        run = self.prepare()
        m = workflow.read_json(run / "run.json")
        (self.root / m["artifacts"][0]["path"]).write_text("修改后的内容未经重新审核。", encoding="utf-8")
        self.blocked(run, "内容审核")

    def test_changed_memory_draft_invalidates_review(self):
        run = self.prepare()
        m = workflow.read_json(run / "run.json")
        (self.root / m["updates"][0]["staged_path"]).write_text("无证据地把状态改了。", encoding="utf-8")
        self.blocked(run, "内容审核")

    def test_validation_requires_rule_read_event(self):
        run = self.prepare()
        events = workflow.read_json(run / "events.json")
        events[:] = [event for event in events if event.get("event") != "rules_read"]
        workflow.write_json(run / "events.json", events)
        self.blocked(run, "未登记本批规则读取")

    def test_skill_config_version_drift_blocks_start(self):
        with self.assertRaisesRegex(ValueError, "配置版本"):
            self.prepare(config_version="0.0.0")
    def test_rule_change_requires_revision(self):
        run = self.prepare()
        self.write("长期记忆/执行与验收规范.md", "规则已改，需要重新读取和核对")
        self.blocked(run, "文件已改变")

    def test_new_input_requires_scope_reconciliation(self):
        run = self.prepare()
        self.write("输入/后来新增.txt", "新增资料不能遗漏")
        self.blocked(run, "新增了文件")

    def test_no_standard_answer_blocks_formal_practice(self):
        run = self.prepare("practice")
        self.mutate(run, lambda m: m["practice"][0].update(answer_source={}))
        self.blocked(run, "answer_source 缺来源")

    def test_missing_required_figure_blocks_practice(self):
        run = self.prepare("practice")
        self.mutate(run, lambda m: m["practice"][0].update(figure_required=True))
        self.blocked(run, "缺必要题图")

    def test_unconfirmed_prerequisites_block_practice(self):
        run = self.prepare("practice")
        self.mutate(run, lambda m: m["practice"][0].update(learning_level="unconfirmed"))
        self.blocked(run, "未确认已学前置内容")

    def test_student_answer_module_is_rejected(self):
        run = self.prepare("practice")
        m = workflow.read_json(run / "run.json")
        art = next(a for a in m["artifacts"] if a["role"] == "student_docx")
        self.docx(self.root / art["path"], "标准答案：错误混入学生文档的答案。")
        self.blocked(run, "学生版发现明显答案模块")

    def test_correction_is_not_improvement(self):
        run = self.prepare()
        def edit(m):
            m["findings"][0].update(state="已改善", change_basis="对照前次错处", attempts=[{"input_id": "I0001", "event_id": "E1", "date": "2026-09-10", "locator": "订正处", "result": "correct", "independent": False, "is_correction": True}])
        self.mutate(run, edit)
        self.blocked(run, "缺独立通过证据")

    def test_unconfirmed_correct_attempt_is_not_improvement(self):
        run = self.prepare()
        def edit(m):
            m["findings"][0].update(state="已改善", change_basis="合成旧问题对照", attempts=[{
                "input_id": "I0001", "event_id": "E1", "date": "2026-09-10", "locator": "第1题",
                "result": "correct", "confirmed": False, "independent": True, "is_correction": False}])
        self.mutate(run, edit)
        self.review_all(run)
        self.blocked(run, "缺独立通过证据")
        self.mutate(run, lambda m: m["findings"][0]["attempts"][0].update(confirmed=True))
        self.review_all(run)
        self.assertTrue(workflow.validate(run)["pass"], workflow.validate(run))

    def test_task_cannot_omit_required_flag_to_skip_time(self):
        run = self.prepare("practice")
        self.mutate(run, lambda m: m["practice"][0].pop("required"))
        self.review_all(run)
        self.blocked(run, "须明确必做或选做")

    def test_same_event_cannot_be_repeated_weakness(self):
        run = self.prepare()
        def edit(m):
            attempt = {"input_id": "I0001", "event_id": "E1", "date": "2026-09-10", "locator": "同题", "result": "wrong", "confirmed": True}
            m["findings"][0].update(state="反复薄弱", attempts=[attempt, copy.deepcopy(attempt)])
        self.mutate(run, edit)
        self.blocked(run, "两个独立")

    def test_note_without_performance_cannot_be_weakness(self):
        run = self.prepare()
        self.mutate(run, lambda m: m["findings"][0].update(state="薄弱"))
        self.blocked(run, "缺已确认错误事件")

    def test_missing_note_cannot_prove_not_learned(self):
        run = self.prepare()
        self.mutate(run, lambda m: m["findings"][0].update(teaching_status="not_learned"))
        self.blocked(run, "不能仅凭笔记缺记录")

    def test_time_limit_includes_non_question_work(self):
        run = self.prepare("practice")
        self.mutate(run, lambda m: m["activities"][0].update(minutes=20))
        self.blocked(run, "时间上限")

    def test_memory_concurrency_is_not_overwritten(self):
        run = self.prepare()
        m = workflow.read_json(run / "run.json")
        changed = self.write(m["updates"][0]["path"], "另一个任务新增的真实状态")
        self.blocked(run, "其他任务更新")
        self.assertFalse(workflow.release(run)["pass"])
        self.assertEqual(changed.read_text(encoding="utf-8"), "另一个任务新增的真实状态")

    def test_destination_cannot_overwrite_original_source(self):
        run = self.prepare()
        self.mutate(run, lambda m: m["artifacts"][0].update(destination=m["inputs"][0]["original_path"]))
        self.blocked(run, "禁止覆盖原始依据")

    def test_invalid_docx_is_not_accepted_by_filename(self):
        run = self.prepare("practice")
        m = workflow.read_json(run / "run.json")
        a = next(a for a in m["artifacts"] if a["role"] == "student_docx")
        (self.root / a["path"]).write_text("只是把文本扩展名改成docx", encoding="utf-8")
        self.blocked(run, "交付物")

    def test_manual_delivered_label_is_not_receipt(self):
        run = self.prepare()
        self.mutate(run, lambda m: m.update(status="delivered"))
        self.blocked(run, "缺有效发布回执")

    def test_repeat_release_does_not_duplicate_memory(self):
        run = self.prepare()
        workflow.release(run)
        with self.assertRaisesRegex(ValueError, "已交付"):
            workflow.release(run)

    def test_publish_failure_restores_previous_files(self):
        run = self.prepare()
        m = workflow.read_json(run / "run.json")
        for art in m["artifacts"]:
            self.write(art["destination"], "发布前旧文件")
        original_copy = shutil.copy2
        def fail_one(source, target, *args, **kwargs):
            if Path(source).parent == run / "staged" and Path(source).name == "A002.md":
                raise OSError("模拟第二份产物复制中断")
            return original_copy(source, target, *args, **kwargs)
        with patch.object(workflow.shutil, "copy2", side_effect=fail_one):
            with self.assertRaisesRegex(OSError, "复制中断"):
                workflow.release(run, replace=True)
        for art in m["artifacts"]:
            self.assertEqual((self.root / art["destination"]).read_text(encoding="utf-8"), "发布前旧文件")
        self.assertEqual(workflow.read_json(run / "run.json")["status"], "draft")

    def test_short_checkmark_is_not_review_record(self):
        run = self.prepare()
        record = self.write(workflow.relative(self.root, run / "敷衍.md"), "已核验")
        with self.assertRaisesRegex(ValueError, "审核记录"):
            workflow.record_review(run, "content", str(record), ["A001"])

    def test_future_attempt_date_cannot_be_evidence(self):
        run = self.prepare()
        future = (date.today() + timedelta(days=1)).isoformat()
        self.mutate(run, lambda m: m["findings"][0]["attempts"].append(
            {"input_id": "I0001", "event_id": "E1", "date": future, "locator": "未来记录",
             "result": "correct", "confirmed": True, "independent": True, "is_correction": False}
        ))
        self.blocked(run, "不能晚于今天")

    def test_triage_rejects_external_source_path(self):
        with self.assertRaisesRegex(ValueError, "相对文件名"):
            inbox_workflow.resolve_source(self.root, str(self.parent / "outside.jpg"))

    def test_triage_rejects_path_traversal_in_source(self):
        with self.assertRaisesRegex(ValueError, "待处理目录"):
            inbox_workflow.resolve_source(self.root, "..\\outside.jpg")

    def test_triage_rejects_symlink_source(self):
        inbox = self.root / "临时文件" / "待处理"
        inbox.mkdir(parents=True)
        target = inbox / "real.jpg"
        target.write_bytes(b"real")
        link = inbox / "link.jpg"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("当前文件系统不支持创建符号链接")
        with self.assertRaisesRegex(ValueError, "符号链接"):
            inbox_workflow.resolve_source(self.root, "link.jpg")

    def test_triage_rejects_path_traversal_in_target_components(self):
        move = inbox_workflow.PlannedMove(files=["a.jpg"], subject="数学", kind="笔记", grade="..\\..", date_label="9.12")
        with self.assertRaisesRegex(ValueError, "年级"):
            inbox_workflow.target_dir_for(self.root, move, "2026-09-12")

    def test_triage_dry_run_reserves_same_target(self):
        inbox = self.root / "临时文件" / "待处理"
        inbox.mkdir(parents=True)
        (inbox / "a.jpg").write_bytes(b"a")
        (inbox / "b.jpg").write_bytes(b"b")
        move = inbox_workflow.PlannedMove(files=["a.jpg", "b.jpg"], subject="数学", kind="笔记")
        results = inbox_workflow.apply_moves(self.root, [move], process_date="2026-09-12", batch="test", dry_run=True)
        targets = results[0]["targets"]
        self.assertEqual(len(targets), 2)
        self.assertNotEqual(targets[0], targets[1])
        self.assertTrue((inbox / "a.jpg").is_file() and (inbox / "b.jpg").is_file())

    def test_installer_preserves_old_copy_and_checks_drift(self):
        target = self.root / "host" / "skills" / "xuelema"
        self.assertTrue(installer.install(workflow.SKILL, target)["match"])
        with (target / "SKILL.md").open("a", encoding="utf-8") as out:
            out.write("\n目标副本发生变化。")
        self.assertFalse(installer.compare(workflow.SKILL, target)["match"])
        result = installer.install(workflow.SKILL, target, overwrite=True)
        self.assertTrue(result["match"])
        self.assertIn("目标副本发生变化", (Path(result["previous"]) / "SKILL.md").read_text(encoding="utf-8"))

    def test_installer_rejects_workspace_as_destination(self):
        with self.assertRaisesRegex(ValueError, "安装目标"):
            installer.install(workflow.SKILL, self.root, overwrite=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
