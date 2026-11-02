# 任务记录与验收入口

适用于实际资料处理/打印交付。查询、讨论和系统维护不强制登记。程序是结构和审核时效检查，不是学科真理验证器；AI须真实对照原材料，不能为通过检查编造记录。

## 文件和路径

- 脚本：本技能 scripts/learning_run.py；所有命令使用当前可用Python，无需调用API。
- scope.json：AI根据用户范围、资料索引与只读扫描准备，家长不用填写。
- 资料库/任务记录/<批次>/baseline.json：程序扫描的输入、规则和记忆更新前指纹；不可编辑来消除错误。
- 同目录run.json：持续记录处理结果，允许AI逐步补全；旧版本状态不靠聊天恢复。
- staged/：产物、拟更新索引/记忆、审核说明和版式证据；正文确认前不改正式文件。
- validation.json、delivery.json：程序验收/发布回执。已交付批次只读，修订新建关联批次。

run.json内文件路径统一是相对资料库根目录的路径，也支持同一资料库内的绝对路径。产物必须处于本批staged内；destination是正式目录中的最终文件名。原材料不复制进技能仓库。

## 启动例子

以下是虚构路径，仅说明字段。实际目录须从本次索引与扫描确定，不照抄日期和学科。

```json
{
  "mode": "weekly",
  "request": "本周资料齐了，按既定流程出周复盘；实际截至周六",
  "subjects": ["数学", "物理"],
  "period": {"start": "2026-09-07", "end": "2026-09-13", "as_of": "2026-09-12"},
  "source_roots": ["数学/笔记/高二上/9.10", "物理/试卷/高二上/9.11"],
  "index_paths": ["数学/笔记/高二上/高二上数学笔记索引.md"],
  "time_budget_minutes": 50,
  "core_subject_limit": 2
}
```

mode为triage/inbox/notes/homework/exam/weekly/practice/review。日常常规模型做识别和归档时用triage；它可以进行轻量 OCR/视觉摘要和预索引（标题、章节、题号、页序、候选主题、清晰度、完整性、作答/订正/批注是否存在），完成含义是识别、预索引、分拣、日志和待确认清单，不包含完整 OCR 整理、学情诊断、练习或掌握状态更新。需要把照片继续处理成笔记/作业/试卷产物时用inbox；inbox先只读识别，再加material_kinds，例如["notes","homework"]，程序据此加载对应规则和最低追踪更新项。notes/homework/exam/inbox必须声明涉及的学科/学期index_paths；索引目标尚不存在也可登记。weekly/practice须有本次时间与学科上限；时间不能从此示例照搬。

source_roots既可单文件，也可目录；目录下的照片、PDF、MD、TXT、DOCX均登记。选择最小完整范围，不把整个资料库或技能目录当范围。参考原卷/答案可在practice中另行引用，不必当成孩子的作答事件。

回做结果使用 `mode=homework`、`followup=true`；由 AI 关联原周计划并登记实际回传。程序追加复盘、学生打印与题源规则、分科 feedback_md/feedback_docx，以及知识点追踪、复盘日志更新决定，与作业追踪/看板一并验收。普通作业无需此标记，用户也不用记字段。

```text
python <技能>/scripts/learning_run.py start --root <资料库> --scope <scope.json>
python <技能>/scripts/learning_run.py read-rules --run <任务目录>
python <技能>/scripts/learning_run.py status --run <任务目录>
```

`start` 后必须先运行一次 `read-rules`。该命令输出并登记本批实际规则及指纹；换模型或中断续接时仍以同一批次的 `run.json`、`baseline.json` 和 `status` 为准。没有规则读取事件的任务不能通过 `validate` 或 `release`。

可按输出路径分批读取规则，避免工具截断；须实际读取内容，指纹本身不证明读过。未登记的新资料或规则变化会提示另建修订批次，request注明承接批次和变化。

## 补全运行清单

程序创建inputs、subject_decisions、必交付artifacts和updates骨架。只编辑run.json，保留baseline。

