"""Core verification logic.

All computations are interval-based: a ten-million-frame timeline is never
expanded frame-by-frame. Clip output ranges and authorization source ranges
are treated as half-open integer intervals, and coverage is computed with
interval arithmetic using fractions.Fraction for signed fractional speeds.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any


def parse_speed(value: Any) -> Fraction:
    """Parse a signed non-zero fractional speed.

    Accepts strings like "1/2", "-3/2", "2", "-1", or numeric values.
    """
    if isinstance(value, bool):
        raise ValueError("速度必须是非零分数")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError("速度不能为空")
        return Fraction(s)
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(str(value))
    raise ValueError(f"无法解析速度: {value!r}")


def ceil_div(a: int, b: Fraction) -> int:
    """Ceiling of a / b for integer a and positive Fraction b."""
    return -((-a) // b)


def union_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping (but not merely adjacent) half-open intervals."""
    if not intervals:
        return []
    ordered = sorted(intervals)
    result: list[tuple[int, int]] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = result[-1]
        if start < prev_end:  # overlap
            result[-1] = (prev_start, max(prev_end, end))
        else:
            result.append((start, end))
    return result


def subtract_interval(
    lo: int, hi: int, covered: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Return [lo, hi) minus the union of covered intervals (sorted, disjoint)."""
    gaps: list[tuple[int, int]] = []
    cur = lo
    for cs, ce in covered:
        if cs > cur:
            gaps.append((cur, cs))
        cur = max(cur, ce)
    if cur < hi:
        gaps.append((cur, hi))
    return gaps


def validate_timeline(timeline: Any) -> list[str]:
    """Validate a timeline object. Returns a list of error messages (empty if ok)."""
    errors: list[str] = []
    if not isinstance(timeline, dict):
        return ["时间线必须是 JSON 对象"]
    total = timeline.get("total_frames")
    if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
        errors.append("total_frames 必须是正整数")
    clips = timeline.get("clips")
    if not isinstance(clips, list) or len(clips) == 0:
        errors.append("clips 必须是非空数组")
        return errors
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            errors.append(f"clips[{i}] 必须是对象")
            continue
        name = clip.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"clips[{i}].name 必须是非空字符串")
        os_ = clip.get("output_start")
        oe = clip.get("output_end")
        if not isinstance(os_, int) or isinstance(os_, bool) or os_ < 0:
            errors.append(f"片段 {name!r} 的 output_start 必须是非负整数")
        if not isinstance(oe, int) or isinstance(oe, bool) or oe <= os_:
            errors.append(f"片段 {name!r} 的 output_end 必须大于 output_start")
        ss = clip.get("source_start")
        if not isinstance(ss, int) or isinstance(ss, bool) or ss < 0:
            errors.append(f"片段 {name!r} 的 source_start 必须是非负整数")
        try:
            v = parse_speed(clip.get("speed"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"片段 {name!r} 的速度无效: {exc}")
        else:
            if v == 0:
                errors.append(f"片段 {name!r} 的速度必须非零")
    return errors


def _clip_gaps(
    clip: dict,
    total_frames: int,
    matching: list[dict],
) -> tuple[list[dict] | None, str | None]:
    """Compute uncovered output intervals for a single clip.

    Returns (gaps, None) on success, or (None, error_message) if the clip's
    source frames go out of bounds.
    """
    a = clip["output_start"]
    b = clip["output_end"]
    s0 = clip["source_start"]
    v = parse_speed(clip["speed"])
    w = abs(v)
    name = clip["name"]
    clip_id = clip.get("id", name)

    # Bounds check over the whole clip using endpoints only.
    if v > 0:
        min_s = s0
        max_s = s0 + math.floor((b - 1) * w)
    else:
        min_s = s0 - math.floor((b - 1) * w)
        max_s = s0
    if min_s < 0 or max_s >= total_frames:
        return None, (
            f"片段 {name!r} 映射到源帧 [{min_s}, {max_s}]，"
            f"超出有效范围 [0, {total_frames})"
        )

    # Covered output intervals per matching authorization.
    covered: list[tuple[int, int]] = []
    for auth in matching:
        as_ = auth["source_start"]
        ae = auth["source_end"]
        if v > 0:
            k_lo = ceil_div(as_ - s0, w)
            k_hi = ceil_div(ae - s0, w)
        else:
            k_lo = ceil_div(s0 - ae + 1, w)
            k_hi = ceil_div(s0 - as_ + 1, w)
        t_lo = a + k_lo
        t_hi = a + k_hi
        t_lo = max(a, t_lo)
        t_hi = min(b, t_hi)
        if t_lo < t_hi:
            covered.append((t_lo, t_hi))

    covered_union = union_intervals(covered)
    clip_gaps = subtract_interval(a, b, covered_union)

    reasons: list[dict] = []
    for g_lo, g_hi in clip_gaps:
        if v > 0:
            src_lo = s0 + math.floor((g_lo - a) * w)
            src_hi = s0 + math.floor((g_hi - 1 - a) * w) + 1
        else:
            src_max = s0 - math.floor((g_lo - a) * w)
            src_min = s0 - math.floor((g_hi - 1 - a) * w)
            src_lo = src_min
            src_hi = src_max + 1
        reasons.append(
            {
                "clip_id": clip_id,
                "clip_name": name,
                "output_start": g_lo,
                "output_end": g_hi,
                "source_start": src_lo,
                "source_end": src_hi,
            }
        )
    return reasons, None


def compute_violations(
    timeline: dict,
    authorizations: list[dict],
    date: str,
    region: str,
    channel: str,
) -> dict:
    """Compute merged violation segments for a timeline.

    Returns {"ok": True, "violations": [...], "total_violation_frames": int}
    or {"ok": False, "error": str}.
    """
    total_frames = timeline["total_frames"]
    clips = timeline["clips"]

    matching = [
        a
        for a in authorizations
        if a["valid_from"] <= date <= a["valid_to"]
        and a["region"] == region
        and a["channel"] == channel
    ]

    # gaps: list of (start, end, reason)
    gaps: list[tuple[int, int, dict]] = []
    for clip in clips:
        reasons, err = _clip_gaps(clip, total_frames, matching)
        if err is not None:
            return {"ok": False, "error": err}
        for reason in reasons:
            gaps.append((reason["output_start"], reason["output_end"], reason))

    if not gaps:
        return {"ok": True, "violations": [], "total_violation_frames": 0}

    # Merge overlapping or adjacent (consecutive) violating output frames.
    gaps.sort(key=lambda g: g[0])
    merged: list[tuple[int, int, list[dict]]] = []
    for start, end, reason in gaps:
        if merged and start <= merged[-1][1]:
            ps, pe, preasons = merged[-1]
            merged[-1] = (ps, max(pe, end), preasons + [reason])
        else:
            merged.append((start, end, [reason]))

    violations: list[dict] = []
    total_vf = 0
    for start, end, reasons in merged:
        violations.append({"start": start, "end": end, "reasons": reasons})
        total_vf += end - start

    return {
        "ok": True,
        "violations": violations,
        "total_violation_frames": total_vf,
    }
