"""核心算法单元测试：帧映射、覆盖求交、违规合并、越界拒绝、性能。"""

import time

import pytest

from app.verification import (
    Segment,
    complement,
    covered_k_interval,
    merge_intervals,
    merge_runs_with_tags,
    normalize_timeline,
    parse_speed,
    verify,
)


# ---------------------------------------------------------------------------
# 分数解析
# ---------------------------------------------------------------------------

def test_parse_speed_forms():
    assert parse_speed(2) == (2, 1)
    assert parse_speed(-3) == (-3, 1)
    assert parse_speed("2/4") == (1, 2)
    assert parse_speed("-6/4") == (-3, 2)
    assert parse_speed({"numerator": 6, "denominator": -4}) == (-3, 2)


@pytest.mark.parametrize("v", [0, "0/1", {"numerator": 0, "denominator": 5}])
def test_parse_speed_rejects_zero(v):
    with pytest.raises(ValueError):
        parse_speed(v)


def test_parse_speed_rejects_float():
    with pytest.raises(ValueError):
        parse_speed(0.5)


# ---------------------------------------------------------------------------
# 映射规则：src(k) = origin + sign * floor(k * |p/q|)
# ---------------------------------------------------------------------------

def make_seg(p, q, n, origin=0, seg_in=0, sid="S", mid="M"):
    return Segment(sid, mid, seg_in, seg_in + n, origin, p, q)


def test_positive_fractional_mapping():
    seg = make_seg(3, 2, 6, origin=100)  # 速度 1.5
    assert [seg.src_at(k) for k in range(6)] == [100, 101, 103, 104, 106, 107]


def test_negative_fractional_mapping():
    # src(k) = origin + sign * floor(k * |p/q|)，符号作用于 floor 的结果
    seg = make_seg(-1, 2, 6, origin=9000)
    assert [seg.src_at(k) for k in range(6)] == [9000, 9000, 8999, 8999, 8998, 8998]


def test_negative_integer_mapping():
    seg = make_seg(-1, 1, 5, origin=100)
    assert [seg.src_at(k) for k in range(5)] == [100, 99, 98, 97, 96]


# ---------------------------------------------------------------------------
# 授权区间 -> k 区间（O(1) 求交）
# ---------------------------------------------------------------------------

def test_covered_k_positive():
    seg = make_seg(3, 2, 6, origin=100)  # 源帧 100,101,103,104,106,107
    assert covered_k_interval(seg, 100, 108) == (0, 6)
    assert covered_k_interval(seg, 103, 105) == (2, 4)   # 源 103,104
    assert covered_k_interval(seg, 104, 107) == (3, 5)   # 源 104,106（107 不含）
    assert covered_k_interval(seg, 101, 102) == (1, 2)   # 源 101
    assert covered_k_interval(seg, 0, 100) is None       # 半开：不含 100
    assert covered_k_interval(seg, 108, 200) is None
    assert covered_k_interval(seg, 102, 103) is None     # 没有源帧 102


def test_covered_k_negative():
    seg = make_seg(-1, 2, 6, origin=9000)  # 9000,9000,8999,8999,8998,8998
    assert covered_k_interval(seg, 8997, 9001) == (0, 6)
    assert covered_k_interval(seg, 8998, 8999) == (4, 6)  # 8998 出现在 k=4,5
    assert covered_k_interval(seg, 8999, 9000) == (2, 4)  # 8999 出现在 k=2,3
    assert covered_k_interval(seg, 9000, 9001) == (0, 2)  # 9000 出现在 k=0,1
    assert covered_k_interval(seg, 8996, 8997) is None
    assert covered_k_interval(seg, 9001, 9999) is None


def test_covered_k_partial_overlap():
    seg = make_seg(1, 1, 10, origin=100)  # 源 100..109
    assert covered_k_interval(seg, 95, 103) == (0, 3)     # 100,101,102
    assert covered_k_interval(seg, 107, 200) == (7, 10)   # 107,108,109


# ---------------------------------------------------------------------------
# 区间工具
# ---------------------------------------------------------------------------

