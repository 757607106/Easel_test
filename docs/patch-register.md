# 本地补丁登记表

目标仓库：`757607106/Easel_test`；更新来源：`ZJU-REAL/Easel`。
本次固定升级到 `v0.3.0`（`bb3c8ff0463f36c202454d74171682ba6e470cb1`）。
升级前基线：`ed05c2b`，包版本 `0.2.1`。

合并上游前逐项检查这些文件。优先采用上游实现，在协议边界保留阿里云行为；不要直接覆盖整个设置页或执行引擎。
当前 `.env`、API Key、OpenClaw profile、账号登录和 `outputs/` 属于本机状态，不进入 Git 提交。

| 补丁 | 文件 | 必须保留的行为 | 回归入口 |
| --- | --- | --- | --- |
| ALI-01 生图 | `skills/shared/scripts/ai_image.py`、`.env.example` | 独立 `IMG_*` 配置；缺少图片模型时不回落到 `OPENAI_MODEL`；阿里云图片编辑走 `/images/generations` 的 `image` 字段 | `tests/test_aliyun_media.py`，文生图与编辑协议 |
| ALI-02 视频 | `skills/shared/scripts/ai_video.py` | 万相统一视频端点、真实像素尺寸、文生/图生模型选择 | `tests/test_aliyun_media.py`、`tests/test_ai_video_env.py` |
| ALI-03 配音 | `skills/shared/scripts/voice_clone.py` | 千问 TTS 预置音色、原生接口、WAV/MP3 正确格式、根地址仅出现一次 `/api/v1` | `tests/test_aliyun_media.py`，配音与转码 |
| ALI-04 转写 | `skills/shared/scripts/aliyun_asr.py`、`skills/shared/scripts/asr.py`、`skills/shared/scripts/model_registry.py`、`web/app.py` | `ASR_PROVIDER=dashscope`，四分钟分段、真实时间戳、设置页读写；保留本地 whisper | `tests/test_aliyun_media.py`，跨段字幕偏移与配置保存 |
| ALI-05 音乐 | `skills/shared/scripts/ai_music.py`、`skills/shared/scripts/model_registry.py` | 可用的 `qwen-audio-3.1-tts-next` 音频协议；保留 Fun-Music 正确的同步协议；不把待授权模型标为可用 | `tests/test_aliyun_media.py`，两种音频响应 |
| ALI-06 状态展示 | `web/app.py`、`web/frontend/src/components/SettingsPanel.tsx` | 显示阿里云供应商；配置状态与实时在线分开；实测记录按模型、地址、凭据摘要匹配；保留上游新执行引擎 UI | `tests/test_aliyun_media.py`、前端构建、实际设置页 |
| ALI-07 测试隔离 | `tests/test_web_anthropic_slot.py`、`tests/test_aliyun_media.py` | 模拟探针不依赖本机 VPN DNS，不读取用户真实认证 | `pytest -q` |
| ALI-08 网关流收尾 | `web/app.py`、`tests/test_gateway_http_completion.py` | HTTP 对话按本次响应的 `finish_reason=stop` 和 `[DONE]` 判断正常结束；共享日志乱序不得误报，断流和长度截断仍须告警 | 完整 / 断流 / 长度截断协议回归、真实 Web 对话 |
| LOCAL-01 已有安装修复 | `setup.sh` | 保留升级前已有的 `${MEM_PREFIX}` / `${EMBEDDING_MODEL}` 插值修复 | 安装脚本语法检查、上游安装测试 |
| GOV-01 维护文档 | `docs/aliyun-models.md`、`docs/patch-register.md`、`docs/upstream-upgrade.md`、`docs/adr/0001-aliyun-provider-boundaries.md` | 固定版本、补丁与协议来源可追踪 | 文档路径校验、升级验收记录 |

## 验收范围

本仓库是 Easel，没有 CowAgent 的根目录 legacy `app.py`、`cow platform doctor`、platform API / worker、`agent_id / binding_id`、usage / quota / audit 独立入口。
这些步骤对本次升级不适用，不用新增占位实现伪造通过。
对应验收实际存在的 `easel` CLI、`web/app.py`、OpenClaw 网关、会话和工具执行，以及阿里云六个模型通道。

## 升级记录

- 2026-10-13：登记现有阿里云适配，升级工作在 `codex/upgrade-easel-v0.3.0-aliyun` 独立分支执行。
- 合并前已逐项比对：`skills/shared/scripts/` 中登记的媒体脚本和 `.env.example` 在这九个上游提交中均未改动。
- `setup.sh`、`web/app.py` 自动合并；设置页的唯一文本冲突采用上游执行引擎和 API 预览结构，保留本地主通道配置判据和媒体实测状态。
- 上游迁移到 `agents/`、`skills/builtin/` 的路径按上游布局保留，不恢复旧技能目录。
- 真实对话发现共享 raw 日志在 `assistant_message_end` 后补写正文，导致完整回答误报中断；HTTP 收尾改为验证本请求的 SSE 标记，保留截断和错误告警。
- 升级分支全量 `pytest -q`：1284 通过、6 跳过；前端测试：71 通过；前端 lint 和生产构建通过（保留上游已有非阻断警告）。
- 文档路径、306 条技能命令、114 个技能契约及安装 / 同步 / 网关脚本语法校验通过。
- 新版 CLI 环境检查全部通过、网关联通性检查通过；隔离端口启动 Web，六通道配置及匹配的历史实测结果完整。
- 真实 Web 对话约 2.8 秒返回“升级测试通过”，保存 `clean_end=true`、`stop_reason=stop`；补充八种正常 / 截断 / 错误收尾回归。
- 本机 `.env` 与 OpenClaw 配置对比私有备份无变化；旧技能目录中无需要迁移的非缓存本机配置。工作区文档已另行备份，更新采用仅文档同步，保留 USER、MEMORY、账号、画像与产物。
