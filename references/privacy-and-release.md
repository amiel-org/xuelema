# Privacy And Release Rules

## 仓库边界

纯技能仓库只保存：

- `SKILL.md`
- `agents/openai.yaml`
- `references/`
- `scripts/`
- `assets/learning-vault-template`
- `requirements.txt`
- `.gitignore`

不要保存：

- 真实孩子资料、照片、课堂笔记原图
- 课件截图、老师讲义、学校内部资料
- 高考真题、一模二模原卷 PDF
- 生成的 DOCX/PDF/PNG 成品
- 临时下载缓存、OCR 中间结果、日志

## 发布前检查

1. 运行技能校验。
2. 运行 Python 语法编译。
3. 用空模板跑 `validate_vault.py`。
4. 搜索本机绝对路径、用户目录路径和真实姓名。
5. 确认 `git status` 里没有 PDF、照片、Word、缓存、日志。

## 版本规则

建议用 Git tag：

- `v0.1.0`：第一版可安装技能，含空模板、核心脚本和工作流。
- patch：修脚本 bug、改文案、补小模板。
- minor：新增稳定工作流、重大模板字段或新的题库能力。
- major：目录结构或使用规则不兼容旧资料库。

## 更新规则

更新技能时，先改仓库，再重新安装或覆盖到 Codex skills 目录。

每次更新都检查：

- `SKILL.md` 是否仍短而清楚。
- `agents/openai.yaml` 是否仍和技能描述一致。
- 新脚本是否支持 `--root`，不得绑死本机路径。
- 新模板是否不含真实材料。
- 题库脚本是否继续保持“机器标签只筛题，最终题目必须核验”的边界。