def test_merge_and_complement():
    assert merge_intervals([(0, 5), (5, 10), (12, 14), (3, 4)]) == [(0, 10), (12, 14)]
    assert complement(merge_intervals([(2, 4), (8, 9)]), 10) == [(0, 2), (4, 8), (9, 10)]


def test_merge_runs_with_tags_adjacent_segments():
    # 两个相邻片段各自的缺口在输出轴上连续，必须合并为一个运行并保留两个片段原因
    tagged = [
        (0, 100, {"segment_id": "S1", "k_lo": 0, "k_hi": 100}),
        (100, 200, {"segment_id": "S2", "k_lo": 0, "k_hi": 100}),
    ]
    runs = merge_runs_with_tags(tagged)
    assert runs == [
        (0, 200, [
            {"segment_id": "S1", "k_lo": 0, "k_hi": 100},
            {"segment_id": "S2", "k_lo": 0, "k_hi": 100},
        ])
    ]


def test_merge_runs_with_tags_overlapping():
    tagged = [
        (10, 50, {"segment_id": "S1", "k_lo": 0, "k_hi": 40}),
        (40, 80, {"segment_id": "S2", "k_lo": 0, "k_hi": 40}),
        (90, 100, {"segment_id": "S3", "k_lo": 0, "k_hi": 10}),
    ]
    runs = merge_runs_with_tags(tagged)
    assert [(lo, hi) for lo, hi, _ in runs] == [(10, 80), (90, 100)]
    assert {t["segment_id"] for t in runs[0][2]} == {"S1", "S2"}


# ---------------------------------------------------------------------------
# 端到端核验
# ---------------------------------------------------------------------------

DATE = "2026-01-01"


def tl_single(total_frames, segments, fps=25):
    return normalize_timeline({"fps": fps, "materials": [
        {"id": "M1", "total_frames": total_frames, "segments": segments}]})


def auth(lo, hi, date_from="2025-01-01", date_to="2027-01-01",
         region="CN", channel="TV", mid="M1", aid=1):
    return {"id": aid, "project_id": 1, "material_id": mid,
            "src_lo": lo, "src_hi": hi, "date_from": date_from,
            "date_to": date_to, "region": region, "channel": channel,
            "note": "", "created_at": ""}


def test_verify_clean_when_fully_covered():
    tl = tl_single(1000, [{"id": "S1", "in": 0, "out": 100,
                           "origin": 100, "speed": 1}])
    res = verify(tl, [auth(100, 200)], DATE, "CN", "TV")
    assert res["status"] == "ok"
    assert res["violating_frames"] == 0
    assert res["violations"] == []
    assert res["active_frames"] == 100


def test_verify_partial_gap_with_fractional_speed():
    # 速度 3/2，源帧 100,101,103,104,106,107...
    seg = {"id": "S1", "in": 0, "out": 200, "origin": 100, "speed": "3/2"}
    tl = tl_single(1000, [seg])
    # 只授权 [100,105)：覆盖源 100,101,103,104 => k=0..3
    res = verify(tl, [auth(100, 105)], DATE, "CN", "TV")
    assert res["status"] == "ok"
    assert len(res["violations"]) == 1
    v = res["violations"][0]
    assert (v["out"], v["out_end"]) == (4, 200)
    piece = v["segments"][0]
    assert (piece["src_lo"], piece["src_hi"]) == (106, 399)  # src(4)=106, src(199)=398 半开
    assert piece["reason_code"] == "NO_LICENSE"


def test_verify_blank_frames_not_violations():
    # 片段只占用 [100,200)，外面的空白帧不算违规
    tl = tl_single(1000, [{"id": "S1", "in": 100, "out": 200,
                           "origin": 0, "speed": 1}])
    res = verify(tl, [auth(0, 100)], DATE, "CN", "TV")
    assert res["active_frames"] == 100
    assert res["blank_frames"] == 0  # 时间线范围即片段并集
    assert res["violating_frames"] == 0

    tl2 = normalize_timeline({"fps": 25, "materials": [{
        "id": "M1", "total_frames": 1000, "segments": [
            {"id": "S1", "in": 0, "out": 100, "origin": 0, "speed": 1},
            {"id": "S2", "in": 200, "out": 300, "origin": 0, "speed": 1},
        ]}]})
    res2 = verify(tl2, [auth(0, 100)], DATE, "CN", "TV")
    assert res2["blank_frames"] == 100
    assert res2["violating_frames"] == 0


