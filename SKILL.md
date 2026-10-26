---
name: memo-mineruocr
description: Memo-MinerUOCR，识别 PDF、扫描件和文档图片并交付 Markdown，支持大 PDF 按页数和大小拆分、MinerU 云端任务续跑、图片引用整理与有序合并。首次使用先询问本地非 MinerU OCR 或 MinerUOCR；后者引导注册并安全配置 Token。不负责知识拆解、制卡或 Markji 写入。
metadata:
  version: "1.2.5"
---

# Memo-MinerUOCR v1.2.5

调用名 `$memo-mineruocr`；展示名「Memo-MinerUOCR」。它是 `memo-cardest` 的可选材料识别支链，也可独立把大文档转为 Markdown。OCR 结果不是已制成的卡片；不要自动总结、删减原文或调用 Markji。

## 首次使用：先问路线，再处理

第一次业务使用必须先问并等待明确回答。**问之前先只读检测 `MINERU_TOKEN` 是否存在**（`python -c "import os; print(bool(os.environ.get('MINERU_TOKEN')))"`，只看 true/false，不打印值），把结果写进问题：

> 这次文档识别，你想使用本地非 MinerU OCR，还是使用 MinerUOCR（官网云端，需要上传文件；Token 已配置 / 未配置）？

- **只问这一个决策**；不要把模板授权、表格适配、上传范围等混在同一条消息里，用户回答后再问下一个。
- 用户已配置 Token 时，**不要再让用户确认或重新提供**；未配置时才在该路线选中后给直达链接。
- 有交互式问题框时优先用问题框；Codex Desktop 的 `request_user_input` 仅允许可选问题、不得用于必答或权限，按其规则用**一条**简洁文字问题，不得把多个问题合并成一段。

两条路线平级，不预选；不要因为本机有 Token、安装了 MinerU 或某条路线失败就替用户选择。用户在当前请求中已明确选定时不重复提问。当前聊天可沿用明确选择；跨聊天没有可验证的用户偏好时重新询问。只有用户明确要求记住时，才将 `route=local` 或 `route=mineru-cloud` 写入操作系统用户数据目录 `MemoMinerUOCR/preferences.json`，不保存 Token，不把偏好带入发布仓库。更换路线需明确同意。