### inputs

每个输入保留id、original_path、sha256；移动后只改path，内容指纹须相同。补：

- subject：范围内学科；kind：notes/homework/exam/reference。
- status：processed/duplicate/deferred/excluded。后三者写具体reason。
- event_id：实际独立学习事件；重拍/局部照同一个事件，不能按图片编号生成多个作答事件。
- duplicate_of：重复项指向已处理原件；相同指纹可自动提示，不同指纹同页重拍需要真实核对。
- artifact_ids：本输入被哪些产物处理；topics：深度流程填写所有可识别知识点，注明重点/简要保留/待核及产物去向；`triage` 可填写候选主题或内容线索，但必须标为候选/待核，不把预索引当作最终知识点判断。
- `review` 还必须补 `deep_review`：对象为 `completed`（本批完成深度复盘）或 `reused_and_rechecked`（复用前序深度产物并回原材料复核），并写 `source_stage`、`work`、`evidence_locators`、`artifact_ids`。仅做过 `triage` 的输入不得直接写 `reused_and_rechecked`；必须在本批完成深度处理。`deep_review` 是本次月度复盘的处理记录，不等于孩子已经掌握。
- `review` 中的 `deferred/excluded` 只能用于确实无法可靠读取、缺核心材料等阻塞项，须另写 `review_block.status=blocked`、具体原因和 `next_action`；不能用“月度复盘引用入口”“仅归档”“只筛选”等说法把期间资料跳过深度处理。

subject_decisions中的学科只能active或no_material；无材料要说明原因，不能把有已处理材料的科目标为无材料。

### findings

每个需要跟踪或选题的目标形成一条记录；普通笔记可保持待观察，不强造错误。

```json
{
  "id": "F1", "subject": "数学", "topic": "线面角辨认", "state": "待观察", "priority": "P1",
  "evidence": [{"input_id": "I0001", "locator": "第1页例题旁提问", "observation": "可见角类型辨认的提问，尚无独立测验结果"}],
  "teaching_status": "seen", "next_check": "下次用适配原题，先独立指出目标角并解释",
  "attempts": []
}
```

attempts只放确有作答的证据，字段为input_id、event_id、date、locator、result（correct/wrong）、confirmed、independent、is_correction。date是可确认的作答日期，不能拿归档日代替未知日期；未知时不用于需要跨次证据的状态升级。

薄弱需要确认错误事件；反复薄弱需要至少两个独立错误事件；已改善需要独立、非仅订正的正确作答和change_basis（对比旧问题的具体依据）；基本掌握默认需要不同日期至少两次独立通过。not_learned需要teaching_evidence，不能仅靠缺笔记。

### practice与activities

每题记录id、subject、topic、finding_ids、source_type（original/excerpt/adapted）、source、answer_source、learning_level（learned/intro_excerpt）、prerequisite_evidence（输入id）、figure_required、figure_paths、student_artifact_id、answer_artifact_id、minutes、required。

source和answer_source各含path、sha256、citation、locator；原题与答案可在同一卷不同页，均需可定位。节选加excerpt_note，说明保留范围和条件；改编必须有本次已有user_authorization并明确标注。

student_artifact_id和answer_artifact_id通常对应正式DOCX；题图需真实图形文件，并实际进入正式学生件。所有学生/答案MD和DOCX均须内容核验，确保相互对应。

卡片、回顾、口述等非题目活动单列activities：subject、description、minutes、required。必做总用时等于必做题目与非题目活动之和；不要漏掉卡片/阅读时间，也不要重复计算。

题目和活动均须用布尔值 `required` 明确必做/选做。周流程的 activities 另有唯一 `id` 和 `finding_ids`，关联同科的具体目标；阅读、核对、订正和本次复测也按实际安排计时。

