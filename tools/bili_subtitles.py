#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B 站字幕提取脚本（单文件，零第三方依赖，仅用 Python 标准库）

原理参考：https://github.com/9Kun/bilibili-media-hub
    1. 解析 URL -> BV 号（b23.tv 短链自动跟随重定向）
    2. /x/web-interface/view 拿视频信息：分P 列表（pages[].cid）与合集信息（ugc_season）
    3. /x/player/wbi/v2?bvid=&cid=  （需要 WBI 签名 + 指纹 Cookie）拿字幕清单
       响应路径：data.subtitle.subtitles[] -> {lan, lan_doc, subtitle_url}
    4. 拉取字幕 JSON（{"body":[{"from":0.5,"to":2.3,"content":"..."}]}）
    5. 转成 SRT / TXT / JSON / LRC 落盘

支持的输入 URL：
    - 单个视频 / 分P：  https://www.bilibili.com/video/BV1xx411c7mD?p=3
    - 短链：            https://b23.tv/xxxxxxx
    - 视频合集(ugc_season)：视频页 URL + --season
    - 空间合集：        https://space.bilibili.com/<mid>/channel/collectiondetail?sid=<sid>
                        https://space.bilibili.com/<mid>/lists/<sid>?type=season
    - 空间系列：        https://space.bilibili.com/<mid>/channel/seriesdetail?sid=<sid>
                        https://space.bilibili.com/<mid>/lists/<sid>?type=series
    - 也可以直接传 BV 号 / av 号

关于登录 Cookie（重要）：
    B 站字幕接口对未登录请求经常返回空清单。想稳定拿到 CC / AI 字幕，请提供 Cookie：
        export BILI_COOKIES="SESSDATA=xxxx; bili_jct=yyyy; buvid3=zzzz"
    或  --cookie "SESSDATA=xxxx"
    或  --cookie-file cookies.txt   （支持浏览器导出的 Netscape 格式，或单行 Cookie 头）

用法示例：
    python bili_subtitles.py "https://www.bilibili.com/video/BV1xx411c7mD"
    python bili_subtitles.py "https://www.bilibili.com/video/BV1xx411c7mD?p=2" --format srt,txt
    python bili_subtitles.py "https://www.bilibili.com/video/BV1xx411c7mD" --all-parts
    python bili_subtitles.py "https://www.bilibili.com/video/BV1xx411c7mD" --season -o 字幕
    python bili_subtitles.py "https://space.bilibili.com/123/channel/collectiondetail?sid=456"
    python bili_subtitles.py "BV1xx411c7mD" --list        # 只列出有哪些语言的字幕
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from dataclasses import dataclass, field
from http.cookiejar import Cookie, CookieJar, LoadError, MozillaCookieJar
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__version__ = "1.0.0"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

API_VIEW = "https://api.bilibili.com/x/web-interface/view"
API_PLAYER_WBI_V2 = "https://api.bilibili.com/x/player/wbi/v2"
API_PLAYER_V2 = "https://api.bilibili.com/x/player/v2"
API_NAV = "https://api.bilibili.com/x/web-interface/nav"
API_FINGER_SPI = "https://api.bilibili.com/x/frontend/finger/spi"
API_SEASON_ARCHIVES = "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list"
API_SERIES_ARCHIVES = "https://api.bilibili.com/x/series/archives"

# WBI 混淆表
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

# 默认语言优先级：人工/UP主 CC 简体 > 繁体 > AI 简体 > 英文
DEFAULT_LANG_PRIORITY = ["zh-Hans", "zh-CN", "zh-Hant", "zh-TW", "ai-zh", "en-US", "ai-en"]


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #
class BiliError(Exception):
    """脚本内部统一异常。"""


class NoSubtitleError(BiliError):
    """该分P没有可用字幕。"""


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Part:
    """一个分P（或合集中的一集）。"""
    bvid: str
    cid: int
    page: int
    part_title: str
    video_title: str
    owner: str = ""
    duration: int = 0
    # 合集内的序号（用于文件名排序），None 表示不是合集模式
    season_index: Optional[int] = None


@dataclass
class SubtitleTrack:
    lan: str
    lan_doc: str
    url: str
    is_ai: bool = False
    body: List[dict] = field(default_factory=list)


@dataclass
class TaskResult:
    part: Part
    ok: bool
    lang: str = ""
    files: List[Path] = field(default_factory=list)
    reason: str = ""


