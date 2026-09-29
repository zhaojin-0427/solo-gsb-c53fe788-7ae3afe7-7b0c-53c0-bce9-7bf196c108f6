"""授权覆盖核验核心算法。

帧映射规则（半开区间）
----------------------
片段为 [seg_in, seg_out) 的输出帧；第 k 个输出帧（0 <= k < length）的源帧为

    src(k) = origin + sign(k) * floor(k * |speed|)

速度以非零有符号分数 p/q 给出（q > 0），全程使用整数运算，不依赖浮点。

核验针对一次「播出维度」（播出日期、地区、渠道）：
某输出帧若存在至少一个活动片段，则该帧合法当且仅当其在每个活动片段上映射出的
源帧都被至少一条维度匹配的授权区间覆盖；没有任何活动片段的空白帧不算违规。

性能约定
--------
10,000,000 帧的时间线也不得逐帧展开。所有运算都以「区间」为单位：
  * 片段越界只需检查映射区间的两个端点（floor 单调）；
  * 每条授权与片段的求交是 O(1) 的整数区间运算；
  * 区间合并用线性扫描，整体复杂度 O((S + A) log A)（S=片段数, A=授权数），
    与时间线总帧数无关。
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from math import gcd
from typing import Iterable


# ---------------------------------------------------------------------------
# 分数与整数工具
# ---------------------------------------------------------------------------

def _ceil_div(a: int, b: int) -> int:
    """ceil(a / b)，要求 b > 0。"""
    return -((-a) // b)


def parse_speed(value) -> tuple[int, int]:
    """把整数 / "p/q" 字符串 / {"numerator":..,"denominator":..} 解析为约分后的 (p, q)。

    返回带符号分子与正分母；速度不得为零。
    """
    if isinstance(value, bool):  # bool 是 int 的子类，显式拒绝
        raise ValueError("速度必须是非零有符号分数，不能是布尔值")
    if isinstance(value, int):
        num, den = value, 1
    elif isinstance(value, float):
        raise ValueError("速度必须以分数或整数给出，禁止使用浮点数")
    elif isinstance(value, str):
        text = value.strip()
        if "/" in text:
            ns, ds = text.split("/", 1)
            num, den = int(ns), int(ds)
        else:
            num, den = int(text), 1
    elif isinstance(value, dict):
        num = int(value.get("numerator", value.get("num")))
        den = int(value.get("denominator", value.get("den", 1)))
    else:
        raise ValueError(f"无法识别的速度表示: {value!r}")
    if den == 0:
        raise ValueError("速度分母不能为零")
    if num == 0:
        raise ValueError("速度不能为零")
    if den < 0:
        num, den = -num, -den
    g = gcd(abs(num), den)
    return num // g, den // g


@dataclass(frozen=True)
class Segment:
    id: str
    material_id: str
    seg_in: int
    seg_out: int          # 半开
    origin: int
    p: int                # 带符号分子（非零）
    q: int                # 正分母

    @property
    def length(self) -> int:
        return self.seg_out - self.seg_in

    def span(self) -> tuple[int, int, int, int]:
        """返回映射源帧区间及关键端点 (lo, hi_exclusive, src_first, src_last)。

        floor 对 k 单调，正向时最小值在 k=0、反向时最大值在 k=0。
        """
        n = self.length
        if self.p > 0:
            first = self.origin
            last = self.origin + ((n - 1) * self.p) // self.q
            return first, last + 1, first, last
        ap = -self.p
        first = self.origin - ((n - 1) * ap) // self.q
        last = self.origin
        return first, last + 1, first, last

    def src_at(self, k: int) -> int:
        """片段内第 k 帧映射到的源帧。"""
        if self.p > 0:
            return self.origin + (k * self.p) // self.q
        return self.origin - (k * (-self.p)) // self.q

    def k_for_src(self, x: int) -> int:
        """源帧 x 在片段内对应的 k（单调映射，取下标意义由调用方按区间使用）。"""
        if self.p > 0:
            return _ceil_div((x - self.origin) * self.q, self.p)
        return _ceil_div((self.origin - x) * self.q, -self.p)


# ---------------------------------------------------------------------------
# 授权 → 输出帧区间求交
# ---------------------------------------------------------------------------

def covered_k_interval(seg: Segment, a_lo: int, a_hi: int) -> tuple[int, int] | None:
    """授权源帧半开区间 [a_lo, a_hi) 在片段内覆盖的片段下标 k 区间 [lo, hi)。

    纯整数 O(1) 运算；无交集返回 None。
    """
    n = seg.length
    p, q = seg.p, seg.q
    if p > 0:
        # k 覆盖当且仅当 a_lo <= o + floor(kp/q) < a_hi。
        # 令 u(k) = floor(kp/q)（单调不减，步长约 p/q）。
        #   下界：u(k) >= a_lo - o => k >= ceil((a_lo-o)*q/p)。
        #   上界：u(k) <= a_hi - o - 1 => 最大 k 为
        #        floor(((a_hi-o)*q - 1) / p) + 1（floor 不等式的标准逆元；
        #        非整除时直接 ceil((a_hi-o)q/p) 会多放进一帧）。
        lo = _ceil_div((a_lo - seg.origin) * q, p)
        hi = ((a_hi - seg.origin) * q - 1) // p + 1
    else:
        # k 覆盖当且仅当 a_lo <= o - floor(k*ap/q) < a_hi（ap = -p > 0）。
        # 令 d(k) = floor(k*ap/q)（单调不减，步长约 ap/q）。
        #   上界：o - d >= a_lo  =>  d <= o - a_lo
        #        => floor(k*ap/q) <= o-a_lo，最大 k 用标准 floor 逆元：
        #        floor(((o-a_lo+1)*q - 1)/ap) + 1。
        #   下界：o - d < a_hi => d >= o - a_hi + 1
        #        => k >= ceil((o-a_hi+1)*q/ap)。
        ap = -p
        lo = _ceil_div((seg.origin - (a_hi - 1)) * q, ap)
        hi = ((seg.origin - a_lo + 1) * q - 1) // ap + 1
    lo = max(lo, 0)
    hi = min(hi, n)
    if lo < hi:
        return lo, hi
    return None


def merge_intervals(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """合并重叠或相邻（[0,5)+[5,10) => [0,10)）的半开整数区间。"""
    ordered = sorted((lo, hi) for lo, hi in intervals if lo < hi)
    merged: list[tuple[int, int]] = []
    for lo, hi in ordered:
        if merged and lo <= merged[-1][1]:
            if hi > merged[-1][1]:
                merged[-1] = (merged[-1][0], hi)
        else:
            merged.append((lo, hi))
    return merged


def complement(intervals: list[tuple[int, int]], length: int) -> list[tuple[int, int]]:
    """[0, length) 内被 intervals 覆盖部分之外的缺口（intervals 需已合并）。"""
    gaps: list[tuple[int, int]] = []
    cursor = 0
    for lo, hi in intervals:
        if lo > cursor:
            gaps.append((cursor, lo))
        if hi > cursor:
            cursor = hi
    if cursor < length:
        gaps.append((cursor, length))
    return gaps


def merge_runs_with_tags(
    tagged: list[tuple[int, int, dict]],
) -> list[tuple[int, int, list[dict]]]:
    """把所有带标签区间取并集，合并重叠或相邻区间，返回每段上的标签列表。

    标签结构: {"segment_id", "kind": "gap", "k_lo", "k_hi"}。
    运行是全部标签区间并集的连通分量，因此每个标签区间完整包含于恰好一个
    运行内；双指针扫描即可线性分配，整体 O(G log G)（仅排序开销）。
    """
    runs = merge_intervals((lo, hi) for lo, hi, _ in tagged)
    if not runs:
        return []
    ordered = sorted(tagged, key=lambda t: (t[0], t[1]))
    result: list[tuple[int, int, list[dict]]] = []
    j = 0
    for r_lo, r_hi in runs:
        tags = []
        while j < len(ordered) and ordered[j][0] < r_hi:
            lo, hi, tag = ordered[j]
            # 标签不可能跨入另一个运行（否则两运行应相连），故只需断言包含关系
            if lo >= r_lo and hi <= r_hi:
                tags.append(tag)
            j += 1
        result.append((r_lo, r_hi, sorted(tags, key=lambda t: t["segment_id"])))
    return result


# ---------------------------------------------------------------------------
# 原因判定
# ---------------------------------------------------------------------------

def _mismatch_reasons(auth: dict, date: str, region: str, channel: str) -> list[str]:
    reasons = []
    if not (auth["date_from"] <= date <= auth["date_to"]):
        reasons.append("date")
    if auth["region"] != region:
        reasons.append("region")
    if auth["channel"] != channel:
        reasons.append("channel")
    return reasons


_REASON_LABEL = {
    "date": "播出日期不在授权有效期内",
    "region": "授权地区不匹配",
    "channel": "授权渠道不匹配",
}


def classify_gap_reasons(
    queries: list[dict],
    authorizations: list[dict],
    date: str,
    region: str,
    channel: str,
    limit_per_gap: int = 20,
) -> None:
    """为同一素材的一批缺口（query）就地填充 reason 与 candidates。

    queries: [{"lo","hi","pieces":[...]}]，按 lo 排序；缺口片段是源帧区间。
    authorizations: 该素材的全部授权（含维度不匹配的，用于给出候选）。
    使用按起点排序 + 小顶堆的扫描线，整体 O((Q+A) log A)，不展开任何帧。
    """
    auth_sorted = sorted(authorizations, key=lambda a: a["src_lo"])
    heap: list[tuple[int, int]] = []  # (src_hi, 序号)
    i = 0
    n = len(auth_sorted)
    for q in queries:
        lo, hi = q["lo"], q["hi"]
        while i < n and auth_sorted[i]["src_lo"] < hi:
            heapq.heappush(heap, (auth_sorted[i]["src_hi"], i))
            i += 1
        # 惰性清理确定过期的堆顶；其余元素以快照方式参与过滤，随后放回。
        while heap and heap[0][0] <= lo:
            heapq.heappop(heap)
        snapshot = heap
        overlapping = [
            auth_sorted[idx]
            for end, idx in snapshot
            if end > lo and auth_sorted[idx]["src_lo"] < hi
        ]

        candidates = []
        saw_date = saw_region = saw_channel = False
        for auth in overlapping:
            bad = _mismatch_reasons(auth, date, region, channel)
            for b in bad:
                if b == "date":
                    saw_date = True
                elif b == "region":
                    saw_region = True
                else:
                    saw_channel = True
            if len(candidates) < limit_per_gap:
                candidates.append(
                    {
                        "id": auth["id"],
                        "src_lo": auth["src_lo"],
                        "src_hi": auth["src_hi"],
                        "date_from": auth["date_from"],
                        "date_to": auth["date_to"],
                        "region": auth["region"],
                        "channel": auth["channel"],
                        "mismatch": bad,
                    }
                )
        if not overlapping:
            q["reason_code"] = "NO_LICENSE"
            q["reason"] = "该源帧区间没有任何授权登记"
        else:
            parts = [_REASON_LABEL[b] for b in ("date", "region", "channel")
                     if (b == "date" and saw_date or b == "region" and saw_region
                         or b == "channel" and saw_channel)]
            q["reason_code"] = "DIMENSION_MISMATCH"
            q["reason"] = "存在授权但均不匹配：" + "、".join(parts)
        q["candidates"] = candidates


# ---------------------------------------------------------------------------
# 时间线归一化
# ---------------------------------------------------------------------------

def normalize_timeline(data: dict) -> dict:
    """校验并归一化导入的时间线 JSON。

    支持形式：
      {"fps": 25, "materials": [{"id","total_frames","segments":[...]}]}
    或单素材简写：
      {"fps": 25, "total_frames": 1000, "segments": [...]}

    片段: {"id"?, "in", "out", "origin", "speed": int|"p/q"|{"numerator","denominator"}}
    """
    if not isinstance(data, dict):
        raise ValueError("时间线必须是 JSON 对象")
    fps = int(data.get("fps", 25))
    if fps <= 0:
        raise ValueError("fps 必须为正整数")

    raw_materials = data.get("materials")
    if raw_materials is None:
        if "total_frames" not in data:
            raise ValueError("时间线缺少 materials 或 total_frames")
        raw_materials = [{
            "id": data.get("material_id", "M1"),
            "total_frames": data["total_frames"],
            "segments": data.get("segments", []),
        }]

    materials = []
    global_seg_ids: set[str] = set()
    auto_idx = 0
    for m in raw_materials:
        mid = str(m.get("id", f"M{len(materials) + 1}"))
        total = int(m["total_frames"])
        if total <= 0:
            raise ValueError(f"素材 {mid} 的 total_frames 必须为正整数")
        segments = []
        for s in m.get("segments", []):
            seg_in = int(s["in"])
            seg_out = int(s["out"])
            origin = int(s["origin"])
            p, q = parse_speed(s.get("speed", 1))
            if seg_in < 0 or seg_out <= seg_in:
                raise ValueError(f"素材 {mid} 存在非法输出半开区间 [{seg_in},{seg_out})")
            sid = s.get("id")
            if sid is None:
                auto_idx += 1
                sid = f"S{auto_idx}"
            sid = str(sid)
            if sid in global_seg_ids:
                raise ValueError(f"片段 id 重复: {sid}")
            global_seg_ids.add(sid)
            segments.append({
                "id": sid,
                "material_id": mid,
                "in": seg_in,
                "out": seg_out,
                "origin": origin,
                "p": p,
                "q": q,
            })
        materials.append({"id": mid, "total_frames": total, "segments": segments})

    if not any(m["segments"] for m in materials):
        raise ValueError("时间线至少需要一个片段")
    return {"fps": fps, "materials": materials}


# ---------------------------------------------------------------------------
# 主核验流程
# ---------------------------------------------------------------------------

def verify(timeline: dict, authorizations: list[dict],
           date: str, region: str, channel: str) -> dict:
    """对给定播出维度执行核验。返回结构化结果（不展开任何帧）。

    返回:
      status = "rejected" 时含 violations_out_of_bounds；
      status = "ok"       时含 violations（违规运行）、violating_frames、blank_frames 等。
    """
    fps = timeline.get("fps", 25)
    materials = {m["id"]: m for m in timeline["materials"]}
    seg_objects: list[Segment] = []
    timeline_end = 0
    for m in timeline["materials"]:
        for s in m["segments"]:
            seg_objects.append(
                Segment(s["id"], m["id"], s["in"], s["out"],
                        s["origin"], s["p"], s["q"])
            )
            timeline_end = max(timeline_end, s["out"])
    timeline_start = min((s.seg_in for s in seg_objects), default=0)

    # 1) 越界检查：单调性保证只需检查端点源帧。
    oob = []
    for seg in seg_objects:
        lo, hi_ex, first, last = seg.span()
        total = materials[seg.material_id]["total_frames"]
        if lo < 0 or hi_ex > total:
            oob.append({
                "segment_id": seg.id,
                "material_id": seg.material_id,
                "out": seg.seg_in,
                "out_end": seg.seg_out,
                "src_first": first,
                "src_last": last,
                "src_min": lo,
                "src_max": hi_ex - 1,
                "total_frames": total,
                "reason": (
                    f"片段源帧区间 [{lo},{hi_ex}) 越界，素材 {seg.material_id} "
                    f"总帧数 {total}（合法源帧 [0,{total})）"
                ),
            })
    if oob:
        return {
            "status": "rejected",
            "fps": fps,
            "timeline_start": timeline_start,
            "timeline_end": timeline_end,
            "reason": "存在片段映射源帧越界，核验被拒绝",
            "violations_out_of_bounds": oob,
        }

    # 2) 按素材与维度筛选授权。
    auths_by_mat: dict[str, list[dict]] = {mid: [] for mid in materials}
    for a in authorizations:
        if (a.get("material_id") in auths_by_mat
                and a["date_from"] <= date <= a["date_to"]
                and a["region"] == region and a["channel"] == channel):
            auths_by_mat[a["material_id"]].append(a)

    # 3) 逐片段求「未被覆盖的片段下标区间」，带上片段标签。
    tagged_gaps: list[tuple[int, int, dict]] = []
    # 同时按素材收集缺口源帧区间，供原因判定。
    gap_queries_by_mat: dict[str, list[dict]] = {mid: [] for mid in materials}

    for seg in seg_objects:
        covered = []
        for a in auths_by_mat[seg.material_id]:
            hit = covered_k_interval(seg, a["src_lo"], a["src_hi"])
            if hit:
                covered.append(hit)
        for k_lo, k_hi in complement(merge_intervals(covered), seg.length):
            tag = {
                "segment_id": seg.id,
                "material_id": seg.material_id,
                "k_lo": k_lo,
                "k_hi": k_hi,
            }
            tagged_gaps.append((seg.seg_in + k_lo, seg.seg_in + k_hi, tag))
            src_first = seg.src_at(k_lo)
            src_last = seg.src_at(k_hi - 1)
            src_lo, src_hi_ex = min(src_first, src_last), max(src_first, src_last) + 1
            gap_queries_by_mat[seg.material_id].append({
                "lo": src_lo,
                "hi": src_hi_ex,
                "k_lo": k_lo,
                "k_hi": k_hi,
                "segment_id": seg.id,
            })

    # 4) 原因判定（按素材扫描全部授权，含维度不匹配者）。
    reasons_by_seg: dict[str, dict[int, dict]] = {}
    all_auths_by_mat: dict[str, list[dict]] = {mid: [] for mid in materials}
    for a in authorizations:
        if a.get("material_id") in all_auths_by_mat:
            all_auths_by_mat[a["material_id"]].append(a)
    for mid, queries in gap_queries_by_mat.items():
        if not queries:
            continue
        queries.sort(key=lambda q: (q["segment_id"], q["lo"]))
        classify_gap_reasons(queries, all_auths_by_mat[mid], date, region, channel)
        bucket = reasons_by_seg.setdefault(mid, {})
        for q in queries:
            bucket.setdefault(q["segment_id"], {})[(q["k_lo"], q["k_hi"])] = q

    # 5) 在输出时间轴上合并连续违规帧（跨同一片段相邻块、跨重叠片段）。
    runs = merge_runs_with_tags(tagged_gaps)

    violations = []
    violating_frames = 0
    seg_by_id = {s.id: s for s in seg_objects}
    for out_lo, out_hi, tags in runs:
        violating_frames += out_hi - out_lo
        pieces = []
        # 同一片段在该运行内只会有一个标签（片段自身的缺口区间互不重叠）。
        for tag in tags:
            seg = seg_by_id[tag["segment_id"]]
            k_lo, k_hi = tag["k_lo"], tag["k_hi"]
            info = reasons_by_seg[seg.material_id][seg.id][(k_lo, k_hi)]
            pieces.append({
                "segment_id": seg.id,
                "material_id": seg.material_id,
                "out": seg.seg_in + k_lo,
                "out_end": seg.seg_in + k_hi,
                "src_lo": info["lo"],
                "src_hi": info["hi"],
                "origin": seg.origin,
                "speed": f"{seg.p}/{seg.q}",
                "reason_code": info["reason_code"],
                "reason": info["reason"],
                "candidates": info["candidates"],
            })
        violations.append({
            "out": out_lo,
            "out_end": out_hi,
            "frames": out_hi - out_lo,
            "segments": pieces,
        })

    # 6) 统计：输出帧并集 => 活动帧与空白帧。
    active_runs = merge_intervals(
        (s.seg_in, s.seg_out) for s in seg_objects
    )
    active_frames = sum(hi - lo for lo, hi in active_runs)
    timeline_span = max(timeline_end - timeline_start, 0)
    blank_frames = timeline_span - active_frames

    return {
        "status": "ok",
        "fps": fps,
        "timeline_start": timeline_start,
        "timeline_end": timeline_end,
        "selection": {"date": date, "region": region, "channel": channel},
        "segment_count": len(seg_objects),
        "active_frames": active_frames,
        "blank_frames": blank_frames,
        "violating_frames": violating_frames,
        "violation_run_count": len(violations),
        "violations": violations,
    }
