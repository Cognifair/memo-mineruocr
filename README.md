# Memo-MinerUOCR

把 PDF、扫描材料和文档图片转为便于阅读与后续制卡的 Markdown。针对大 PDF，支持按页数与实际大小拆分、云端分片识别、断点续跑，以及按原页序合并正文和图片素材。

调用名：`$memo-mineruocr`。当前版本以 [SKILL.md](SKILL.md) 的 `metadata.version` 和 [version.json](version.json) 为准。

本技能可独立使用，也可作为「墨卡大师 Memo-Cardest」的材料识别支链。它不负责知识拆解、制卡或向墨墨记忆卡写入内容。

## 第一次使用

Agent 必须先询问，并等待你选择：

> 使用本地非 MinerU OCR，还是使用 MinerUOCR（官网云端，需要上传文件并配置 Token）？

- 本地非 MinerU OCR：使用已安装且可用的本地工具，例如 PaddleOCR 或 Tesseract；不调用 MinerU、不索要 MinerU Token，也不上传材料。原生文字 PDF 可先直接提取文本。没有可用引擎时会说明，不假装已经识别完成。
- MinerUOCR：调用 [MinerU 官网](https://mineru.net/) 托管的解析 API，不是安装 [MinerU 开源项目](https://github.com/opendatalab/mineru) 后在本地运行。只有确认本次文件上传范围后才发送材料。

已有 Token 不代表同意云端上传，路线失败也不会自动切换另一条路线。维护或测试技能不触发 OCR 选择问题。

## 使用示例

把文件交给支持本地技能的 Agent，例如：

> 使用 Memo-MinerUOCR，把这份大 PDF 转为完整 Markdown。先让我选择识别路线；如果超过限制，拆分识别后按原页序合并，保留图片和公式，并报告需要复核的位置。

安装时，将整个技能目录放到目标 Agent 已配置的技能目录中，保留目录名 `memo-mineruocr`。不同客户端的技能发现与刷新方式不同；放入目录不等于启用了后台任务。

## MinerU 注册与 Token 配置

**Token 配置直达**：[https://mineru.net/apiManage](https://mineru.net/apiManage)（登录后创建/复制 Token）。

1. 打开 [MinerU 官网](https://mineru.net/)，自行注册或登录。
2. 打开上面的 API 管理页，创建 Token →复制；接口说明见 [官方 API 文档](https://mineru.net/apiManage/docs)。页面名称以官网当前界面为准。
3. 使用客户端的安全凭据注入机制，或在执行命令的终端安全输入，把 Token 提供给当前进程环境变量 `MINERU_TOKEN`。具体 PowerShell 示例见 [云端 API 与安全凭据](references/cloud-api.md)。
4. 若你本次提供了 Token 且尚未设置用户变量，技能会用问题框问一次是否写入用户环境变量 `MINERU_TOKEN`（仅本人 Token；`setx` 或用户级变量 API，不回显）。写入后新会话直接读取，不再重复输入；不写入则仅本次使用。

不要把 Token 发在聊天里、写进命令参数、README、配置文件或 GitHub。外部终端的环境变量不会自动传给已经启动的桌面 Agent；需要在同一终端执行云端命令，或使用客户端真正支持的安全注入方式。Token 存在不等于上传授权，每次云端上传范围仍需确认。

### 免费还是付费？

本技能不收取独立服务费，也不包含 MinerU 付费额度。本地路线的计算资源与模型成本由所选工具决定；云端的额度、优先级和费用以 MinerU 官网当前规则为准，不承诺永久免费，也不代你购买套餐。

随技能提供的参考资料记录于 2026-10-16：官网精准接口每文件上限为 200 页、200 MB；每日 1000 页指最高优先级额度，不代表无限免费额度。真实批处理前应重新核对当前规则，额度或费用不明确时先停下确认。

## 大 PDF 如何处理

1. 检查原件的页数、大小、加密与版面，不改动原文件。
2. 默认拆成每片最多 150 页、180 MB（十进制），为云端限制留余量；按拆分后的实际字节数检查，必要时继续二分。单页仍超限时停止说明，不擅自降低画质。
3. 确认上传范围后，逐片提交云端任务；保存 batch ID 和状态，避免重复提交与潜在重复计费。
4. 未完成时使用同一任务继续查询。下载失败可重试获取结果，不需要重新提交 OCR；提交或上传状态不明确时保留现场，不盲目重提。
5. 全部分片完成后，校验连续页段与结果哈希，按原页序合并。每片图片放入独立素材目录，并改写常见 Markdown / HTML 本地引用，避免同名图片冲突。
6. 抽查各分片首尾、表格、公式与图片。跨页表格、复杂自定义链接和 OCR 漏字仍需人工复核，不承诺自动恢复所有版面。

默认不重叠拆分、不模糊去重、不自动删正文，也不把部分结果当作完整成品。

## 脚本用法

需要 Python 3；PDF 拆分另需 `pypdf`。云端 HTTP、ZIP 与清单处理使用 Python 标准库，不需要安装完整 MinerU 或 GPU 环境。先使用已有运行时；缺少依赖时按当前环境的安装授权处理。

以下命令在本技能目录中执行，或将脚本换成绝对路径。当前内置自动化脚本针对 PDF；图片或其他格式应使用所选路线实际支持的工具，不直接套用 PDF 拆分命令。

```text
# 只读原件，生成分片与可恢复清单；不联网
python -B scripts/workflow.py prepare "原文件.pdf" "工作目录/job"

# 仅在确认云端上传后执行；Token 通过安全环境变量提供
python -B scripts/workflow.py submit "工作目录/job/manifest.json" --chunk part-0001 --allow-upload

# 每次查询一次；未完成时之后继续执行同一命令
python -B scripts/workflow.py collect "工作目录/job/manifest.json" --chunk part-0001

# 所有分片完成后生成正式交付目录；不联网、不覆盖已有目录
python -B scripts/workflow.py merge "工作目录/job/manifest.json" "交付目录/完整文档"

# 复核逐页覆盖与表格块；只读结果 ZIP
python -B scripts/check_coverage.py "工作目录/job/manifest.json"
```

对清单中的每个分片分别执行 submit / collect；不要只处理示例中的 `part-0001`。可通过 prepare 的 `--max-pages` 和 `--max-mb` 调整限制，但须符合官网当前约束。

两个可选参数：

- `collect --no-proxy`：本次请求忽略 `HTTP_PROXY/HTTPS_PROXY`。本机代理（Clash 等）会让结果下载域名握手失败时使用。
- `submit --replace-batch`：只用于「任务已创建但文件始终没上传成功」的分片；旧 batch 记进 `abandoned_batches` 而不会被抹掉，已 `submitted` 的分片拒绝替换。

执行顺序、坑与复核清单见 [references/troubleshooting.md](references/troubleshooting.md)。

脚本使用官网 v4 精准解析 API，默认 VLM 并启用表格/公式识别；不与开源 MinerU 本地服务的 `/v1` 接口混用。本地非 MinerU 路线可以复用 PDF 拆分，但本地输出须按真实格式合并，不能伪造云端任务清单。

## 交付内容

```text
完整文档/
├── document.md
├── assets/
│   ├── part-0001/...
│   └── part-0002/...
└── report.json
```

报告包含页段覆盖与校验结果；Agent 同时说明采用的路线、完整或部分状态、实际复核与已知限制。只有结果确实包含素材时才交付对应图片。云端结果合并会拒绝危险 ZIP 路径、缺失的本地素材以及不完整页段。

原文件、分片、运行清单和任务状态留在工作区，不进入技能仓库或成品包。后续制卡可把 Markdown 和素材交给 Memo-Cardest，但不会自动写入卡片。

## 文件与验证

- [SKILL.md](SKILL.md)：Agent 执行规则和授权边界。
- [references/local-ocr.md](references/local-ocr.md)：本地非 MinerU 路线。
- [references/cloud-api.md](references/cloud-api.md)：注册、Token、官网接口与续跑说明。
- [references/troubleshooting.md](references/troubleshooting.md)：跑通路径、常见坑（上传签名 403、代理断流、`waiting-file` 恢复、Token 给法）与复核清单。
- [scripts/workflow.py](scripts/workflow.py)：PDF 拆分、提交、收集与合并。
- [scripts/check_coverage.py](scripts/check_coverage.py)：逐页覆盖与表格块复核，只读结果 ZIP。

```text
python -B scripts/test_workflow.py
```

测试使用临时 PDF、模拟 API 和 ZIP，不访问真实 MinerU、不使用真实 Token、不产生 OCR 费用。离线测试通过不等于真实云端联调成功。

技能的首次 GitHub 上传询问与版本更新由 Skill Publisher 的内置 Memo 模式处理，不依赖单独的 Memo-Publisher。文档处理授权不等于发布技能的授权。

## Memo 系列

<!-- memo-series:begin -->
| 技能 | 职责 |
|---|---|
| [墨卡大师 Memo-Cardest](https://github.com/Cognifair/memo-cardest) | 核心制卡：知识拆解、题型、正文语法与牌组操作 |
| [墨记表格制作 Memo-Table](https://github.com/Cognifair/memo-table) | 表格图片与 LaTeX array 表格渲染 |
| [墨记文档导入 Memo-Txtimporter](https://github.com/Cognifair/memo-txtimporter) | TXT 容器格式、分卡校验与图片回填 |
| [迁墨 Memo-Ankitransfer](https://github.com/Cognifair/memo-ankitransfer) | Anki 图片挖空转墨墨原生遮罩 |
| [Memo-QAhelper](https://github.com/Cognifair/memo-qahelper) | 墨墨记忆卡使用答疑（官方百科与论坛） |
<!-- memo-series:end -->

## License

[MIT](LICENSE)
