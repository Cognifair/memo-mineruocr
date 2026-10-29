# 变更记录

遵循语义化版本：修 bug → patch，新增能力 → minor，改变契约 → major。

## v1.2.7 — 2026-10-30

影响面：memo-mineruocr(README.md)

### 变更

- README 顶部增加「墨卡大师 · 专业制卡工作流」在线介绍页链接。

## v1.2.6 — 2026-10-28

影响面：memo-mineruocr(SKILL.md)

### 变更

- 文档中的发布器名称由 `skill-publisher` 更新为 `maimemo-publisher`，与当前技能名保持一致。

## v1.2.5 — 2026-10-26

影响面：memo-mineruocr(SKILL.md)

### 修复

- 路线询问前先只读检测 `MINERU_TOKEN`，已配置时不再让用户确认或重提；路线问题只问一个决策，不与其他授权混在一起。
- 补充 Codex `request_user_input` 限制说明：有交互式问题框时优先使用；Codex 只允许可选问题，必答/权限按其规则用单条文字问题。

## v1.2.4 — 2026-10-24

### 修复

- `--replace-batch` 只允许替换「上传从未完成」的分片；运行中、待下载、已完成一律拒绝，避免重复建任务与消耗额度。
- Token 读取顺序统一为「本次明确指定 → 用户级环境变量」。

## v1.2.3 — 2026-10-24

### 变更

- 新增 MIT `LICENSE`，README 补 License 说明。

## v1.2.2 — 2026-10-23

### 变更

- README 的「Memo 系列」表与 `references/satellites.md` 改由 `memo-series.json` 生成（`sync-series`），不再手写跨技能清单。

## v1.2.3 — 2026-10-24

### 变更

- 新增 MIT `LICENSE`，README 补 License 说明。

## v1.2.1 — 2026-10-22

### 变更

- Token 配置时直接给出 API 管理直达链接 `https://mineru.net/apiManage`，不再让用户按“顶部 API → API 管理”自行找入口；SKILL.md 与 README 同步。

## v1.2.3 — 2026-10-24

### 变更

- 新增 MIT `LICENSE`，README 补 License 说明。

## v1.2.0 — 2026-10-19

### 新增

- Token 配置与墨卡大师对齐：优先读取用户级环境变量 `MINERU_TOKEN`，存在时不再重复索要。
- 用户本次提供 Token 后，用问题框询问是否写入用户环境变量；写入后新会话直接读取，避免反复输入。
- 明确只写入用户本人的 Token；问题框文案包含“接错会消耗别人的额度”的提醒。

### 安全

- 提问必须使用交互式问题框，不得只写文字结束回合；确实没有控件时才退回文字。
- Token 仍不写入技能文件、状态、日志、Git、清单或交付报告；Token 存在不等于上传授权。

## v1.2.3 — 2026-10-24

### 变更

- 新增 MIT `LICENSE`，README 补 License 说明。

## v1.1.0 — 2026-10-16

- 首次发布：本地/云端路线选择、大 PDF 分片、MinerU v4 云端提交与续跑、素材合并与覆盖检查。