- **本地非 MinerU OCR**：读取 [references/local-ocr.md](references/local-ocr.md)。不请求 MinerU Token、不安装/调用 MinerU、不上传文件。遵循当前可用 PDF/图片技能处理，缺少引擎时说明可用选项并等待用户选择或安装授权。
- **MinerUOCR**：这里指官网托管云端，不等于 GitHub 项目的本地 CLI。先读取 [references/cloud-api.md](references/cloud-api.md)，并直接给出 Token 配置直达链接 [https://mineru.net/apiManage](https://mineru.net/apiManage)，引导注册与 Token 配置，确认本次文件/目录的上传范围后才调用。没有确认不得以“测试连通性”为由上传样页。
- 维护、安装和测试本技能不是 OCR 业务，不触发路线问题或索要 Token。

## MinerU 注册与 Token 引导

**Token 配置直达**：[https://mineru.net/apiManage](https://mineru.net/apiManage)（登录后创建/复制 Token；这是唯一需要打开的页面）。

明确给用户以下可点击路径，而不只说“给我密钥”：

1. 打开 [MinerU 官网](https://mineru.net/)，注册或登录。
2. 直接打开 [API 管理](https://mineru.net/apiManage)，创建 Token →复制；接口说明见 [官方 API 文档](https://mineru.net/apiManage/docs)。页面名称可能改变，以当前页面为准；不能把文档页当成已创建 Token。
3. 在使用者本机通过安全输入将 Token 交给当前进程环境变量 `MINERU_TOKEN`，或使用环境提供的秘密输入工具。不要让用户把 Token 直接贴在聊天、命令参数、技能文件或 GitHub 中；用户已经在聊天里给出时不要要求重发，按下一节流程处理并建议之后到 API 管理页轮换。PowerShell 安全输入示例见 cloud-api 参考；三种可用给法（当前进程安全输入、用户级环境变量、客户端秘密注入）见 [references/troubleshooting.md](references/troubleshooting.md)。

只检查变量是否存在，不显示值/长度/前后缀，不读取不相关凭据。Token 一旦出现在聊天或日志里，建议用户到 API 管理页轮换。没有安全输入通道时交由用户配置，暂停实际云端调用。不得代注册、代登录、购买套餐或猜收费。当前公开接口的配额不代表永久免费；正式批处理前重新确认官网限制和费用，收费或额度不足时停下询问。

## Token 配置（与墨卡大师一致）

云端路线确定后，按下面的顺序取 Token，不反复索要：

1. **本次明确指定**：用户在当前请求里提供或指定的 Token 优先；不静默被环境变量覆盖。失败也不自动换用旧 Token 或其他账户。
2. **用户级环境变量 `MINERU_TOKEN`**：没有本次指定时，存在且非空就直接用，视为已配置；只看是否存在，不打印值。
3. **都没有**：把直达链接 [https://mineru.net/apiManage](https://mineru.net/apiManage) 给用户，创建/复制 Token 后通过安全输入交给当前进程。

**用户本次提供了 Token 后，用问题框问一次是否存成用户环境变量**（仅当 `MINERU_TOKEN` 尚未设置）：

> 要把这个 Token 设为用户环境变量 `MINERU_TOKEN` 吗？**请确认这是你自己账户的 Token**——接错会消耗别人的额度。以后就不用每次输入。
>
> ① 是我自己的 Token，设置到用户环境变量（仅本机、当前 Windows 用户生效）
> ② 不用，仅本次使用

- 选①：用 `setx MINERU_TOKEN "<token>"` 或用户级环境变量 API 写入，不要回显 Token；写入会把 Token 放进这条命令，若环境会记录命令历史，提醒用户可以改由他本人在终端执行。成功只报 `token_env: set`，失败说明原因并继续用本次 Token。用户级变量仅影响新进程。
- 选②：只本次使用，不落盘，报 `token_env: session_only`。
- **提问必须用当前 Agent 的交互式问题框**（如 `ask_user_question`）；不得只写一句就结束回合，更不得直接终止对话。确实没有控件时才用文字，并写明「等你选择后继续」。
- **只配置用户自己的 Token**：他人、共享或来源不明的 Token 不得写入本机环境变量；来源存疑时先澄清。
- 任何情况下都不得把 Token 写进技能文件、状态、日志、Git、清单或交付报告。
- **Token 存在不等于上传授权**：每次云端上传范围仍需用户明确确认。

## 大文件工作流

先检查原文件格式、可读性、页数、大小、加密和大致版面。原件只读。PDF 可用 `pypdf` 做无损页对象拆分；它不是本地 OCR 引擎。不要先把整本转成低清图片；单页仍超限时停下说明，压缩或降采样需用户同意。

本技能脚本只依赖 Python 标准库，PDF 拆分另需 `pypdf`。优先查找已有运行时，缺依赖先说明；使用文件处理技能时读取其要求。脚本默认每片最多 150 页、180 MB（十进制），留出官网现行每文件 200 页、200 MB 限制的余量。限制是配置不是永恒保证；云端文档改变时先调整方案，不机械重试。

```text
python -B scripts/workflow.py prepare "原文件.pdf" "工作目录/job"
python -B scripts/workflow.py submit "工作目录/job/manifest.json" --chunk part-0001 --allow-upload
python -B scripts/workflow.py collect "工作目录/job/manifest.json" --chunk part-0001
python -B scripts/workflow.py merge "工作目录/job/manifest.json" "交付目录/完整文档"
python -B scripts/check_coverage.py "工作目录/job/manifest.json"
```

命令均以本技能目录为工作目录，或使用脚本绝对路径。`prepare`、`merge` 不联网；只有明确授权后才能传 `--allow-upload`。云端脚本针对官方 **v4 精准解析 API**，不是 MinerU 本地 4.0 `/v1` API；不要混用版本和字段。

`submit` 另有两个恢复向参数：`--replace-batch` 只用于「已建任务但文件始终没上传成功」的分片，旧 batch 记进 `abandoned_batches` 而不是被抹掉，已 `submitted` 的分片拒绝替换；`collect --no-proxy` 让本次请求忽略 `HTTP_PROXY/HTTPS_PROXY`，本机代理破坏结果下载时使用。完整执行顺序、坑与复核清单见 [references/troubleshooting.md](references/troubleshooting.md)。

1. **规划和拆分**：核对连续页段、文件哈希和每片实际字节数。脚本按固定连续页段分片，超大分片递归二分；如章节书签可明确改善边界，先规划页段再实现同等校验。不要声称固定分片自动识别了章节。
2. **确认上传**：说明文件名、总页数、分片数、云端服务和预计配额；用户明确要求云端处理当前文件通常已覆盖该范围，但历史路线偏好或 Token 本身不是上传授权。目录范围不明确时先问。
3. **提交和续跑**：按分片逐个 `submit`，默认 VLM 并保留表格/公式识别。清单记录 batch ID、状态与结果哈希；已提交分片不再新建任务。`collect` 每次只查询一次，未完成时稍后用同一命令继续，不启动后台死循环。并发和频率服从官网限制。
4. **失败处理**：认证失败、额度不足或请求限流时停下说明；429/暂时故障按官方建议有界退避。提交结果不明、上传结果不明时先查询已知任务，不盲目重提或产生重复计费。脚本不会持久化签名上传 URL；上传失败后若服务仍等待文件，先核实任务和用户是否接受新任务，再人工协调，不擅自抹去清单。
5. **有序合并**：全部分片成功后才生成正式成品。脚本校验完整页段、结果 ZIP 的哈希和安全路径，将素材按分片命名空间整理，重写常见 Markdown、引用式图片和 HTML `src/href` 的本地链接，拒绝缺失素材。不覆盖已有输出目录。远程素材仅保留引用并报告，不擅自联网补抓。
6. **语义与视觉复核**：先跑 `scripts/check_coverage.py` 拿逐页 blocks/字符数与表格块统计，再重点抽查每个分片的首尾、复杂表格/公式、图片引用和重复页眉。页段齐全只证明覆盖范围，不证明 OCR 无漏字。跨页表格或段落断裂时优先补解析边界窗口并根据原始页码替换对应内容；补解析本身仍受上传和配额授权约束。默认不重叠分片、不做模糊全文去重；脚本不自动把断表拼成“完美表格”。

## 交付与支链

交付 UTF-8 `document.md`、配套 `assets/` 和 `report.json`；需要时将整个目录打包。报告原始页数、分片页段、全部成功/部分成功状态、实际校验、待人工复核位置。失败或部分完成不能冒称完整成品。清单、源文件路径、任务状态和凭据留在工作区，不混入交付包或技能 Git 仓库。

交给墨卡大师时提供合并后的 Markdown、素材和页段定位，由 `memo-cardest` 决定知识拆解、题型与 Markji 语法；制卡前仍需遵守其专业版确认关卡。本技能不代替 `memo-txtimporter` 的 TXT 容器校验或 `memo-table` 的表格渲染。

本技能新建后的 GitHub 上传询问与版本发布由 `skill-publisher` 的内置 Memo 模式处理，不再调用单独的发布技能；用户已在本次请求明确要求上传时无需重复询问“要不要”，但目标仓库与可见性仍需确认。不得把 OCR 文档、Token 或运行清单随技能发布。

## 验证

`python -B scripts/test_workflow.py` 使用临时本地 PDF、模拟 API 和 ZIP，验证分片覆盖、大小限制、失败续跑、素材重命名、缺图/路径穿越拒绝及完整合并；另覆盖签名上传的空 `Content-Type`、`--replace-batch` 的 `abandoned_batches` 记录、`--no-proxy` 绕开环境代理、API 拒绝时回显 `code`/`msg`、传输错误报出 host，以及 `check_coverage.py` 对空页的判定。它不会访问真实 MinerU、使用真实 Token 或产生 OCR 费用。离线测试通过不代表真实云端联调成功。