每道题增加 `source_category`：`beijing_gaokao`、`beijing_mock`、`school` 或 `teaching_material`。weekly 的每个重点必须关联至少一道 required=true、source_category=`beijing_gaokao` 的已核原题或完整节选；卡片、校内旧题和 practice_limits 不能替代。没有明确重点时，weekly 仍至少登记一道 source_category=`beijing_gaokao` 的题，按本周知识点或历史待验证弱项选择，可设为低负担必做或明确选做，但整周不得为零。非重点科目无可靠题源时可在practice_limits写subject、reason、search_record（实际检索或暂缓说明路径），并在家长说明中披露。不得编题或假造标准答案来消除限制。

`review` 的每道题还需写 `source_completeness`（`complete` 或 `complete_excerpt`）和 `source_components`。`source_components` 至少说明本题实际需要的 `stem`、`stimulus`、`subquestions`、`options`、`conditions`、`figures` 中哪些部分；`complete` 表示学生件保留了题干、原文/材料、图表、选项、条件和小问，`complete_excerpt` 必须另写 `excerpt_note`，说明节选范围以及为何不影响作答。名著、文学阅读、英语阅读和材料题不能只写题意概括。`review` 允许同一学生练习文件承载多道题，学生/答案文件仍需独立。

### weekly_plan（仅 weekly）

由 AI 填写，内容同时落实到家长版和总览，不要求家长填表。

- `previous_review.status`：`reviewed`（已核对实际回传）、`no_feedback`（有上期计划但无可核回传）、`no_previous_plan`（已查无相关历史计划）。`summary` 逐项说明上期重点结果及本次减量/继续/换方法决定；首周写已查范围。
- 有上期计划时 `source` 写 `path`、`sha256`、`locator`，定位最近一次相关周报/计划；有关目标不在一份文件时在摘要中明确相关入口。`reviewed` 的 `evidence` 必须有 `input_id`、`locator`、`observation`，对应本批处理的真实回传。旧周报只是计划来源，不能当成孩子本周作答。无回传可继续发布，效果待验证列入限制。
- `budget_note` 说明预算覆盖的时段和任务；若安排周日复做，也计入本次必做总额。下周自然学校作答可作为验证时机，不虚构已选新题或额外时间。
- `focuses` 每项有唯一 `id`、`subject`、`finding_ids`、`practice_ids`、`activity_ids`、`success_criteria`、`stop_rule`、`recheck`（`trigger` 与 `method`）。每项至少关联一道同科、同目标、逐题核验过的北京高考必做真题或完整节选；所有必做题目/活动各归入一个重点，合并同任务验证的多个目标，避免重复计时。
- 默认少量重点，实际科目数/时间沿用 scope 的上限。无须必做时允许空 `focuses`，但须写 `no_required_reason` 且不能残留必做任务；有材料科目的归档与题源限制仍如实处理。

同一份原题回做通过不等于已迁移；核验后的独立新表现才用于相应状态判断。程序检查关联与字段完整性，目标是否足够具体、用时是否现实仍须内容复核。

### review_plan（仅 review）

月度/学期复盘不使用 `weekly_plan`，改在 `run.json.review_plan` 中记录覆盖和验证安排：

```json
{
  "parent_deliverable": "none",
  "time_policy": "evidence_driven",
  "coverage": [{
    "id": "C1", "subject": "数学", "topic": "空间角",
    "status": "已改善", "fact": "一次独立作答中完成两法向量和最终量",
    "evidence_input_ids": ["I0001"], "finding_ids": ["F1"],
    "error_point": "点积绝对值书写需保持",
    "next_check": "下一道自然作业空间角题"
  }],
  "validation_tasks": [{
    "id": "V1", "subject": "数学", "finding_ids": ["F1"],
    "practice_ids": ["Q1", "Q2"],
    "purpose": "一题检查保持，一题检查新情境迁移",
    "suggested_sessions": ["可分两次完成"]
  }]
}
```