def test_verify_overlapping_segments_both_must_be_licensed():
    # 两个片段在输出帧重叠；只授权一个 => 重叠区每帧仍违规
    tl = normalize_timeline({"fps": 25, "materials": [{
        "id": "M1", "total_frames": 1000, "segments": [
            {"id": "S1", "in": 0, "out": 100, "origin": 0, "speed": 1},
            {"id": "S2", "in": 50, "out": 150, "origin": 500, "speed": 1},
        ]}]})
    res = verify(tl, [auth(0, 100)], DATE, "CN", "TV")
    assert res["violations"][0]["out"] == 50
    assert res["violations"][0]["out_end"] == 150
    assert res["violations"][0]["segments"][0]["segment_id"] == "S2"

    # 两条授权都给齐 => 完全干净
    res2 = verify(tl, [auth(0, 100, aid=1), auth(500, 600, aid=2)],
                  DATE, "CN", "TV")
    assert res2["violating_frames"] == 0


def test_verify_dimension_filters_and_candidates():
    tl = tl_single(1000, [{"id": "S1", "in": 0, "out": 100,
                           "origin": 0, "speed": 1}])
    res = verify(tl, [auth(0, 100, region="US")], DATE, "CN", "TV")
    assert res["violating_frames"] == 100
    piece = res["violations"][0]["segments"][0]
    assert piece["reason_code"] == "DIMENSION_MISMATCH"
    assert piece["candidates"][0]["mismatch"] == ["region"]

    # 日期区间含首尾
    res_edge = verify(tl, [auth(0, 100, date_from=DATE, date_to=DATE)],
                      DATE, "CN", "TV")
    assert res_edge["violating_frames"] == 0

    res_date = verify(tl, [auth(0, 100, date_from="2027-01-01",
                                date_to="2028-01-01")], DATE, "CN", "TV")
    assert res_date["violations"][0]["segments"][0]["candidates"][0]["mismatch"] == ["date"]


def test_verify_multiple_gap_pieces_kept_per_run():
    # 授权覆盖片段中段，形成两段缺口
    tl = tl_single(1000, [{"id": "S1", "in": 0, "out": 300,
                           "origin": 0, "speed": 1}])
    res = verify(tl, [auth(100, 200)], DATE, "CN", "TV")
    v = res["violations"]
    assert [(x["out"], x["out_end"]) for x in v] == [(0, 100), (200, 300)]


def test_verify_out_of_bounds_rejected():
    # 正向：结尾越界
    tl = tl_single(100, [{"id": "S1", "in": 0, "out": 50,
                          "origin": 90, "speed": 1}])  # 源 90..139
    res = verify(tl, [], DATE, "CN", "TV")
    assert res["status"] == "rejected"
    assert res["violations_out_of_bounds"][0]["src_max"] == 139

    # 反向：开头越界
    tl2 = tl_single(100, [{"id": "S2", "in": 0, "out": 30,
                           "origin": 10, "speed": -1}])  # 源 10..-19
    res2 = verify(tl2, [], DATE, "CN", "TV")
    assert res2["status"] == "rejected"
    assert res2["violations_out_of_bounds"][0]["src_min"] == -19


def test_verify_reverify_after_license_change():
    tl = tl_single(1000, [{"id": "S1", "in": 0, "out": 100,
                           "origin": 0, "speed": 1}])
    res1 = verify(tl, [], DATE, "CN", "TV")
    assert res1["violating_frames"] == 100
    res2 = verify(tl, [auth(0, 100)], DATE, "CN", "TV")
    assert res2["violating_frames"] == 0