# --------------------------------------------------------------------------- #
# HTTP 客户端：Cookie / 指纹 / WBI 签名 / 重试
# --------------------------------------------------------------------------- #
class BiliClient:
    def __init__(
        self,
        cookie_str: str = "",
        cookie_file: str = "",
        user_agent: str = DEFAULT_UA,
        timeout: float = 15.0,
        retries: int = 3,
        delay: float = 0.4,
        verbose: bool = False,
    ) -> None:
        self.ua = user_agent
        self.timeout = timeout
        self.retries = max(1, retries)
        self.delay = max(0.0, delay)
        self.verbose = verbose

        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPRedirectHandler(),
        )
        self._wbi_key: Optional[str] = None
        self._warmed = False
        self._last_request_at = 0.0

        self.login_cookies: Dict[str, str] = {}
        loaded = _load_cookies(cookie_str, cookie_file)
        for k, v in loaded.items():
            self.login_cookies[k] = v
            self._set_cookie(k, v)

    # ---------------- Cookie ----------------
    @property
    def logged_in(self) -> bool:
        return bool(self.login_cookies.get("SESSDATA"))

    def _set_cookie(self, name: str, value: str, domain: str = ".bilibili.com") -> None:
        self.jar.set_cookie(
            Cookie(
                version=0, name=name, value=value, port=None, port_specified=False,
                domain=domain, domain_specified=True, domain_initial_dot=domain.startswith("."),
                path="/", path_specified=True, secure=False, expires=None, discard=True,
                comment=None, comment_url=None, rest={}, rfc2109=False,
            )
        )

    # ---------------- 基础请求 ----------------
    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        wait = self._last_request_at + self.delay - time.time()
        if wait > 0:
            time.sleep(wait)

    def request(self, url: str, referer: str = "https://www.bilibili.com/", raw: bool = False):
        """GET 请求，返回 bytes（raw=True）或 str。带重试与限速。"""
        headers = {
            "User-Agent": self.ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Referer": referer,
            "Origin": "https://www.bilibili.com",
            "Connection": "keep-alive",
        }
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries):
            self._throttle()
            try:
                req = urllib.request.Request(url, headers=headers)
                with self.opener.open(req, timeout=self.timeout) as resp:
                    data = resp.read()
                    enc = (resp.headers.get("Content-Encoding") or "").lower()
                self._last_request_at = time.time()
                if enc == "gzip":
                    data = gzip.decompress(data)
                elif enc == "deflate":
                    try:
                        data = zlib.decompress(data)
                    except zlib.error:
                        data = zlib.decompress(data, -zlib.MAX_WBITS)
                return data if raw else data.decode("utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001 - 网络异常统一重试
                last_exc = exc
                self._last_request_at = time.time()
                if attempt < self.retries - 1:
                    backoff = 0.8 * (2 ** attempt) + random.random() * 0.3
                    if self.verbose:
                        _log(f"请求失败({exc})，{backoff:.1f}s 后重试：{url}")
                    time.sleep(backoff)
        raise BiliError(f"请求失败：{url}\n  {last_exc}")

    def get_json(self, url: str, referer: str = "https://www.bilibili.com/") -> dict:
        text = self.request(url, referer=referer)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BiliError(f"响应不是合法 JSON：{url}\n  {text[:200]}") from exc
        if not isinstance(obj, dict):
            raise BiliError(f"响应结构异常：{url}")
        return obj

    def api(self, url: str, referer: str = "https://www.bilibili.com/") -> dict:
        """调用 B 站 API 并校验 code。"""
        obj = self.get_json(url, referer=referer)
        code = obj.get("code", 0)
        if code != 0:
            msg = obj.get("message") or obj.get("msg") or "未知错误"
            hint = ""
            if code in (-101, -400, -403, -404, 62002, 62004):
                hint = "（可能需要登录 Cookie，或视频不可见 / 已失效）"
            raise BiliError(f"接口返回 code={code}: {msg} {hint}\n  {url}")
        return obj.get("data") or {}

    def resolve_redirect(self, url: str) -> str:
        """跟随短链重定向，返回最终 URL。"""
        headers = {"User-Agent": self.ua, "Accept": "*/*"}
        try:
            req = urllib.request.Request(url, headers=headers)
            with self.opener.open(req, timeout=self.timeout) as resp:
                return resp.geturl()
        except Exception as exc:  # noqa: BLE001
            raise BiliError(f"短链解析失败：{url}\n  {exc}") from exc

    # ---------------- 指纹 Cookie（未登录时也能提高成功率） ----------------
    def warm_up(self) -> None:
        if self._warmed:
            return
        self._warmed = True
        try:
            self.request("https://www.bilibili.com/", raw=True)
        except BiliError:
            pass
        names = {c.name for c in self.jar}
        if "b_nut" not in names:
            self._set_cookie("b_nut", str(int(time.time())))
        self._set_cookie("i-wanna-go-back", "-1")
        self._set_cookie("b_lsid", f"{_rand_hex(8).upper()}_{format(int(time.time() * 1000), 'X')}")
        self._set_cookie("_uuid", str(uuid.uuid4()).upper() + "infoc")
        fp = _rand_hex(32)
        self._set_cookie("buvid_fp", fp)
        self._set_cookie("fingerprint", fp)
        try:
            spi = self.get_json(API_FINGER_SPI)
            data = spi.get("data") or {}
            if data.get("b_3"):
                self._set_cookie("buvid3", data["b_3"])
            if data.get("b_4"):
                self._set_cookie("buvid4", data["b_4"])
        except BiliError:
            pass
        # 登录 Cookie 优先级最高，重设一次防止被站点 Set-Cookie 覆盖
        for k, v in self.login_cookies.items():
            self._set_cookie(k, v)

    # ---------------- WBI 签名 ----------------
    def _get_wbi_key(self) -> str:
        if self._wbi_key:
            return self._wbi_key
        self.warm_up()
        obj = self.get_json(API_NAV)
        wbi_img = ((obj.get("data") or {}).get("wbi_img")) or {}
        img_url = wbi_img.get("img_url") or ""
        sub_url = wbi_img.get("sub_url") or ""
        if not img_url or not sub_url:
            raise BiliError("获取 WBI 密钥失败（nav 接口未返回 wbi_img）")
        raw = _filename_stem(img_url) + _filename_stem(sub_url)
        self._wbi_key = "".join(raw[i] for i in MIXIN_KEY_ENC_TAB[:32])
        return self._wbi_key

    def sign_wbi(self, base_url: str, params: Dict[str, object]) -> str:
        mixin_key = self._get_wbi_key()
        signed: Dict[str, str] = {}
        for k, v in params.items():
            # 过滤 value 中的 !'()* 字符（B 站前端行为）
            signed[k] = re.sub(r"[!'()*]", "", str(v))
        signed["wts"] = str(int(time.time()))
        query = urllib.parse.urlencode(sorted(signed.items()), quote_via=urllib.parse.quote)
        w_rid = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
        return f"{base_url}?{query}&w_rid={w_rid}"


# --------------------------------------------------------------------------- #
# URL 解析
# --------------------------------------------------------------------------- #
BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
AV_RE = re.compile(r"(?:^|/|av)(\d{1,15})(?:$|[/?#])", re.IGNORECASE)


@dataclass
class ParsedTarget:
    kind: str                       # "video" | "collection" | "series"
    bvid: str = ""
    aid: int = 0
    page: Optional[int] = None      # ?p=N
    mid: int = 0
    sid: int = 0
    source_url: str = ""


def parse_target(raw: str, client: BiliClient) -> ParsedTarget:
    """把用户输入（URL / BV 号 / av 号）解析成抓取目标。"""
    text = raw.strip().strip('"').strip("'")
    if not text:
        raise BiliError("输入为空")

    # 纯 BV / av 号
    if re.fullmatch(r"BV[0-9A-Za-z]{10}", text):
        return ParsedTarget(kind="video", bvid=text, source_url=text)
    if re.fullmatch(r"[Aa][Vv]?\d{1,15}", text) or re.fullmatch(r"\d{1,15}", text):
        return ParsedTarget(kind="video", aid=int(re.sub(r"\D", "", text)), source_url=text)

    if not text.startswith("http"):
        text = "https://" + text

    parsed = urllib.parse.urlparse(text)
    host = (parsed.hostname or "").lower()

    # 短链跟随
    if host in ("b23.tv", "bili2233.cn", "m.bilibili.com") or "b23.tv" in host:
        resolved = client.resolve_redirect(text)
        if resolved and resolved != text:
            _log(f"短链已解析 -> {resolved}")
            text = resolved
            parsed = urllib.parse.urlparse(text)
            host = (parsed.hostname or "").lower()

    query = urllib.parse.parse_qs(parsed.query)
    path = parsed.path or ""

    def _qint(name: str) -> int:
        try:
            return int(query.get(name, ["0"])[0])
        except (TypeError, ValueError):
            return 0

    # 空间合集 / 系列
    if "space.bilibili.com" in host:
        mid_match = re.search(r"space\.bilibili\.com/(\d+)", text)
        mid = int(mid_match.group(1)) if mid_match else _qint("mid")
        sid = _qint("sid")
        list_match = re.search(r"/lists/(\d+)", path)
        if not sid and list_match:
            sid = int(list_match.group(1))
        list_type = (query.get("type", [""])[0] or "").lower()
        if "collectiondetail" in path or list_type == "season":
            kind = "collection"
        elif "seriesdetail" in path or list_type == "series":
            kind = "series"
        else:
            kind = "collection"  # /lists/<sid> 默认按合集处理，失败时会自动回退成系列
        if not sid:
            raise BiliError("无法从空间链接中解析 sid，请确认 URL 含 ?sid=xxx 或 /lists/xxx")
        return ParsedTarget(kind=kind, mid=mid, sid=sid, source_url=text)

    # 播放列表页 /list/... 里通常也带 bvid
    bv = BV_RE.search(text)
    if bv:
        page = _qint("p") or None
        return ParsedTarget(kind="video", bvid=bv.group(1), page=page, source_url=text)

    av = re.search(r"/video/av(\d+)", text, re.IGNORECASE) or re.search(r"[?&]aid=(\d+)", text)
    if av:
        page = _qint("p") or None
        return ParsedTarget(kind="video", aid=int(av.group(1)), page=page, source_url=text)

    if "/bangumi/" in path or re.search(r"/(ep|ss)\d+", path):
        raise BiliError(
            "检测到番剧/影视链接（ep/ss）。本脚本只处理 UP 主投稿视频（BV/av），"
            "番剧字幕受版权保护且接口不同，暂不支持。"
        )

    raise BiliError(f"无法识别的链接：{raw}")


# --------------------------------------------------------------------------- #
# 视频信息 / 列表展开
# --------------------------------------------------------------------------- #
def fetch_view(client: BiliClient, bvid: str = "", aid: int = 0) -> dict:
    if bvid:
        url = f"{API_VIEW}?bvid={urllib.parse.quote(bvid)}"
    elif aid:
        url = f"{API_VIEW}?aid={aid}"
    else:
        raise BiliError("fetch_view 需要 bvid 或 aid")
    return client.api(url)


def parts_from_view(view: dict, pages_filter: Optional[Sequence[int]] = None) -> List[Part]:
    bvid = view.get("bvid") or ""
    title = view.get("title") or bvid
    owner = ((view.get("owner") or {}).get("name")) or ""
    pages = view.get("pages") or []
    if not pages:
        # 极少数情况下 pages 缺失，用顶层 cid 兜底
        cid = int(view.get("cid") or 0)
        if not cid:
            raise BiliError(f"{bvid} 未取到分P信息")
        pages = [{"cid": cid, "page": 1, "part": title, "duration": view.get("duration", 0)}]

    result: List[Part] = []
    for idx, p in enumerate(pages):
        page_no = int(p.get("page") or idx + 1)
        if pages_filter is not None and page_no not in pages_filter:
            continue
        result.append(
            Part(
                bvid=bvid,
                cid=int(p.get("cid") or 0),
                page=page_no,
                part_title=(p.get("part") or f"P{page_no}").strip() or f"P{page_no}",
                video_title=title,
                owner=owner,
                duration=int(p.get("duration") or 0),
            )
        )
    if not result:
        raise BiliError("按 --pages 过滤后没有剩余分P")
    return result


def season_bvids_from_view(view: dict) -> Tuple[str, List[str]]:
    """从视频详情里读取所属合集（ugc_season）的全部 BV 号。"""
    season = view.get("ugc_season") or {}
    if not season:
        return "", []
    name = season.get("title") or "合集"
    bvids: List[str] = []
    for section in season.get("sections") or []:
        for ep in section.get("episodes") or []:
            bvid = ep.get("bvid") or ""
            if bvid and bvid not in bvids:
                bvids.append(bvid)
    return name, bvids


def fetch_collection_bvids(client: BiliClient, mid: int, sid: int) -> Tuple[str, List[str]]:
    """空间合集（seasons_archives_list）。"""
    bvids: List[str] = []
    name = f"合集{sid}"
    page_num, page_size = 1, 30
    while True:
        url = (
            f"{API_SEASON_ARCHIVES}?mid={mid}&season_id={sid}"
            f"&sort_reverse=false&page_num={page_num}&page_size={page_size}"
        )
        data = client.api(url, referer=f"https://space.bilibili.com/{mid}/")
        meta = data.get("meta") or {}
        if meta.get("name"):
            name = meta["name"]
        archives = data.get("archives") or []
        for a in archives:
            if a.get("bvid"):
                bvids.append(a["bvid"])
        total = int(((data.get("page") or {}).get("total")) or len(bvids))
        if len(bvids) >= total or not archives:
            break
        page_num += 1
    return name, bvids


def fetch_series_bvids(client: BiliClient, mid: int, sid: int) -> Tuple[str, List[str]]:
    """空间系列（series/archives）。"""
    bvids: List[str] = []
    name = f"系列{sid}"
    pn, ps = 1, 30
    while True:
        url = (
            f"{API_SERIES_ARCHIVES}?mid={mid}&series_id={sid}"
            f"&only_normal=true&sort=asc&pn={pn}&ps={ps}"
        )
        data = client.api(url, referer=f"https://space.bilibili.com/{mid}/")
        archives = data.get("archives") or []
        for a in archives:
            if a.get("bvid"):
                bvids.append(a["bvid"])
        total = int(((data.get("page") or {}).get("total")) or len(bvids))
        if len(bvids) >= total or not archives:
            break
        pn += 1
    return name, bvids


def build_task_list(client: BiliClient, target: ParsedTarget, args) -> Tuple[str, List[Part]]:
    """返回 (任务标题, 待处理分P列表)。"""
    pages_filter = _parse_pages(args.pages)

    if target.kind in ("collection", "series"):
        if not target.mid:
            raise BiliError("空间合集/系列链接缺少 UP 主 mid，请使用完整的 space.bilibili.com/<mid>/... 链接")
        try:
            if target.kind == "collection":
                name, bvids = fetch_collection_bvids(client, target.mid, target.sid)
            else:
                name, bvids = fetch_series_bvids(client, target.mid, target.sid)
        except BiliError:
            # /lists/<sid> 无 type 时可能猜错类型，自动回退
            if target.kind == "collection":
                name, bvids = fetch_series_bvids(client, target.mid, target.sid)
            else:
                name, bvids = fetch_collection_bvids(client, target.mid, target.sid)
        if not bvids:
            raise BiliError("该合集/系列没有取到任何视频")
        _log(f"合集《{name}》共 {len(bvids)} 个视频")
        return name, _expand_bvids(client, bvids, pages_filter, all_parts=True)

    view = fetch_view(client, bvid=target.bvid, aid=target.aid)

    if args.season:
        name, bvids = season_bvids_from_view(view)
        if not bvids:
            raise BiliError("该视频不属于任何合集（ugc_season），不能使用 --season")
        _log(f"合集《{name}》共 {len(bvids)} 个视频")
        return name, _expand_bvids(client, bvids, pages_filter, all_parts=True)

    title = view.get("title") or target.bvid
    total_pages = len(view.get("pages") or []) or 1

    if pages_filter is not None:
        parts = parts_from_view(view, pages_filter)
    elif args.all_parts:
        parts = parts_from_view(view)
    elif target.page:
        parts = parts_from_view(view, [target.page])
    else:
        parts = parts_from_view(view)
        if total_pages > 1:
            _log(f"该视频共 {total_pages} 个分P，默认全部抓取（用 --pages 1,3 或 URL 的 ?p= 指定）")
    return title, parts


def _expand_bvids(
    client: BiliClient,
    bvids: Sequence[str],
    pages_filter: Optional[Sequence[int]],
    all_parts: bool,
) -> List[Part]:
    parts: List[Part] = []
    for idx, bvid in enumerate(bvids, start=1):
        try:
            view = fetch_view(client, bvid=bvid)
        except BiliError as exc:
            _log(f"[{idx}/{len(bvids)}] {bvid} 信息获取失败，跳过：{exc}")
            continue
        try:
            sub_parts = parts_from_view(view, pages_filter if not all_parts else None)
        except BiliError as exc:
            _log(f"[{idx}/{len(bvids)}] {bvid} 分P解析失败，跳过：{exc}")
            continue
        for p in sub_parts:
            p.season_index = idx
        parts.extend(sub_parts)
    if not parts:
        raise BiliError("合集展开后没有任何可处理的分P")
    return parts


# --------------------------------------------------------------------------- #
# 字幕抓取
# --------------------------------------------------------------------------- #
def list_subtitle_tracks(client: BiliClient, bvid: str, cid: int) -> List[SubtitleTrack]:
    """查询某个分P可用的字幕轨道。"""
    client.warm_up()
    referer = f"https://www.bilibili.com/video/{bvid}/"
    data: dict = {}
    try:
        url = client.sign_wbi(API_PLAYER_WBI_V2, {"bvid": bvid, "cid": cid, "isGaiaAvoided": "false"})
        data = client.api(url, referer=referer)
    except BiliError as exc:
        if client.verbose:
            _log(f"wbi/v2 查询失败，回退 player/v2：{exc}")
        try:
            data = client.api(f"{API_PLAYER_V2}?bvid={bvid}&cid={cid}", referer=referer)
        except BiliError as exc2:
            raise NoSubtitleError(f"字幕接口查询失败：{exc2}") from exc2

    subtitles = ((data.get("subtitle") or {}).get("subtitles")) or []
    tracks: List[SubtitleTrack] = []
    for s in subtitles:
        url = (s.get("subtitle_url") or s.get("subtitle_url_v2") or "").strip()
        if url.startswith("//"):
            url = "https:" + url
        elif url and not url.startswith("http"):
            url = "https://" + url
        lan = s.get("lan") or ""
        tracks.append(
            SubtitleTrack(
                lan=lan,
                lan_doc=s.get("lan_doc") or lan,
                url=url,
                is_ai=bool(str(lan).lower().startswith("ai-") or s.get("ai_status")),
            )
        )
    return tracks


def choose_track(
    tracks: Sequence[SubtitleTrack],
    want_langs: Sequence[str],
    exclude_ai: bool = False,
) -> SubtitleTrack:
    usable = [t for t in tracks if t.url]
    if exclude_ai:
        usable = [t for t in usable if not t.is_ai]
    if not usable:
        raise NoSubtitleError("没有可用字幕（可能是该视频无 CC/AI 字幕，或需要登录 Cookie）")
    for want in want_langs:
        for t in usable:
            if t.lan.lower() == want.lower():
                return t
    for want in want_langs:
        for t in usable:
            if t.lan.lower().startswith(want.lower()):
                return t
    # 兜底：优先非 AI
    usable.sort(key=lambda t: (t.is_ai,))
    return usable[0]


def fetch_track_body(client: BiliClient, track: SubtitleTrack) -> List[dict]:
    text = client.request(track.url, referer="https://www.bilibili.com/")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BiliError(f"字幕 JSON 解析失败：{track.url}") from exc
    body = obj.get("body") if isinstance(obj, dict) else None
    if not isinstance(body, list) or not body:
        raise NoSubtitleError("字幕内容为空")
    return body


# --------------------------------------------------------------------------- #
# 格式转换
# --------------------------------------------------------------------------- #
def seconds_to_srt_time(seconds: float) -> str:
    ms_total = max(0, int(round(float(seconds) * 1000)))
    hours, rest = divmod(ms_total, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def seconds_to_lrc_time(seconds: float) -> str:
    total = max(0.0, float(seconds))
    minutes = int(total // 60)
    secs = total - minutes * 60
    return f"[{minutes:02d}:{secs:05.2f}]"


def _clean_entries(body: Sequence[dict]) -> List[Tuple[float, float, str]]:
    entries: List[Tuple[float, float, str]] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        start = float(item.get("from") or 0.0)
        end = float(item.get("to") or start)
        if end < start:
            end = start
        entries.append((start, end, content))
    return entries


def to_srt(body: Sequence[dict]) -> str:
    entries = _clean_entries(body)
    if not entries:
        raise NoSubtitleError("字幕没有有效内容")
    blocks = []
    for i, (start, end, content) in enumerate(entries, start=1):
        blocks.append(
            f"{i}\n{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}\n{content}\n"
        )
    return "\n".join(blocks)


def to_txt(body: Sequence[dict], with_time: bool = False) -> str:
    entries = _clean_entries(body)
    if not entries:
        raise NoSubtitleError("字幕没有有效内容")
    if with_time:
        lines = [f"[{seconds_to_srt_time(s).replace(',', '.')}] {c}" for s, _e, c in entries]
    else:
        lines = [c for _s, _e, c in entries]
    return "\n".join(lines) + "\n"


def to_lrc(body: Sequence[dict]) -> str:
    entries = _clean_entries(body)
    return "\n".join(f"{seconds_to_lrc_time(s)}{c}" for s, _e, c in entries) + "\n"


def to_json(part: Part, track: SubtitleTrack, body: Sequence[dict]) -> str:
    entries = _clean_entries(body)
    payload = {
        "bvid": part.bvid,
        "cid": part.cid,
        "page": part.page,
        "video_title": part.video_title,
        "part_title": part.part_title,
        "owner": part.owner,
        "duration": part.duration,
        "lang": track.lan,
        "lang_doc": track.lan_doc,
        "is_ai_subtitle": track.is_ai,
        "url": f"https://www.bilibili.com/video/{part.bvid}/?p={part.page}",
        "entries": [{"from": s, "to": e, "content": c} for s, e, c in entries],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


# --------------------------------------------------------------------------- #
# 落盘
# --------------------------------------------------------------------------- #
INVALID_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def sanitize(name: str, max_len: int = 80) -> str:
    cleaned = INVALID_CHARS.sub("_", (name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = cleaned or "untitled"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip(" .")
    return cleaned


def build_stem(part: Part, track: SubtitleTrack, multi_part: bool, season_mode: bool) -> str:
    pieces: List[str] = []
    if season_mode and part.season_index:
        pieces.append(f"{part.season_index:02d}")
    base = part.video_title
    if multi_part and part.part_title and part.part_title != part.video_title:
        base = f"{base}_P{part.page:02d}_{part.part_title}" if not season_mode else f"{base}_P{part.page:02d}"
    pieces.append(sanitize(base))
    stem = "_".join(p for p in pieces if p)
    return f"{stem}.{track.lan or 'unknown'}"


def write_outputs(
    outdir: Path,
    part: Part,
    track: SubtitleTrack,
    body: Sequence[dict],
    formats: Sequence[str],
    stem: str,
    with_time_txt: bool,
    overwrite: bool,
) -> List[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for fmt in formats:
        path = outdir / f"{stem}.{fmt}"
        if path.exists() and not overwrite:
            _log(f"  已存在，跳过（--overwrite 可覆盖）：{path.name}")
            written.append(path)
            continue
        if fmt == "srt":
            content = to_srt(body)
        elif fmt == "txt":
            content = to_txt(body, with_time=with_time_txt)
        elif fmt == "lrc":
            content = to_lrc(body)
        elif fmt == "json":
            content = to_json(part, track, body)
        else:
            raise BiliError(f"不支持的格式：{fmt}")
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def write_merged(outdir: Path, title: str, results: Sequence[TaskResult], bodies: Dict[str, List[dict]]) -> Optional[Path]:
    """把所有成功的字幕合并成一个 Markdown 文稿，方便整体阅读 / 喂给 LLM。"""
    ok = [r for r in results if r.ok]
    if not ok:
        return None
    lines = [f"# {title}", "", f"> 共 {len(ok)} 个分P/视频，由 bili_subtitles.py 提取", ""]
    for r in ok:
        p = r.part
        key = f"{p.bvid}#{p.cid}"
        body = bodies.get(key) or []
        entries = _clean_entries(body)
        heading = p.part_title if p.part_title != p.video_title else p.video_title
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(
            f"- 链接：https://www.bilibili.com/video/{p.bvid}/?p={p.page}　字幕语言：{r.lang}"
        )
        lines.append("")
        for s, _e, c in entries:
            lines.append(f"[{seconds_to_srt_time(s)[:8]}] {c}")
        lines.append("")
    path = outdir / f"{sanitize(title)}_合并文稿.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #
def _log(msg: str) -> None:
    print(msg, flush=True)


def _rand_hex(n: int) -> str:
    return "".join(random.choice("0123456789abcdef") for _ in range(n))


def _filename_stem(url: str) -> str:
    return url.rsplit("/", 1)[-1].split(".", 1)[0]


def _parse_pages(spec: str) -> Optional[List[int]]:
    """解析 --pages "1,3,5-8" -> [1,3,5,6,7,8]"""
    if not spec:
        return None
    pages: List[int] = []
    for token in re.split(r"[,\s]+", spec.strip()):
        if not token:
            continue
        if "-" in token:
            a, _, b = token.partition("-")
            try:
                start, end = int(a), int(b)
            except ValueError as exc:
                raise BiliError(f"--pages 格式错误：{token}") from exc
            if start > end:
                start, end = end, start
            pages.extend(range(start, end + 1))
        else:
            try:
                pages.append(int(token))
            except ValueError as exc:
                raise BiliError(f"--pages 格式错误：{token}") from exc
    result = sorted({p for p in pages if p > 0})
    if not result:
        raise BiliError("--pages 没有解析出有效页码")
    return result


def _parse_cookie_header(raw: str) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for token in re.split(r"[;\n]+", raw or ""):
        token = token.strip()
        if not token or "=" not in token:
            continue
        k, _, v = token.partition("=")
        k, v = k.strip(), v.strip().strip('"')
        if k and v:
            cookies[k] = v
    return cookies


def _load_cookies(cookie_str: str, cookie_file: str) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    env = os.environ.get("BILI_COOKIES", "").strip()
    if env:
        cookies.update(_parse_cookie_header(env))
    if cookie_file:
        path = Path(cookie_file).expanduser()
        if not path.is_file():
            raise BiliError(f"Cookie 文件不存在：{path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        if text.lstrip().startswith("# Netscape") or "\t" in text:
            jar = MozillaCookieJar(str(path))
            try:
                jar.load(ignore_discard=True, ignore_expires=True)
                for c in jar:
                    if "bilibili" in (c.domain or ""):
                        cookies[c.name] = c.value or ""
            except (LoadError, OSError) as exc:
                raise BiliError(f"Cookie 文件解析失败：{exc}") from exc
        else:
            for line in text.splitlines():
                if line.strip() and not line.strip().startswith("#"):
                    cookies.update(_parse_cookie_header(line))
    if cookie_str:
        cookies.update(_parse_cookie_header(cookie_str))
    return cookies


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    formats = [f.strip().lower() for f in args.format.split(",") if f.strip()]
    for f in formats:
        if f not in ("srt", "txt", "json", "lrc"):
            raise BiliError(f"不支持的输出格式：{f}（可选 srt/txt/json/lrc）")

    langs = [x.strip() for x in args.lang.split(",") if x.strip()] if args.lang else list(DEFAULT_LANG_PRIORITY)

    client = BiliClient(
        cookie_str=args.cookie,
        cookie_file=args.cookie_file,
        timeout=args.timeout,
        retries=args.retries,
        delay=args.delay,
        verbose=args.verbose,
    )
    if client.logged_in:
        _log("已加载登录 Cookie（SESSDATA）")
    else:
        _log("未提供登录 Cookie：多数视频的字幕清单会返回空，建议设置 BILI_COOKIES 环境变量")

    target = parse_target(args.url, client)
    title, parts = build_task_list(client, target, args)
    season_mode = bool(args.season or target.kind in ("collection", "series"))

    outdir = Path(args.output).expanduser()
    if season_mode and not args.no_subdir:
        outdir = outdir / sanitize(title)

    _log(f"目标：{title}")
    _log(f"待处理：{len(parts)} 个分P/视频 -> 输出目录 {outdir}")
    _log("-" * 60)

    # 仅列出字幕语言
    if args.list:
        for p in parts:
            try:
                tracks = list_subtitle_tracks(client, p.bvid, p.cid)
            except BiliError as exc:
                _log(f"[{p.bvid} P{p.page}] {p.part_title} -> 查询失败：{exc}")
                continue
            if not tracks:
                _log(f"[{p.bvid} P{p.page}] {p.part_title} -> 无字幕")
            else:
                desc = ", ".join(f"{t.lan}({t.lan_doc}){'[AI]' if t.is_ai else ''}" for t in tracks)
                _log(f"[{p.bvid} P{p.page}] {p.part_title} -> {desc}")
        return 0

    multi_part = len(parts) > 1
    results: List[TaskResult] = []
    bodies: Dict[str, List[dict]] = {}

    for idx, part in enumerate(parts, start=1):
        label = f"[{idx}/{len(parts)}] {part.bvid} P{part.page} {part.part_title}"
        try:
            tracks = list_subtitle_tracks(client, part.bvid, part.cid)
            track = choose_track(tracks, langs, exclude_ai=args.no_ai)
            body = fetch_track_body(client, track)
            bodies[f"{part.bvid}#{part.cid}"] = body
            stem = build_stem(part, track, multi_part, season_mode)
            files = write_outputs(
                outdir, part, track, body, formats, stem,
                with_time_txt=args.txt_with_time, overwrite=args.overwrite,
            )
            results.append(TaskResult(part=part, ok=True, lang=track.lan, files=files))
            flag = "AI字幕" if track.is_ai else "CC字幕"
            _log(f"{label} -> {flag} {track.lan}，{len(_clean_entries(body))} 条 -> {files[0].name}")
        except NoSubtitleError as exc:
            results.append(TaskResult(part=part, ok=False, reason=str(exc)))
            _log(f"{label} -> 跳过：{exc}")
        except BiliError as exc:
            results.append(TaskResult(part=part, ok=False, reason=str(exc)))
            _log(f"{label} -> 失败：{exc}")

    _log("-" * 60)
    ok_count = sum(1 for r in results if r.ok)
    _log(f"完成：成功 {ok_count} / {len(results)}")

    if args.merge and ok_count:
        merged = write_merged(outdir, title, results, bodies)
        if merged:
            _log(f"合并文稿：{merged}")

    if ok_count == 0:
        _log(
            "\n一条都没拿到？常见原因：\n"
            "  1) 未登录：设置 export BILI_COOKIES=\"SESSDATA=...\" 后重试（最常见）\n"
            "  2) 该视频确实没有 CC / AI 字幕（可用 --list 确认）\n"
            "  3) 触发风控：加大 --delay，或稍后再试"
        )
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bili_subtitles.py",
        description="从 B 站视频 / 视频系列（分P、合集、系列）URL 提取字幕，输出 SRT / TXT / JSON / LRC。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  %(prog)s https://www.bilibili.com/video/BV1xx411c7mD\n"
            "  %(prog)s https://www.bilibili.com/video/BV1xx411c7mD?p=2 --format srt,txt\n"
            "  %(prog)s https://www.bilibili.com/video/BV1xx411c7mD --season --merge\n"
            "  %(prog)s 'https://space.bilibili.com/123/channel/collectiondetail?sid=456' -o 字幕\n"
            "  %(prog)s BV1xx411c7mD --list\n"
        ),
    )
    parser.add_argument("url", help="视频 URL / 合集 URL / BV 号 / av 号")
    parser.add_argument("-o", "--output", default="subtitles", help="输出目录（默认 subtitles）")
    parser.add_argument("-f", "--format", default="srt", help="输出格式，逗号分隔：srt,txt,json,lrc（默认 srt）")
    parser.add_argument("-l", "--lang", default="", help=f"语言优先级，逗号分隔（默认 {','.join(DEFAULT_LANG_PRIORITY)}）")
    parser.add_argument("--no-ai", action="store_true", help="排除 AI 智能字幕，只要人工/UP主 CC 字幕")
    parser.add_argument("--pages", default="", help='只抓指定分P，如 "1,3,5-8"')
    parser.add_argument("--all-parts", action="store_true", help="抓取全部分P（URL 带 ?p= 时用它覆盖）")
    parser.add_argument("--season", action="store_true", help="抓取该视频所属合集（ugc_season）的全部视频")
    parser.add_argument("--merge", action="store_true", help="额外生成一个合并的 Markdown 文稿")
    parser.add_argument("--list", action="store_true", help="只列出每个分P可用的字幕语言，不下载")
    parser.add_argument("--txt-with-time", action="store_true", help="txt 格式带时间戳前缀")
    parser.add_argument("--no-subdir", action="store_true", help="合集模式下不额外创建以合集名命名的子目录")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的文件")
    parser.add_argument("--cookie", default="", help='Cookie 字符串，如 "SESSDATA=xxx; bili_jct=yyy"')
    parser.add_argument("--cookie-file", default="", help="Cookie 文件（Netscape cookies.txt 或单行 Cookie 头）")
    parser.add_argument("--delay", type=float, default=0.4, help="请求间隔秒数，防风控（默认 0.4）")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时秒数（默认 15）")
    parser.add_argument("--retries", type=int, default=3, help="失败重试次数（默认 3）")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出更多调试信息")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except BiliError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