`coverage` 至少覆盖每个有材料学科的主要内容；状态可写 `仅接触`、`待验证`、`已有表现`、`已改善`、`薄弱`、`反复薄弱` 或 `基本掌握`，但必须能回到本批 finding 和原始输入。`validation_tasks` 允许一个目标关联多道小题，也允许一个综合题覆盖多个目标；不要求每科恰好一道题，也不要求每科都布置必做题。`time_policy` 固定为 `evidence_driven` 时，题目中的 `minutes` 是建议用时和分段提示，不作为 `review` 的总时长上限；学生册的阅读时间与答题时间分开说明。

`review` 的每个已处理输入都必须有 `deep_review`。月度范围内当周资料即使刚由 `triage` 分拣，也要在本批完成深度复盘后才能进入 `topics`、`findings`、`coverage` 或验证题选择；只写分拣日志、候选主题或“已归档”不能通过。`reused_and_rechecked` 只适用于前序已有深度产物且本批已回原材料复核的输入。

除确实无法可靠处理的阻塞项外，`review` 不得把期间输入标成 `deferred/excluded`；阻塞项必须在交付限制中列明，不能作为“全部资料已复盘”的依据。

### feedback（仅回做阶段必填）

与 findings 分开：findings 用于长期跟踪目标，feedback 是孩子完成本周学生版并回传后才生成的逐题反馈。weekly 不创建 feedback，也不发布 feedback_md/feedback_docx；本周已有作业、试卷和上期结果只用于诊断、减量与选题。收到本周学生版回传后另开 `homework + followup=true`。

回做阶段 status=provided。每个有效学科增加独立 feedback_md 和 feedback_docx；必要时附 feedback_pdf。每条 items 关联同科两份实际文件，不能用 parent_md、后台 correction_md 或通用 answer_docx 代替。输入照片重拍合并，所有题目有去向，连续正确小题可准确合并题号；错题/未完成题逐项写。原始绝对路径仅在清单保留，孩子用原卷/任务名称、页码、题号定位。

下面仅展示条目形状；文件和指纹须取本批真实值，不得照抄示例：

```json
{
  "status": "provided",
  "reason": "",
  "items": [{
    "id": "FB1", "subject": "数学", "input_id": "I0001",
    "locator": "回做任务第1页第2题",
    "student_response": "写了结论，但未列适用条件",
    "result": "partial", "observation": "结论与标准一致，依据缺一个必要条件",
    "error_point": "证明中缺少条件核对",
    "cause": {"status": "unknown", "explanation": "不能仅凭省略步骤判断不会，待口头说明确认"},
    "independence": "unknown",
    "answer": {"status": "verified", "text": "实际核验后的完整答案或标准要点",
      "source": {"path": "题库/本次原卷答案.pdf", "sha256": "实际指纹", "citation": "原卷配套答案", "locator": "第2题答案页"}},
    "next_step": "只补缺失条件，并说明其作用",
    "success_criteria": "下一道校内同类题，无提示写全条件和结论",
    "artifact_ids": ["A反馈MD", "A反馈DOCX"]
  }]
}
```

- result：correct/partial/wrong/incomplete/uncertain。student_response 写原始作答；observation 写具体对错依据或做对之处。不能只写“薄弱”“注意审题”。
- partial/wrong/incomplete 必须有 error_point 和 cause；cause.status 为 confirmed/hypothesis/unknown，explanation 写依据或如何验证。正确题不必写错因。
- independence：independent/prompted/answer_seen/unknown，孩子件翻成自然中文；未知不能当独立通过。反馈结论本身不自动改变 findings 掌握状态。
- answer.status=verified 须有 text 和可回查的 source（path、sha256、citation、locator），来源按题源规范实际核验。缺可靠答案时 status=pending，reason 说明缺口，text 留空/省略；result 只能为 uncertain 或 incomplete，交付自动带限制。孩子反馈只写已确认事实和待核提示，不输出猜测。
- next_step 与 success_criteria 必填；做对的可写不重复本题、后续自然作业观察，不能强行制造训练。反馈不得提前暴露仍需独立完成的新题。
- 每份反馈正文标“做完后核对”。每条至少对应同科 feedback_md/feedback_docx；两份实际正文均需 content、source、learning 审核，DOCX/PDF另需layout。正文须含标准答案的关键解释，主观题用标准要点/得分点，不强造唯一表述。

