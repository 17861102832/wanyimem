# Security Policy

## 报告漏洞

请**不要**在公开 issue 中报告漏洞。请发送邮件至项目维护者（见 GitHub 仓库主页联系方式），或使用 GitHub 的 Private vulnerability reporting 功能。

## 隐私承诺

万忆中枢的设计目标是**全本地、零遥测、无云端依赖**：

- 记忆数据（SQLite + 事件日志）只存在于你的 `万忆中枢_STORE_DIR`
- 任何"记忆上传/同步到云"的 PR 都会被拒绝
- 开源仓库中不包含任何真实用户记忆数据

## 提交检查

如果你在提交中发现以下内容，请立即停止并清理：

- `.db` / `.jsonl` / `event_logs/` / `index.json` 等记忆数据文件（已被 `.gitignore` 覆盖）
- 环境变量、密钥、token（已被 `.gitignore` 覆盖）
- 个人绝对路径（应改为环境变量 + 通用默认值）

## 支持版本

当前仅维护 `main` 分支最新版本。
