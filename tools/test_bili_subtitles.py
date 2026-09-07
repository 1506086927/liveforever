#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bili_subtitles.py 的离线单元测试（不联网，用 mock 模拟 B 站接口）。

运行： python3 tools/test_bili_subtitles.py -v
"""

import hashlib
import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bili_subtitles as bs  # noqa: E402


SAMPLE_BODY = [
    {"from": 0.5, "to": 2.3, "content": "大家好"},
    {"from": 2.3, "to": 5.0, "content": "今天讲子宫内膜癌的分期"},
    {"from": 5.0, "to": 6.0, "content": "   "},          # 空内容应被跳过
    {"from": 3661.25, "to": 3663.999, "content": "结束"},
]


class FakeClient(bs.BiliClient):
    """不发真实请求的客户端：所有网络出口都被替换成内存数据。"""

    def __init__(self, view_map=None, subs=None, bodies=None, **kw):
        super().__init__(**kw)
        self.view_map = view_map or {}
        self.subs = subs or {}
        self.bodies = bodies or {}
        self.calls = []
        self._wbi_key = "x" * 32
        self._warmed = True

    def request(self, url, referer="", raw=False):
        self.calls.append(url)
        if url in self.bodies:
            return json.dumps({"body": self.bodies[url]}, ensure_ascii=False)
        raise bs.BiliError(f"unexpected request {url}")

    def api(self, url, referer=""):
        self.calls.append(url)
        parsed = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(parsed.query)
        if parsed.path.endswith("/x/web-interface/view"):
            key = q.get("bvid", [""])[0] or f"av{q.get('aid', ['0'])[0]}"
            if key not in self.view_map:
                raise bs.BiliError(f"no view for {key}")
            return self.view_map[key]
        if "player" in parsed.path:
            key = (q.get("bvid", [""])[0], int(q.get("cid", ["0"])[0]))
            return {"subtitle": {"subtitles": self.subs.get(key, [])}}
        if "seasons_archives_list" in parsed.path:
            return {
                "meta": {"name": "合集A"},
                "page": {"total": 2},
                "archives": [{"bvid": "BV10000000a1"}, {"bvid": "BV10000000b2"}],
            }
        if "series/archives" in parsed.path:
            return {"page": {"total": 1}, "archives": [{"bvid": "BV10000000c3"}]}
        raise bs.BiliError(f"unexpected api {url}")

    def resolve_redirect(self, url):
        return "https://www.bilibili.com/video/BV1xx411c7mD?p=2"


def make_view(bvid, title, pages, season=None):
    return {
        "bvid": bvid,
        "title": title,
        "owner": {"name": "某医生"},
        "pages": [
            {"cid": 1000 + i, "page": i + 1, "part": p, "duration": 60}
            for i, p in enumerate(pages)
        ],
        **({"ugc_season": season} if season else {}),
    }


# --------------------------------------------------------------------------- #
class TestTimeFormat(unittest.TestCase):
    def test_srt_time(self):
        self.assertEqual(bs.seconds_to_srt_time(0), "00:00:00,000")
        self.assertEqual(bs.seconds_to_srt_time(0.5), "00:00:00,500")
        self.assertEqual(bs.seconds_to_srt_time(3661.25), "01:01:01,250")
        self.assertEqual(bs.seconds_to_srt_time(-3), "00:00:00,000")

    def test_lrc_time(self):
        self.assertEqual(bs.seconds_to_lrc_time(0), "[00:00.00]")
        self.assertEqual(bs.seconds_to_lrc_time(75.5), "[01:15.50]")


class TestConverters(unittest.TestCase):
    def test_srt(self):
        srt = bs.to_srt(SAMPLE_BODY)
        self.assertIn("1\n00:00:00,500 --> 00:00:02,300\n大家好", srt)
        # 空内容被跳过后序号仍连续，共 3 条
        self.assertIn("3\n01:01:01,250 --> 01:01:03,999\n结束", srt)
        self.assertNotIn("4\n", srt)

    def test_txt(self):
        self.assertEqual(bs.to_txt(SAMPLE_BODY).splitlines()[0], "大家好")
        self.assertTrue(bs.to_txt(SAMPLE_BODY, with_time=True).startswith("[00:00:00.500] 大家好"))

    def test_json(self):
        part = bs.Part(bvid="BV1", cid=9, page=1, part_title="P1", video_title="标题")
        track = bs.SubtitleTrack(lan="zh-CN", lan_doc="中文（中国）", url="u")
        payload = json.loads(bs.to_json(part, track, SAMPLE_BODY))
        self.assertEqual(len(payload["entries"]), 3)
        self.assertEqual(payload["lang"], "zh-CN")

    def test_empty_body_raises(self):
        with self.assertRaises(bs.NoSubtitleError):
            bs.to_srt([{"from": 0, "to": 1, "content": ""}])


class TestParseTarget(unittest.TestCase):
    def setUp(self):
        self.c = FakeClient()

    def test_plain_bvid(self):
        t = bs.parse_target("BV1xx411c7mD", self.c)
        self.assertEqual((t.kind, t.bvid), ("video", "BV1xx411c7mD"))

    def test_video_url_with_page(self):
        t = bs.parse_target("https://www.bilibili.com/video/BV1xx411c7mD?p=3&t=10", self.c)
        self.assertEqual((t.kind, t.bvid, t.page), ("video", "BV1xx411c7mD", 3))

    def test_av_url(self):
        t = bs.parse_target("https://www.bilibili.com/video/av170001", self.c)
        self.assertEqual((t.kind, t.aid), ("video", 170001))

    def test_short_link(self):
        t = bs.parse_target("https://b23.tv/abcd123", self.c)
        self.assertEqual((t.bvid, t.page), ("BV1xx411c7mD", 2))

    def test_collection(self):
        t = bs.parse_target("https://space.bilibili.com/123/channel/collectiondetail?sid=456", self.c)
        self.assertEqual((t.kind, t.mid, t.sid), ("collection", 123, 456))

    def test_series(self):
        t = bs.parse_target("https://space.bilibili.com/123/channel/seriesdetail?sid=789", self.c)
        self.assertEqual((t.kind, t.mid, t.sid), ("series", 123, 789))

    def test_new_lists_url(self):
        t = bs.parse_target("https://space.bilibili.com/123/lists/456?type=season", self.c)
        self.assertEqual((t.kind, t.mid, t.sid), ("collection", 123, 456))

    def test_playlist_url_with_bvid(self):
        t = bs.parse_target(
            "https://www.bilibili.com/list/123?sid=456&bvid=BV1xx411c7mD&oid=1", self.c
        )
        self.assertEqual(t.bvid, "BV1xx411c7mD")

    def test_bangumi_rejected(self):
        with self.assertRaises(bs.BiliError):
            bs.parse_target("https://www.bilibili.com/bangumi/play/ep123456", self.c)

    def test_garbage_rejected(self):
        with self.assertRaises(bs.BiliError):
            bs.parse_target("https://example.com/whatever", self.c)


class TestPagesSpec(unittest.TestCase):
    def test_parse(self):
        self.assertIsNone(bs._parse_pages(""))
        self.assertEqual(bs._parse_pages("1,3,5-8"), [1, 3, 5, 6, 7, 8])
        self.assertEqual(bs._parse_pages("4-2"), [2, 3, 4])
        with self.assertRaises(bs.BiliError):
            bs._parse_pages("a,b")


class TestWbiSign(unittest.TestCase):
    def test_signature_matches_manual_md5(self):
        c = FakeClient()
        c._wbi_key = "a" * 32
        url = c.sign_wbi("https://api.bilibili.com/x/player/wbi/v2", {"bvid": "BV1", "cid": 2})
        parsed = urllib.parse.urlparse(url)
        pairs = parsed.query.split("&")
        w_rid = pairs[-1].split("=", 1)[1]
        query_wo_rid = "&".join(pairs[:-1])
        self.assertEqual(hashlib.md5((query_wo_rid + "a" * 32).encode()).hexdigest(), w_rid)
        # 参数必须按 key 排序
        keys = [p.split("=", 1)[0] for p in pairs[:-1]]
        self.assertEqual(keys, sorted(keys))
        self.assertIn("wts", keys)

    def test_special_chars_filtered(self):
        c = FakeClient()
        c._wbi_key = "b" * 32
        url = c.sign_wbi("https://x/y", {"kw": "a!b'c(d)e*f"})
        self.assertIn("kw=abcdef", url)


class TestTrackSelection(unittest.TestCase):
    def setUp(self):
        self.tracks = [
            bs.SubtitleTrack("ai-zh", "AI中文", "http://a", is_ai=True),
            bs.SubtitleTrack("zh-CN", "中文", "http://b"),
            bs.SubtitleTrack("en-US", "英文", "http://c"),
        ]

    def test_priority(self):
        t = bs.choose_track(self.tracks, bs.DEFAULT_LANG_PRIORITY)
        self.assertEqual(t.lan, "zh-CN")

    def test_explicit_lang(self):
        self.assertEqual(bs.choose_track(self.tracks, ["en-US"]).lan, "en-US")

    def test_exclude_ai(self):
        only_ai = [bs.SubtitleTrack("ai-zh", "AI中文", "http://a", is_ai=True)]
        with self.assertRaises(bs.NoSubtitleError):
            bs.choose_track(only_ai, ["zh-CN"], exclude_ai=True)
        self.assertEqual(bs.choose_track(only_ai, ["zh-CN"]).lan, "ai-zh")

    def test_no_url_is_unusable(self):
        with self.assertRaises(bs.NoSubtitleError):
            bs.choose_track([bs.SubtitleTrack("zh-CN", "中文", "")], ["zh-CN"])


class TestSanitize(unittest.TestCase):
    def test_illegal_chars(self):
        self.assertEqual(bs.sanitize('a/b\\c:d*e?f"g<h>i|j'), "a_b_c_d_e_f_g_h_i_j")

    def test_truncate(self):
        self.assertEqual(len(bs.sanitize("字" * 200)), 80)

    def test_empty(self):
        self.assertEqual(bs.sanitize("   "), "untitled")


class TestPartsAndSeason(unittest.TestCase):
    def test_pages_filter(self):
        view = make_view("BV1", "多P视频", ["第一节", "第二节", "第三节"])
        parts = bs.parts_from_view(view, [1, 3])
        self.assertEqual([p.page for p in parts], [1, 3])
        self.assertEqual(parts[1].cid, 1002)

    def test_season_bvids(self):
        season = {
            "title": "内膜癌系列",
            "sections": [{"episodes": [{"bvid": "BVa"}, {"bvid": "BVb"}, {"bvid": "BVa"}]}],
        }
        name, bvids = bs.season_bvids_from_view(make_view("BVa", "第一集", ["P1"], season))
        self.assertEqual((name, bvids), ("内膜癌系列", ["BVa", "BVb"]))


class TestEndToEnd(unittest.TestCase):
    """用假客户端跑通「列表 -> 字幕 -> 落盘」全流程。"""

    def _client(self):
        sub_url = "https://aisubtitle.hdslb.com/fake.json"
        return FakeClient(
            view_map={
                "BV1xx411c7mD": make_view("BV1xx411c7mD", "手术要点讲解", ["开场", "分期", "预后"]),
            },
            subs={
                ("BV1xx411c7mD", 1000): [{"lan": "zh-CN", "lan_doc": "中文", "subtitle_url": "//aisubtitle.hdslb.com/fake.json"}],
                ("BV1xx411c7mD", 1001): [{"lan": "ai-zh", "lan_doc": "AI中文", "subtitle_url": sub_url}],
                ("BV1xx411c7mD", 1002): [],  # 无字幕
            },
            bodies={sub_url: SAMPLE_BODY},
        )

    def test_full_run(self):
        client = self._client()
        parts = bs.parts_from_view(client.api(bs.API_VIEW + "?bvid=BV1xx411c7mD"))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            ok, results, bodies = 0, [], {}
            for part in parts:
                try:
                    tracks = bs.list_subtitle_tracks(client, part.bvid, part.cid)
                    track = bs.choose_track(tracks, bs.DEFAULT_LANG_PRIORITY)
                    body = bs.fetch_track_body(client, track)
                except bs.BiliError as exc:
                    results.append(bs.TaskResult(part=part, ok=False, reason=str(exc)))
                    continue
                bodies[f"{part.bvid}#{part.cid}"] = body
                stem = bs.build_stem(part, track, multi_part=True, season_mode=False)
                files = bs.write_outputs(
                    out, part, track, body, ["srt", "txt", "json"], stem,
                    with_time_txt=False, overwrite=True,
                )
                results.append(bs.TaskResult(part=part, ok=True, lang=track.lan, files=files))
                ok += 1

            self.assertEqual(ok, 2)  # 第三个分P无字幕
            names = sorted(p.name for p in out.iterdir())
            self.assertTrue(any(n.endswith(".srt") for n in names))
            self.assertTrue(any(".zh-CN." in n for n in names))
            self.assertTrue(any(".ai-zh." in n for n in names))
            srt = next(out.glob("*.zh-CN.srt")).read_text(encoding="utf-8")
            self.assertIn("今天讲子宫内膜癌的分期", srt)

            merged = bs.write_merged(out, "手术要点讲解", results, bodies)
            self.assertIsNotNone(merged)
            text = merged.read_text(encoding="utf-8")
            self.assertIn("# 手术要点讲解", text)
            self.assertIn("[00:00:00] 大家好", text)

    def test_no_overwrite_keeps_file(self):
        client = self._client()
        part = bs.parts_from_view(client.api(bs.API_VIEW + "?bvid=BV1xx411c7mD"), [1])[0]
        track = bs.choose_track(bs.list_subtitle_tracks(client, part.bvid, part.cid), ["zh-CN"])
        body = bs.fetch_track_body(client, track)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            stem = bs.build_stem(part, track, multi_part=False, season_mode=False)
            (out / f"{stem}.srt").write_text("旧内容", encoding="utf-8")
            bs.write_outputs(out, part, track, body, ["srt"], stem, False, overwrite=False)
            self.assertEqual((out / f"{stem}.srt").read_text(encoding="utf-8"), "旧内容")
            bs.write_outputs(out, part, track, body, ["srt"], stem, False, overwrite=True)
            self.assertIn("大家好", (out / f"{stem}.srt").read_text(encoding="utf-8"))


class TestCookieLoading(unittest.TestCase):
    def test_header_string(self):
        d = bs._parse_cookie_header('SESSDATA=abc%2Cdef; bili_jct="xyz" ; junk')
        self.assertEqual(d["SESSDATA"], "abc%2Cdef")
        self.assertEqual(d["bili_jct"], "xyz")

    def test_netscape_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cookies.txt"
            p.write_text(
                "# Netscape HTTP Cookie File\n"
                ".bilibili.com\tTRUE\t/\tFALSE\t9999999999\tSESSDATA\tsecret\n"
                ".other.com\tTRUE\t/\tFALSE\t9999999999\tX\ty\n",
                encoding="utf-8",
            )
            cookies = bs._load_cookies("", str(p))
            self.assertEqual(cookies.get("SESSDATA"), "secret")
            self.assertNotIn("X", cookies)

    def test_plain_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.txt"
            p.write_text("SESSDATA=aaa; buvid3=bbb\n", encoding="utf-8")
            self.assertEqual(bs._load_cookies("", str(p))["buvid3"], "bbb")

    def test_missing_file(self):
        with self.assertRaises(bs.BiliError):
            bs._load_cookies("", "/nonexistent/cookies.txt")


if __name__ == "__main__":
    unittest.main(verbosity=2)
