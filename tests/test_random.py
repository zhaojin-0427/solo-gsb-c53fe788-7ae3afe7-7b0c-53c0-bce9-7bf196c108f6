"""随机对拍：区间算法 vs 逐帧展开的朴素参照实现。"""

import random

from app.verification import normalize_timeline, verify

DATE = "2026-06-15"
REGIONS = ["CN", "US", "EU"]
CHANNELS = ["TV", "WEB"]


def brute_force(timeline, auths, date, region, channel):
    """逐帧参照实现：直接按定义检查每个输出帧。"""
    materials = {m["id"]: m for m in timeline["materials"]}

    # 越界？
    for m in timeline["materials"]:
        total = m["total_frames"]
        for s in m["segments"]:
            p, q = s["p"], s["q"]
            for k in range(s["out"] - s["in"]):
                d = (k * abs(p)) // q
                src = s["origin"] + (d if p > 0 else -d)
                if not (0 <= src < total):
                    return {"status": "rejected"}

    active = {}  # frame -> [(mat, src)]
    end = 0
    for m in timeline["materials"]:
        for s in m["segments"]:
            end = max(end, s["out"])
            for k in range(s["out"] - s["in"]):
                d = (k * abs(s["p"])) // s["q"]
                src = s["origin"] + (d if s["p"] > 0 else -d)
                active.setdefault(s["in"] + k, []).append((m["id"], src, s["id"]))

    def covered(mat, src):
        for a in auths:
            if (a["material_id"] == mat and a["src_lo"] <= src < a["src_hi"]
                    and a["date_from"] <= date <= a["date_to"]
                    and a["region"] == region and a["channel"] == channel):
                return True
        return False

    bad_frames = []
    for f in range(end):
        if f in active and not all(covered(mat, src) for mat, src, _ in active[f]):
            bad_frames.append(f)

    # 合并连续帧
    runs = []
    for f in bad_frames:
        if runs and f == runs[-1][1]:
            runs[-1][1] = f + 1
        else:
            runs.append([f, f + 1])
    return {"status": "ok",
            "bad": runs,
            "violating": len(bad_frames),
            "active_frames": len(active)}


def gen_case(rng, region, channel):
    materials = []
    auths = []
    aid = 0
    for mi in range(rng.randint(1, 3)):
        mid = f"M{mi}"
        total = rng.randint(50, 400)
        segs = []
        out_cursor = rng.randint(0, 20)
        for si in range(rng.randint(1, 4)):
            n = rng.randint(5, 80)
            speed = rng.choice([1, 2, -1, 3, 2, "1/2", "3/2", "-1/2", "-3/2", "2/3"])
            segs.append({
                "id": f"{mid}-S{si}",
                "in": out_cursor,
                "out": out_cursor + n,
                "origin": rng.choice([
                    rng.randint(0, max(0, total // 2)),        # 多半正向不越界
                    rng.randint(total // 2, total - 1),        # 多半反向不越界
                    rng.randint(-20, total + 20),              # 少量随机越界
                ]),
                "speed": speed,
            })
            out_cursor += n + rng.randint(0, 15)
        materials.append({"id": mid, "total_frames": total, "segments": segs})
        for _ in range(rng.randint(0, 6)):
            aid += 1
            lo = rng.randint(0, total - 1)
            hi = min(total, lo + rng.randint(1, 80))
            if hi <= lo:
                hi = min(total, lo + 1)
            # 六成授权刻意匹配本次核验维度，便于产生覆盖干净的用例
            if rng.random() < 0.6:
                auth_region, auth_channel = region, channel
                date_from = rng.choice(["2025-01-01", "2026-01-01"])
                date_to = rng.choice(["2026-12-31", "2028-01-01"])
            else:
                auth_region = rng.choice(REGIONS)
                auth_channel = rng.choice(CHANNELS)
                date_from = rng.choice(["2025-01-01", "2026-01-01", "2027-01-01"])
                date_to = rng.choice(["2026-06-15", "2026-12-31", "2028-01-01"])
            auths.append({
                "id": aid, "project_id": 1, "material_id": mid,
                "src_lo": lo, "src_hi": hi,
                "date_from": date_from,
                "date_to": date_to,
                "region": auth_region,
                "channel": auth_channel,
                "note": "", "created_at": "",
            })
    timeline = normalize_timeline({"fps": 25, "materials": materials})
    return timeline, auths


def test_randomized_against_bruteforce():
    rng = random.Random(20260929)
    trials = 400
    rejected = 0
    clean_ok = 0
    for t in range(trials):
        region = rng.choice(REGIONS)
        channel = rng.choice(CHANNELS)
        timeline, auths = gen_case(rng, region, channel)
        expected = brute_force(timeline, auths, DATE, region, channel)
        got = verify(timeline, auths, DATE, region, channel)
        if expected["status"] == "rejected":
            assert got["status"] == "rejected", f"trial {t}: 应判越界拒绝"
            rejected += 1
            continue
        assert got["status"] == "ok", f"trial {t}: 不应越界: {got}"
        if not expected["bad"]:
            clean_ok += 1
        got_runs = [list(pair) for pair in
                    ((v["out"], v["out_end"]) for v in got["violations"])]
        assert got_runs == expected["bad"], (
            f"trial {t}: 违规区间不一致\n期望 {expected['bad']}\n实际 {got_runs}")
        assert got["violating_frames"] == expected["violating"]
        assert got["active_frames"] == expected["active_frames"]

        # 每个合并运行上挂的片段卡片：源帧范围自洽，且输出区间内含在运行中
        for v in got["violations"]:
            for p in v["segments"]:
                assert p["out"] >= v["out"] and p["out_end"] <= v["out_end"]
                assert p["src_hi"] > p["src_lo"]
    assert rejected > 10, f"随机用例中应当出现越界情形，实际 {rejected}"
    assert clean_ok >= 1, f"随机用例中应至少出现完全覆盖情形，实际 {clean_ok}"
    assert rejected + clean_ok < trials, (
        f"也应当存在带缺口的用例，越界 {rejected}、完全覆盖 {clean_ok}、共 {trials}")
