# 跑通路径与常见坑

本文件记录一次真实批处理（2026-10-16，两本 333 真题汇编扫描件，362 页）跑通后沉淀下来的执行顺序、坑与复核清单。
它只描述 **MinerU 官网精准解析 API** 路线；路线选择与授权边界见 [SKILL.md](../SKILL.md)。

## 一、可复用的执行顺序

每个 job 走一遍，全部命令都在技能目录里执行（或把脚本换成绝对路径）：

```text
# 0. 只读勘察：页数、大小、是否加密、有无文本层、有无书签
# 1. 拆分：生成分片与可恢复清单（不联网）
python -B scripts/workflow.py prepare "原文件.pdf" "工作目录/job"
# 2. 逐片提交（仅在确认上传范围后）
python -B scripts/workflow.py submit "工作目录/job/manifest.json" --chunk part-0001 --allow-upload
# 3. 逐片查询，未完成就稍后再来（传输层报错先加 --no-proxy）
python -B scripts/workflow.py collect "工作目录/job/manifest.json" --chunk part-0001 --no-proxy
# 4. 全部分片 done 后合并交付（不联网、不覆盖已存在目录）
python -B scripts/workflow.py merge "工作目录/job/manifest.json" "交付目录/完整文档"
# 5. 复核逐页覆盖与表格
python -B scripts/check_coverage.py "工作目录/job/manifest.json"
```

1. **勘察**：用 pypdf 读页数并确认未加密。运行时的 Python 没有 pypdf 时，装到工作区而不是运行时本体：
   `python -m pip install pypdf --no-deps --target <工作区>/tools`，之后用 `PYTHONPATH=<工作区>/tools` 调用脚本。
2. **拆分**：有书签可以先按书签规划页段；**没有书签就按固定连续页段切**，不要事后声称「自动按章节切分」。默认每片 ≤150 页 / 180 MB（官网上限 200 页 / 200 MB）。
3. **提交**：一次一片，清单里记 batch ID 后再上传。上传范围要用户明确授权；历史路线偏好或本机有 Token 都不算授权。
4. **查询**：`collect` 每次只查一次，未完成稍后再来，不写后台死循环；不因为慢就重提任务。
5. **合并**：全部 `done` 才生成成品。脚本会校验页段、结果哈希、ZIP 安全路径与本地素材引用。
6. **复核**：见第四节。页段齐全只证明覆盖范围，不证明 OCR 无漏字。

## 二、坑与判断方法

### 1. 上传 403 `SignatureDoesNotMatch`（旧版本存在，已修）

- **现象**：`submit` 报 `HTTP 403 from mineru.oss-cn-shanghai.aliyuncs.com`，清单停在 `upload_unknown`，云端任务状态是 `waiting-file`。
- **根因**：Python 的 urllib 会给任何带 body 的请求自动补 `Content-Type: application/x-www-form-urlencoded`；OSS 把这个头计入待签名字符串，而签名是对「空 Content-Type」生成的，于是签名对不上。
- **修法**：PUT 时显式传 `"Content-Type": ""`（现版本已内置）。不要改成 `Content-Type: application/octet-stream`，那同样会破坏签名。
- **判断技巧**：报错里的 host 会区分两类 403 —— `*.aliyuncs.com` 是上传签名问题，`mineru.net` 是额度/限流/权限。

### 2. 结果 ZIP 下载 `SSLEOFError`（本机代理）

- **现象**：`collect` 报 `Cloud transport failed`；但同样的进程访问 `api.mineru.net` 完全正常，只有 `cdn-mineru.openxlab.org.cn` 断流。
- **根因**：本机 HTTP(S)_PROXY（例如 Clash `127.0.0.1:7897`）与该 CDN 的握手失败。Python 对 `NO_PROXY` 的处理在部分版本上并不可靠（键名会被解析成 `no`），别指望它。
- **修法**：`collect` 加 `--no-proxy`。`api.mineru.net` 与结果下载域名直连通常都通，只有代理会破坏后者。
- **不要因此重提任务**：查询与下载都是只读的，重跑 `collect` 不会重新 OCR、不产生费用。

### 3. 401 / 403 / `code != 0` 怎么分

| 现象 | 含义 | 处理 |
|---|---|---|
| `HTTP 401` 且正文 `login required` | 请求没带 Token | 确认 `MINERU_TOKEN` 传进了执行命令的那个进程 |
| `HTTP 403 from mineru.net` | 额度、限流或权限 | 停下核对官网配额与频率，不要硬刷 |
| `HTTP 403 from *.aliyuncs.com` | 签名上传被拒 | 见坑 1 |
| `code=-10001, msg=...` | API 信封错误 | 报错已带 code/msg；按提示查 Token、配额或参数 |