def test_normalize_timeline_accepts_forms():
    tl = normalize_timeline({
        "total_frames": 1000,
        "segments": [{"in": 0, "out": 10, "origin": 5, "speed": "-2/3"}],
    })
    assert tl["materials"][0]["id"] == "M1"
    s = tl["materials"][0]["segments"][0]
    assert (s["p"], s["q"]) == (-2, 3)
    assert s["id"] == "S1"

    with pytest.raises(ValueError):
        normalize_timeline({"total_frames": 100, "segments": [
            {"in": 0, "out": 10, "origin": 0, "speed": 0}]})
    with pytest.raises(ValueError):
        normalize_timeline({"total_frames": -1, "segments": []})


# ---------------------------------------------------------------------------
# 性能：千万帧不得逐帧展开
# ---------------------------------------------------------------------------

def test_ten_million_frames_interval_only():
    HUGE = 10_000_000
    tl = normalize_timeline({
        "fps": 25,
        "materials": [
            {"id": "BIG", "total_frames": HUGE * 2, "segments": [
                {"id": "H1", "in": 0, "out": HUGE, "origin": 0, "speed": "1/3"},
            ]},
            {"id": "B2", "total_frames": HUGE * 2, "segments": [
                {"id": "H2", "in": HUGE // 2, "out": HUGE + HUGE // 2,
                 "origin": HUGE, "speed": "-2/5"},
            ]},
        ],
    })
    # 少量分散授权：制造 O(授权数) 个缺口区间
    auths = []
    for i, lo in enumerate(range(0, HUGE, 9973)):
        auths.append(auth(lo, lo + 100, mid="BIG", aid=i + 1))
        if i > 400:
            break
    t0 = time.perf_counter()
    res = verify(tl, auths, DATE, "CN", "TV")
    elapsed = time.perf_counter() - t0
    assert res["status"] == "ok"
    assert elapsed < 3.0, f"千万帧核验耗时 {elapsed:.2f}s，疑似逐帧展开"
    # 违规帧数必须与区间算术一致（抽样用闭式校验，不展开）
    # 片段 H1：速度 1/3，覆盖源帧 = 各授权源区间映射的 k 区间；
    # 这里只验证结果规模与运行数受授权数约束、远小于帧数。
    assert res["violation_run_count"] <= len(auths) + 2
    assert res["active_frames"] == HUGE + HUGE // 2  # 并集长度（含重叠区）
    print(f"\n千万帧核验耗时 {elapsed:.3f}s，"
          f"违规段 {res['violation_run_count']}，违规帧 {res['violating_frames']}")


def test_ten_million_frames_fully_covered_is_instant():
    HUGE = 10_000_000
    seg_n = HUGE
    p, q, origin = 3, 2, 0
    last = origin + ((seg_n - 1) * p) // q
    tl = tl_single(last + 1, [{"id": "H", "in": 0, "out": seg_n,
                               "origin": origin, "speed": f"{p}/{q}"}], fps=24)
    t0 = time.perf_counter()
    res = verify(tl, [auth(origin, last + 1)], DATE, "CN", "TV")
    elapsed = time.perf_counter() - t0
    assert res["violating_frames"] == 0
    assert elapsed < 1.0


def test_many_segments_merged_into_single_run():
    # 一万个片段在同一输出区间重叠且全无授权 => 单个违规运行、上万条片段原因。
    # 标签分配必须是线性扫描，不能出现 O(片段数^2) 的退化。
    N = 10_000
    segs = [{"id": f"S{i}", "in": 0, "out": 50,
             "origin": i, "speed": 1} for i in range(N)]
    tl = normalize_timeline({"fps": 25, "materials": [
        {"id": "M1", "total_frames": N + 1000, "segments": segs}]})
    t0 = time.perf_counter()
    res = verify(tl, [], DATE, "CN", "TV")
    elapsed = time.perf_counter() - t0
    assert res["status"] == "ok"
    assert res["violation_run_count"] == 1
    assert res["violations"][0]["out_end"] == 50
    assert len(res["violations"][0]["segments"]) == N
    assert elapsed < 3.0, f"万片段合并耗时 {elapsed:.2f}s，疑似 O(n²) 退化"
