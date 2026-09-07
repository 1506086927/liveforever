# B 站字幕提取脚本

`bili_subtitles.py` —— 给一个 B 站 URL，把**视频**或**视频系列**（分P / 合集 / 系列）的字幕批量抓下来，保存成 SRT / TXT / JSON / LRC。

- **零依赖**：只用 Python 标准库（Python 3.8+），不需要 `pip install` 任何东西，也不需要 ffmpeg。
- 原理参考 [9Kun/bilibili-media-hub](https://github.com/9Kun/bilibili-media-hub)，本脚本只保留“取字幕”这条链路并重写为单文件。

## 快速开始

```bash
# 1. 设置登录 Cookie（强烈建议，见下文）
export BILI_COOKIES="SESSDATA=你的SESSDATA值"

# 2. 抓单个视频
python3 tools/bili_subtitles.py "https://www.bilibili.com/video/BV1xx411c7mD"
```

字幕默认写到 `./subtitles/` 目录。

## 常用命令

| 目的 | 命令 |
| --- | --- |
| 先看看有没有字幕、有哪些语言 | `python3 tools/bili_subtitles.py BV1xx411c7mD --list` |
| 只抓某一个分P | `python3 tools/bili_subtitles.py "https://www.bilibili.com/video/BV1xx?p=3"` |
| 抓全部分P | `python3 tools/bili_subtitles.py BV1xx --all-parts` |
| 只抓第 1、3、5–8 个分P | `python3 tools/bili_subtitles.py BV1xx --pages "1,3,5-8"` |
| 抓这个视频所属的整个合集 | `python3 tools/bili_subtitles.py BV1xx --season` |
| 抓 UP 主空间里的合集 | `python3 tools/bili_subtitles.py "https://space.bilibili.com/123/channel/collectiondetail?sid=456"` |
| 抓空间里的「系列」 | `python3 tools/bili_subtitles.py "https://space.bilibili.com/123/channel/seriesdetail?sid=789"` |
| 同时输出多种格式 | `python3 tools/bili_subtitles.py BV1xx -f srt,txt,json` |
| 只要人工/UP主 CC 字幕，不要 AI 字幕 | `python3 tools/bili_subtitles.py BV1xx --no-ai` |
| 把整套字幕合并成一篇 Markdown 文稿 | `python3 tools/bili_subtitles.py BV1xx --season --merge` |
| 指定输出目录 | `python3 tools/bili_subtitles.py BV1xx -o 字幕/内膜癌手术` |

支持的输入：完整视频 URL、`b23.tv` 短链、`space.bilibili.com` 合集/系列链接（含新版 `/lists/<sid>?type=season`）、播放列表 URL，以及直接给 `BV` 号或 `av` 号。

## 关于登录 Cookie（最关键的一步）

B 站的字幕清单接口对**未登录**请求几乎总是返回空列表，所以没有 Cookie 时大概率一条字幕也拿不到。获取方式：

1. 浏览器登录 bilibili.com；
2. F12 → Application/存储 → Cookies → `https://www.bilibili.com` → 复制 `SESSDATA` 的值；
3. 三选一传给脚本：

```bash
export BILI_COOKIES="SESSDATA=xxxx; bili_jct=yyyy"     # 推荐：环境变量，不落盘
python3 tools/bili_subtitles.py BV1xx --cookie "SESSDATA=xxxx"
python3 tools/bili_subtitles.py BV1xx --cookie-file cookies.txt   # 支持浏览器导出的 Netscape 格式
```

> `SESSDATA` 等价于你的登录态，**不要提交到 Git、不要分享给别人**。本仓库的 `.gitignore` 已忽略 `cookies.txt` 与 `subtitles/` 输出目录。

## 输出示例

```
subtitles/
├── 手术要点讲解_P01_开场.zh-CN.srt
├── 手术要点讲解_P02_分期.ai-zh.srt
└── 手术要点讲解_合并文稿.md        # 仅 --merge 时生成
```

- `.srt`：标准字幕，时间戳 `HH:MM:SS,mmm`，可直接给播放器或剪辑软件用。
- `.txt`：纯文本（加 `--txt-with-time` 可带时间戳），适合直接读或喂给大模型总结。
- `.json`：带 `bvid / cid / 分P / 语言 / 每条起止秒数`，方便二次处理。
- `.lrc`：歌词格式。
- `--merge`：把整个系列拼成一篇带时间戳的 Markdown，适合整体阅读或让 AI 做全系列摘要。

## 工作原理

1. 解析 URL → BV 号（短链自动跟随跳转；空间合集/系列先调列表接口展开成 BV 号清单）。
2. `GET /x/web-interface/view` → 拿标题、`pages[].cid`（分P）、`ugc_season`（合集）。
3. `GET /x/player/wbi/v2?bvid=&cid=` → 拿 `data.subtitle.subtitles[]`。
   该接口需要 **WBI 签名**：从 `/x/web-interface/nav` 取 `wbi_img` 的两段文件名拼接，按固定 64 位混淆表取前 32 位得到 `mixin_key`，再对排序后的查询串做 `md5(query + mixin_key)` 得到 `w_rid`。脚本同时会预热 `buvid3/buvid4/_uuid` 等指纹 Cookie 以降低风控概率；万一 wbi 接口出错会自动回退到 `/x/player/v2`。
4. 按语言优先级挑一条字幕轨（默认 `zh-Hans → zh-CN → zh-Hant → zh-TW → ai-zh → en-US`，`ai-` 前缀是 AI 智能字幕）。
5. 拉取字幕 JSON（`{"body":[{"from":0.5,"to":2.3,"content":"..."}]}`）并转成目标格式落盘。

请求之间默认间隔 0.4 秒（`--delay` 可调），失败自动重试 3 次（`--retries`）。

## 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 全部提示「没有可用字幕」 | 90% 是没配 Cookie；配好 `BILI_COOKIES` 再试。也可能该视频真的没做字幕，用 `--list` 确认。 |
| `code=-352` / 请求频繁 | 触发风控，加大 `--delay`（如 `--delay 1.5`）或换会儿再跑。 |
| 番剧 / 电影链接（ep、ss） | 不支持，接口和版权限制都不同，脚本会直接给出提示。 |
| 想要没有字幕的视频的文字稿 | 本脚本不做语音转录；需要的话可用 [bilibili-media-hub](https://github.com/9Kun/bilibili-media-hub) 的 FunASR 本地转录。 |

## 测试

```bash
python3 tools/test_bili_subtitles.py -v      # 34 个离线单测，不联网
```

覆盖 URL 解析（含短链、合集、系列、番剧拒绝）、WBI 签名正确性、语言优先级选择、SRT/TXT/JSON/LRC 转换、文件名清洗、Cookie 载入以及「列表→字幕→落盘→合并」的端到端流程（用假客户端模拟接口）。

## 免责声明

仅供个人学习与资料整理使用，请遵守 B 站用户协议与相关法律法规，不要用于批量抓取或二次分发受版权保护的内容。