程序核输入覆盖、字段、角色、独立文件、答案来源指纹与审核时效；不能自动识别一张照片含几道题或判断错因真实。审核必须逐项对照原图、清单与实际正文，查漏题、错配、正确表现遗漏和隐含加量，不能仅搜栏目名。反馈和答案来源修改后须重审。

### artifacts与updates

artifacts至少保留当前流程和有效学科的必交付项；可增加合理产物。每项填写id、role、subject、path、destination，role后缀对应实际md/docx/pdf。无材料学科的空骨架可保留，其他必交付项不能删除。`review` 的全局必交付项是 `student_review_md`、`student_review_docx`、`student_practice_md`、`student_practice_docx`、`answer_md`、`answer_docx` 和 `memory_md`，不要求 `parent_md`。inbox还需根据每个输入类型补齐关联产物，不能只移动文件。

updates由程序登记。decision写update或unchanged，reason写具体依据；update填写staged_path（拟更新完整文件）。更新前文件指纹不能修改；别人已更新正式记录时须合并并重新登记。非必要别名或联动变化，初始scope可通过学科索引登记，追踪表新增需求应在识别范围阶段明确，不通过index_paths覆盖规则。

## 审核与发布

先把范围、输入、诊断、练习、产物、拟更新文件写全，再真正审核并记录。审核说明至少写清对照哪些来源、检查了什么、发现与修复和限制；“已核验”不合格。

```text
python <技能>/scripts/learning_run.py review --run <任务目录> --kind content --record <审核说明.md> --artifacts A001 A002
python <技能>/scripts/learning_run.py review --run <任务目录> --kind source --record <逐题对照.md> --artifacts A003 A004
python <技能>/scripts/learning_run.py review --run <任务目录> --kind learning --record <适配与答案隔离.md> --artifacts A003
python <技能>/scripts/learning_run.py review --run <任务目录> --kind layout --record <逐页检查.md> --artifacts A003 --rendered-pdf <渲染.pdf> --page-images <第1页.png> <第2页.png>
python <技能>/scripts/learning_run.py validate --run <任务目录>
python <技能>/scripts/learning_run.py release --run <任务目录> --dry-run
python <技能>/scripts/learning_run.py release --run <任务目录>
```

review为通过真实检查后的登记命令，不替模型做内容审核；有未修复问题先保留在说明中，不登记pass。所有产物需要content；学生件需要learning；练习所关联产物需要source；每份DOCX/PDF单独需要layout及全部页图。程序自动绑定输入/题源/拟更新记忆和产物指纹，文件或清单改变后旧审核失效。

同一批次的 read-rules、review、release 及 run.json 修改必须串行执行，它们写同一份记录；并行执行会覆盖彼此的新记录。独立文件的只读检查可以并行。

weekly 的 `parent_md`（以及附带的 `parent_docx`/`parent_pdf`）与 `overview_md` 也需要 `learning`：实际对照正文、`weekly_plan`、题目/活动清单，检查上期接续、任务位置、预算合计、通过/停止标准和回传动作，不能只审核孩子文档。上期计划来源绑定这些审核，改变周计划或来源后须重新核对。

release每次重新validate。已有正式产物修订须使用--replace并保留旧版；已登记记忆的正常更新自动备份并检查更新前状态。原始依据不可覆盖。发布失败恢复已处理的目标；任务不标完成。

发布通过仍有待核输入/题源限制时状态是delivered_with_limits，回复应列明限制。全部无材料/未处理不能通过。旧周报没有新run记录，不能伪造一张通过表追认。

## 验证范围

程序能发现漏登记项、缺产物、路径越界、来源缺失、明显答案模块、未排版公式、重复事件、无证据状态变化、超时、过期审核和更新冲突。它不能自动证明OCR、学科推理、归因、节选条件和题图内容正确，也不是防篡改权限系统。必须实际审核，不能把清单填满当成教育质量。
