# 阿里云模型通道

聊天、生图、视频、配音、转写和音乐分别使用对应能力的模型，不把聊天模型作为媒体模型的默认值。
同一北京地域的百炼 API Key 可在获得访问权限后供各通道使用。

| 通道 | 本机配置模型 | 接口 |
| --- | --- | --- |
| 聊天 | `qwen3.7-plus` | `/compatible-mode/v1/chat/completions`，通过 OpenClaw 执行技能 |
| 生图、图片编辑 | `qwen-image-3.0` | `/compatible-mode/v1/images/generations`，编辑图像使用 `image` 字段 |
| 文生视频 | `wan2.6-t2v` | `/api/v1/services/aigc/video-generation/video-synthesis`，异步任务 |
| 图生视频 | `wan2.6-i2v` | 同上，通过 `DASHSCOPE_I2V_MODEL` 可独立指定 |
| 配音 | `qwen3-tts-flash`，默认音色 `Cherry` | `/api/v1/services/aigc/multimodal-generation/generation` |
| 转写 | `qwen-audio-3.0-asr-flash` | 同上，本地音频以 Base64 上传，使用真实词级时间戳生成字幕 |
| 音乐 / BGM | `qwen-audio-3.1-tts-next` | `/api/v1/services/audio/tts/SpeechSynthesizer`，同步音频响应 |

`DASHSCOPE_BASE_URL` 使用业务空间域名加 `/api/v1`；`IMG_BASE_URL` 使用同一域名加 `/compatible-mode/v1`。
凭据保存在忽略提交的 `.env` 和 OpenClaw profile 中。修改前的本机备份放在 `~/.openclaw-easel/backups/`。

`ASR_PROVIDER=dashscope` 启用云转写；`ASR_PROVIDER=local` 使用原有 faster-whisper。
云转写按四分钟分段处理长音频，结果按累计时长拼接。配音返回 WAV，输出 MP3 时通过 ffmpeg 转码。
音乐的 `--duration` 作为提示写入文本，实际时长由模型决定。
可选的 `fun-music-v1` 走 `/api/v1/services/audio/music/generation`；本机账号实测返回 403，需另行申请访问权限，因此默认使用已成功调用的千问音频生成模型。

本机实测记录在 `outputs/_install/model-verification.json`，测试产物在 `outputs/阿里云通道验证/`。
设置页只对匹配模型、地址和凭据的记录显示“上次实测通过”，不把“已配置”当成实时在线状态。

协议来源：[千问生图](https://help.aliyun.com/en/model-studio/qwen-image-generation-and-editing-api-reference)、[万相视频](https://help.aliyun.com/zh/model-studio/legacy-wan-text-to-video-api-reference)、[千问配音](https://help.aliyun.com/en/model-studio/qwen-tts-api)、[Flash 转写](https://help.aliyun.com/en/model-studio/fun-asr-flash-recorded-speech-recognition-http-api)、[千问音频生成](https://help.aliyun.com/en/model-studio/audio-generation-api)、[Fun-Music](https://help.aliyun.com/en/model-studio/fun-music-api)。
