"""
여러 답변 누적 → Floor / Ceiling 추정.

단일 답변으로는 전체 등급을 확정하지 않는다.
min_answers_for_overall(기본 5) 이상 쌓였을 때만 시험 전체 예상 등급을 산출하고,
그 전까지는 "판단 보류"로 표시한다.

Floor   여러 문제·여러 주제에서 안정적으로 반복 수행 가능한 최고 수준
Ceiling 시도는 하지만 지속하지 못하고 breakdown 이 발생하는 수준
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .calibration import opic_dir
from .rater import OpicRating
from .rubric import (
    DEFAULT_ADVANCED_FUNCTIONS,
    DEFAULT_AL_REQUIRED,
    FUNCTION_ITEMS,
    GRADES,
    format_range,
    grade_index,
)

# status → Advanced 기능 수행 점수
_STATUS_SCORE = {"stable": 1.0, "partial": 0.5, "weak": 0.0}

HOLD = "판단 보류"


@dataclass
class ProfileSummary:
    n_answers: int
    floor: str
    ceiling: str
    predicted_grade: str            # 데이터가 부족하면 "판단 보류"
    predicted_range: str
    al_probability: int             # 0-100 (휴리스틱 추정치)
    advanced_success: int
    advanced_total: int
    function_stability: dict[str, dict[str, int]] = field(default_factory=dict)
    breakdown_conditions: list[str] = field(default_factory=list)
    untested_functions: list[str] = field(default_factory=list)   # 한 번도 평가되지 않은 항목
    al_blockers: list[str] = field(default_factory=list)          # AL 판정을 막은 미확인 항목
    reason: str = ""


def _advanced_score(rating: OpicRating, advanced_keys: list[str]) -> float | None:
    """한 답변의 Advanced 기능 수행 점수(0~1). 평가 가능한 항목이 없으면 None."""
    scores = [
        _STATUS_SCORE[rating.function_status(k)]
        for k in advanced_keys
        if rating.function_status(k) in _STATUS_SCORE
    ]
    if not scores:
        return None
    return sum(scores) / len(scores)


def _estimate_floor(ratings: list[OpicRating], floor_ratio: float) -> str:
    """
    floor_ratio 이상의 답변이 하한으로 도달한 최고 등급.

    한두 개의 뛰어난 답변이 Floor를 끌어올리지 못하게 하는 것이 목적이다.
    """
    n = len(ratings)
    lows = [grade_index(r.level_low) for r in ratings]
    needed = max(1, int(round(n * floor_ratio)))

    floor_idx = 0
    for idx in range(len(GRADES)):
        if sum(1 for low in lows if low >= idx) >= needed:
            floor_idx = idx
        else:
            break
    return GRADES[floor_idx]


def summarize_profile(ratings: list[OpicRating], settings: dict) -> ProfileSummary:
    """
    누적된 답변 평가들로 Floor / Ceiling / 전체 예상 등급을 추정.

    Args:
        ratings: 같은 응시자의 답변 평가 결과들
        settings: settings.yaml 전체 dict
    """
    cfg = settings.get("opic_coach", {})
    min_answers = cfg.get("min_answers_for_overall", 5)
    floor_ratio = cfg.get("floor_ratio", 0.7)
    al_ratio = cfg.get("al_advanced_success_ratio", 0.8)
    success_threshold = cfg.get("advanced_success_threshold", 0.7)
    advanced_keys = cfg.get("advanced_functions", DEFAULT_ADVANCED_FUNCTIONS)
    al_required = cfg.get("al_required_functions", DEFAULT_AL_REQUIRED)

    n = len(ratings)
    if n == 0:
        return ProfileSummary(
            n_answers=0, floor=HOLD, ceiling=HOLD,
            predicted_grade=HOLD, predicted_range=HOLD,
            al_probability=0, advanced_success=0, advanced_total=0,
            reason="평가된 답변이 없습니다.",
        )

    floor = _estimate_floor(ratings, floor_ratio)
    ceiling = GRADES[max(grade_index(r.level_high) for r in ratings)]

    # Advanced 기능 성공/붕괴 카운트
    scored = [(r, _advanced_score(r, advanced_keys)) for r in ratings]
    evaluable = [(r, s) for r, s in scored if s is not None]
    advanced_total = len(evaluable)
    advanced_success = sum(1 for _, s in evaluable if s >= success_threshold)
    adv_ratio = advanced_success / advanced_total if advanced_total else 0.0

    # 기능별 안정성 집계
    stability: dict[str, dict[str, int]] = {
        key: {"stable": 0, "partial": 0, "weak": 0, "na": 0} for key in FUNCTION_ITEMS
    }
    for r in ratings:
        for key in FUNCTION_ITEMS:
            stability[key][r.function_status(key)] += 1

    # 한 번도 평가되지 않은 항목 — 해당 기능을 요구하는 문항이 없었거나 건너뛴 경우
    untested = [
        FUNCTION_ITEMS[k] for k in advanced_keys
        if stability[k]["stable"] + stability[k]["partial"] + stability[k]["weak"] == 0
    ]

    # AL 은 "여러 상황에서 유지"가 조건이므로, 확인조차 안 된 기능이 있으면 줄 수 없다.
    al_blockers = [
        FUNCTION_ITEMS[k] for k in al_required
        if stability.get(k, {}).get("stable", 0) == 0
    ]

    # breakdown 조건: weak + partial 이 많은 항목 상위 3개
    ranked = sorted(
        FUNCTION_ITEMS,
        key=lambda k: -(stability[k]["weak"] * 2 + stability[k]["partial"]),
    )
    breakdown_conditions = [
        f"{FUNCTION_ITEMS[k]}: 부족 {stability[k]['weak']}회 / 부분적 {stability[k]['partial']}회 (총 {n}개 답변)"
        for k in ranked[:3]
        if stability[k]["weak"] or stability[k]["partial"]
    ]

    # AL 가능성 (휴리스틱): Advanced 기능 성공률 × AL 상한을 보인 답변 비율
    al_share = sum(1 for r in ratings if r.level_high == "AL") / n
    prob = 100 * adv_ratio * al_share
    if grade_index(floor) < grade_index("IH"):
        prob *= 0.5
    al_probability = int(round(min(prob, 95)))

    # 전체 예상 등급
    if n < min_answers:
        predicted = HOLD
        reason = (
            f"답변이 {n}개뿐이라 시험 전체 등급은 확정하지 않는다. "
            f"최소 {min_answers}개 이상의 서로 다른 질문에서 지속적인 수행을 확인해야 한다."
        )
    else:
        if (
            grade_index(floor) >= grade_index("IH")
            and adv_ratio >= al_ratio
            and ceiling == "AL"
            and not al_blockers
        ):
            predicted = "AL"
            reason = (
                f"Advanced 기능이 {advanced_success}/{advanced_total} 답변에서 성공했고 "
                f"Floor 자체가 {floor}이다. 여러 주제에서 Advanced 수행이 유지된다고 볼 수 있다."
            )
        else:
            predicted = floor
            reason = (
                f"Advanced 기능 성공 {advanced_success}/{advanced_total}, "
                f"breakdown {advanced_total - advanced_success}/{advanced_total}. "
                f"Ceiling은 {ceiling}까지 올라가지만 여러 상황에서 안정적으로 유지되지 않아 "
                f"Floor인 {floor}을 전체 예상 등급으로 본다."
            )
            # AL 전제 기능이 확인되지 않았다면 Floor 가 AL 로 계산됐더라도 AL 을 줄 수 없다.
            # 이 경우 예측 등급의 상한을 IH 로 내린다.
            if al_blockers:
                capped = GRADES[min(grade_index(floor), grade_index("IH"))]
                if capped != predicted:
                    reason = (
                        f"Floor 계산은 {floor}까지 올라가지만 "
                        f"{', '.join(al_blockers)} 항목에서 안정적인 수행이 한 번도 확인되지 않았다. "
                        f"AL 은 여러 상황에서 Advanced 기능을 유지하는지가 조건이므로, "
                        f"확인되지 않은 기능이 있는 상태에서는 {capped}까지만 인정한다 — "
                        f"해당 기능을 요구하는 문항으로 확인이 필요하다."
                    )
                    predicted = capped
                elif grade_index(floor) >= grade_index("IH"):
                    reason += (
                        f" 또한 {', '.join(al_blockers)} 항목이 확인되지 않아 "
                        f"AL 판정 자체가 불가능하다."
                    )

    return ProfileSummary(
        n_answers=n,
        floor=floor,
        ceiling=ceiling,
        predicted_grade=predicted,
        predicted_range=format_range(floor, ceiling),
        al_probability=al_probability,
        advanced_success=advanced_success,
        advanced_total=advanced_total,
        function_stability=stability,
        breakdown_conditions=breakdown_conditions,
        untested_functions=untested,
        al_blockers=al_blockers,
        reason=reason,
    )


def format_profile_report(summary: ProfileSummary, ratings: list[OpicRating]) -> str:
    """누적 평가 요약을 마크다운으로 포맷."""
    lines = [
        "# 누적 평가 요약\n",
        f"답변 수: {summary.n_answers}개\n",
        f"Floor: {summary.floor}",
        f"Ceiling: {summary.ceiling}",
        f"예상 OPIc: {summary.predicted_grade}",
        f"가능 범위: {summary.predicted_range}",
        f"AL 가능성: {summary.al_probability}% (휴리스틱 추정치)",
        f"Advanced 기능 성공: {summary.advanced_success} / {summary.advanced_total}",
        f"Advanced 기능 breakdown: {summary.advanced_total - summary.advanced_success} / {summary.advanced_total}\n",
        f"이유: {summary.reason}\n",
        "## 답변별 수행 수준\n",
    ]
    for i, r in enumerate(ratings, 1):
        q = r.question if len(r.question) <= 60 else r.question[:57] + "..."
        lines.append(f"{i}. {r.level} (확신도 {r.confidence}) — {q}")

    lines.append("\n## 기능별 안정성\n")
    for key, label in FUNCTION_ITEMS.items():
        c = summary.function_stability.get(key, {})
        lines.append(
            f"- {label}: 안정 {c.get('stable', 0)} / 부분 {c.get('partial', 0)} / "
            f"부족 {c.get('weak', 0)} / 평가불가 {c.get('na', 0)}"
        )

    if summary.untested_functions:
        lines.append("\n## 평가되지 않은 기능\n")
        lines.append(
            f"- {', '.join(summary.untested_functions)} — 해당 기능을 요구하는 문항이 없었거나 "
            f"건너뛰었다. 이 상태의 등급은 신뢰도가 낮다."
        )
    if summary.al_blockers:
        lines.append("\n## AL 판정 차단 사유\n")
        lines.append(
            f"- {', '.join(summary.al_blockers)} 에서 '안정적' 수행이 한 번도 확인되지 않음"
        )

    lines.append("\n## breakdown 발생 조건\n")
    if summary.breakdown_conditions:
        lines += [f"- {b}" for b in summary.breakdown_conditions]
    else:
        lines.append("- 반복적으로 무너지는 항목 없음")

    return "\n".join(lines) + "\n"


def save_session_report(report: str, name: str = "") -> Path:
    """세션 리포트를 $OPIC_DIR/sessions/ 아래 마크다운으로 저장."""
    sessions = opic_dir() / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name) if name else "session"
    path = sessions / f"{stamp}-{safe}.md"
    path.write_text(report, encoding="utf-8")
    return path
