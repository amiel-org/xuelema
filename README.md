# 学了么 / xuelema

面向北京高中生、可扩展到初中的学习闭环 Codex Skill。

“学了吗”不只整理一份资料，而是把笔记、作业改错、试卷和题库串成可持续更新的学习记录：先知道学了什么，再知道会不会用，最后用后续练习验证是否真的改善。

## 能做什么

- 整理课堂笔记：OCR 校对稿、整理版、复习卡片和知识点索引。
- 处理作业改错：定位错处，记录知识点、错因、正确做法和下次第一步。
- 复盘试卷：输出家长版诊断、学生版反馈、本周重点和针对性练习。
- 管理题库：对本地北京高考、区级模拟和学校试卷做文件校验、题号切分、机器初标和人工核验队列。
- 维护长期学习记忆：持续追踪知识点、错因、笔记、作业改错和近期重点。
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

2. 校验目录结构：

   ```powershell
   python scripts/validate_vault.py --root "D:\\LearningVault"
   ```

3. 将资料放入 `临时文件/待处理`，并在 Codex 中明确说“材料放好了，开始处理”。

4. 使用 Skill 完成笔记、作业改错、试卷或题库工作流；每次处理后更新长期记忆和下次验证动作。

## 依赖

```powershell
python -m pip install -r requirements.txt
```

## 仓库结构

```text
xuelema/
├── SKILL.md                         # Skill 入口与核心规则
├── agents/openai.yaml               # Codex 展示信息
├── scripts/                         # 初始化、校验、归档、题库处理脚本
├── references/                      # 工作流、打印公式、隐私发布规范
└── assets/learning-vault-template/  # 可复制的空学习资料库模板
```

## 进一步阅读

- [完整 Skill 说明](SKILL.md)
- [资料、作业、试卷、题库与周复盘工作流](references/workflows.md)
- [学生打印版与公式规则](references/print-and-formula.md)
- [隐私与发布边界](references/privacy-and-release.md)

## 隐私说明

这是一个公开的 Skill 仓库，只保存模板、脚本和规则。请不要将孩子的真实姓名、照片、课堂材料、学校内部资料、原卷 PDF 或生成的学生版交付物提交到 Git。
