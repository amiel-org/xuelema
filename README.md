# 学了么 / xuelema

面向北京高中生、可扩展到初中的学习闭环系统。

“学了么”不只整理一份资料，而是把笔记、作业改错、试卷和题库串成可持续更新的学习记录：先知道学了什么，再知道会不会用，最后用后续练习验证是否真的改善。

## 能做什么

- 整理课堂笔记：OCR 校对稿、整理版、复习卡片和知识点索引。
- 处理作业改错：定位错处，记录知识点、错因、正确做法和下次第一步。
- 复盘试卷：输出家长版诊断、学生版反馈、本周重点和针对性练习。
- 管理题库：对本地北京高考、区级模拟和学校试卷做文件校验、题号切分、机器初标和人工核验队列。
- 维护长期学习记忆：持续追踪知识点、错因、笔记、作业改错和近期重点。
- 提供本地学情看板：六科当前重点、统一目标图谱、证据查看、题录多选打印、周/月复盘与执行任务，内置虚构演示数据。
- 联动学情目标底座：复用已复核的学习事件与五年真题目标索引，生成有来源、可锁定的联动候选；不自动判断掌握程度。
- 登记与验收任务：通过 `learning_run.py` 记录输入范围、规则读取、审核、验收和发布，支持中断后续接及产物变更后的重新审核。
- 支持月度与学期复盘：按统计期核对全部输入，区分事实、解释与待验证假设，不把资料分拣当成深度处理。
- 生成周复盘四件套：家长版周报、学生打印版、真题练习和长期记忆更新。

## 设计原则

- 真实孩子资料、照片、课堂笔记、学校材料和原卷 PDF 只留在个人学习资料库，不进入本仓库。
- 机器标签只用于筛选候选题，不能直接进入给孩子的最终内容。
- 学生版内容必须回到原始材料核验题干、图示、答案、公式和符号。
- 高中默认优先使用北京高考真题、北京一模二模和本地学校卷；初中复用闭环结构，但不硬套高中题源。

## 安装

将整个 `xuelema` 文件夹放到 Codex Skills 目录：

```text
~/.codex/skills/xuelema
```

也可以在仓库根目录执行：

```powershell
python scripts/install_local_skill.py --overwrite
```

重启 Codex 后即可使用 `$xuelema`。

## 快速开始

1. 创建一套空学习资料库：

   ```powershell
   python scripts/init_learning_vault.py --target "D:\\LearningVault"
   ```

2. 安装依赖并校验目录结构：

   ```powershell
   python scripts/validate_vault.py --root "D:\\LearningVault"
   ```

3. 将资料放入 `临时文件/待处理`，并在 Codex 中明确说“材料放好了，开始处理”。

4. 使用 Skill 完成笔记、作业改错、试卷或题库工作流；正式交付须经过任务登记、规则读取、审核、验收和发布，不能只生成草稿就标记完成。

日常资料可先做 `triage` 识别分拣；周复盘、月度或学期复盘再从原始材料继续深度核验。学情目标联动只复用已复核记录，候选映射和机器标签不等于已掌握，也不自动放行学生练习。

## 启动学情看板

```powershell
python dashboard/server.py
```

打开 `http://127.0.0.1:8765/` 即可体验完整看板。默认全部为虚构演示数据；个人数据通过 `--data` 指定，不要提交到仓库。看板只读，不因查看、打印或复盘刷新自动修改学情。详见[看板接入说明](dashboard/README.md)。

## 依赖

```powershell
python -m pip install -r requirements.txt
```

## 仓库结构

```text
xuelema/
├── SKILL.md                         # Skill 入口与核心规则
├── agents/openai.yaml               # Codex 展示信息
├── dashboard/                       # 本地学情看板、示例数据、校验与测试
├── scripts/                         # 任务闭环、目标联动、初始化、校验、归档与题库工具
├── references/                      # 工作流、打印公式、隐私发布规范
└── assets/learning-vault-template/  # 可复制的空学习资料库模板
```

## 进一步阅读

- [完整 Skill 说明](SKILL.md)
- [任务登记、审核与发布约定](references/run-contract.md)
- [学习证据与五年真题目标联动](references/target-linking.md)
- [资料、作业、试卷、题库与周复盘工作流](references/workflows.md)
- [学生打印版与公式规则](references/print-and-formula.md)
- [隐私与发布边界](references/privacy-and-release.md)

## 隐私说明

这是一个公开的 Skill 仓库，只保存模板、脚本和规则。请不要将孩子的真实姓名、照片、课堂材料、学校内部资料、原卷 PDF 或生成的学生版交付物提交到 Git。

## 验证

```powershell
python -m unittest discover -s scripts -p "test_*.py" -v
python scripts/validate_vault.py --root assets/learning-vault-template
python -m unittest discover -s dashboard -p "test_*.py" -v
```

当前版本见 `version.json`。维护源、Codex 安装目录及其他客户端安装目录可用 `scripts/install_local_skill.py --check --dest <安装目录>` 核对，避免只更新一份就误认为全部生效。