报错**不打印**响应正文与签名 URL：上传失败的正文含 OSS AccessKeyId 与签名。诊断时也不要把它们贴进聊天、日志或仓库。

### 4. `waiting-file` 与 `--replace-batch`

- 上传没走完的分片会停在 `waiting-file`；签名上传地址不持久化，**同一 batch 无法续传**。
- 正确顺序：先 `collect` 核实任务状态 → 确认服务端确实没收到文件 → `submit --replace-batch`。旧 batch 会记进 `abandoned_batches`，不会被抹掉。
- 已经 `submitted` 的分片会拒绝替换，避免产生重复任务。
- 从未上传文件的空 batch 不会产出 OCR 结果，也不消耗页额度。

### 5. 不要手动把清单改回 `prepared`

`submission_unknown` / `upload_unknown` 是刻意的保守状态：请求可能已经到达服务端。先 `collect` 查任务，再决定替换还是继续等。

### 6. Token 的三种给法（都不进聊天、不进文件、不进仓库）

1. **当前进程安全输入**（推荐）：见 [cloud-api.md](cloud-api.md) 的 PowerShell 示例。
2. **用户级环境变量**：用户在自己的终端用 `Read-Host -AsSecureString` 输入后
   `[Environment]::SetEnvironmentVariable('MINERU_TOKEN', <明文>, 'User')`；Agent 每次执行命令时用
   `$env:MINERU_TOKEN = [Environment]::GetEnvironmentVariable('MINERU_TOKEN','User')` 取进当前进程。
   结束或轮换后用 `[Environment]::SetEnvironmentVariable('MINERU_TOKEN', $null, 'User')` 清除。
3. **客户端秘密注入机制**（若所用客户端支持）。

外部终端里设置的变量不会自动传进已经启动的桌面 Agent。Token 一旦出现在聊天或日志里，建议到 [API 管理](https://mineru.net/apiManage) 轮换一次；不得用「测试连通性」当借口上传样页。

### 7. Windows 控制台中文乱码

`Get-Content` 或控制台可能把 UTF-8 中文显示成乱码，**文件本身没问题**。判断结果请看 JSON 字段（`status` / `state`）、或用 `-Encoding UTF8`、或写进文件再读；不要据乱码判定 OCR 失败。

### 8. 频率与并发

`collect` 每次只查一次；未完成就稍后再来。429/暂时故障按官网建议有界退避，退避仍失败就整轮停下报告，不硬刷。

## 三、分片与边界

- 无书签的扫描书：固定页段是最稳的切法，页段连续且可机械校验。
- 原书**印刷页码与 PDF 页序常有偏移**（例如解析册 PDF 第 151 页印的是页码 147）。写引用时以 PDF 页序为准并说明口径，不要混用。
- 合并后的 `document.md` 用 `<!-- Source pages X-Y; part-000X -->` 标出每片页段，方便回溯。

## 四、复核清单（页段齐全 ≠ OCR 正确）

1. `python -B scripts/check_coverage.py <manifest.json>`
   - 逐页 blocks 与字符数，列出**没有任何内容块**的页与极短页（通常是章节隔页、封面、封底，需渲染确认）。
   - 表格块统计：多少块、多少块带真实 HTML 行、多少块是空的。
2. **边界页**：把每片的首页与末页从原 PDF 渲染成图，与合并后的 Markdown 对照，确认无重叠、无缺页。
3. **表格**：MinerU 对复杂表常用 HTML `<table>`（含 `rowspan`/`colspan`），不是 Markdown 管道表；用 `<table>` 出现次数与云端表格块数对账。跨页大表的「续表」会被切成多段，需要人工拼。
4. **版面示意与公式**：`$...$` 行内公式、以及 `\left\{\begin{array}{l}...\right.` 这类花括号阵列（其实是版面示意图），制卡或二次加工前要展开成纯文本。
5. **页眉页脚与标题残字**：例如重复的 `## <书名>(解析册)`、`## - 答案要点` 这类带破折号残字的标题，交给下游前先剥离。
6. **图片**：图片引用必须都能在 `assets/<part>/` 找到；合并会拒绝缺图，但误判为图片的版面区域仍需肉眼抽查。

## 五、本次实测基线

| 项 | 解析册 | 试题册 |
|---|---|---|
| 页数 / 体积 | 230 页 / 132.6 MB | 132 页 / 73.7 MB |
| 分片 | p1-150、p151-230 | p1-132 |
| 逐页覆盖 | 150/150、80/80 | 132/132 |
| 字符量（约） | 163,012 + 96,793 | 123,486 |
| 表格（带 HTML 行） | 36 + 1 | 7 |
| 成品 | 9176 行 / 728 KB | 5230 行 / 327 KB |

命令、参数与本文一致：默认 150 页 / 180 MB，`vlm` + 表格 + 公式 + 中文。
