"""
여러 답변 누적 → Floor / Ceiling 추정.

단일 답변으로는 전체 등급을 확정하지 않는다.
min_answers_for_overall(기본 5) 이상 쌓였을 때만 시험 전체 예상 등급을 산출하고,
그 전까지는 "판단 보류"로 표시한다.

Floor   여러 문제·여러 주제에서 안정적으로 반복 수행 가능한 최고 수준
Ceiling 시도는 하지만 지속하지 못하고 breakdown 이 발생하는 수준

UserBaseline (실제로 받았던 등급)은 사후 비교에만 쓴다.
채점 프롬프트에 넣으면 모델이 그 등급에 앵커링돼 모든 답변이 그 근처로 수렴하므로,
평가는 언제나 baseline 을 모르는 상태로 수행한다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
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
class UserBaseline:
    """실제로 받았던 OPIc 등급. 예측 검증용 기준선."""
    actual_grade: str
    taken_on: str = ""      # "2024-08" 처럼 응시 시점
    target_grade: str = ""
    note: str = ""
    updated_at: str = ""


def baseline_path() -> Path:
    return opic_dir() / "profile.json"


def save_baseline(baseline: UserBaseline) -> Path:
    """기준선 저장. 등급 문자열은 사다리 위 값이어야 한다."""
    if grade_index(baseline.actual_grade) < 0:
        raise ValueError(f"actual_grade 는 {GRADES} 중 하나여야 합니다: {baseline.actual_grade}")
    if baseline.target_grade and grade_index(baseline.target_grade) < 0:
        raise ValueError(f"target_grade 는 {GRADES} 중 하나여야 합니다: {baseline.target_grade}")

    baseline.actual_grade = baseline.actual_grade.strip().upper()
    baseline.target_grade = baseline.target_grade.strip().upper()
    baseline.updated_at = datetime.now().isoformat(timespec="seconds")

    path = baseline_path()
    path.write_text(json.dumps(asdict(baseline), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_baseline() -> UserBaseline | None:
    """저장된 기준선을 읽는다. 없으면 None."""
    path = baseline_path()
    if not path.exists():
        return None
    return UserBaseline(**json.loads(path.read_text(encoding="utf-8")))


def compare_to_baseline(predicted: str, baseline: UserBaseline) -> str:
    """
    예측 등급과 실제 응시 등급의 괴리를 해석한다.

    예측이 위로 크게 벌어지면 과대평가 신호로 본다.
    다만 실제 응시 이후 실력이 올랐을 수도 있으므로 단정하지 않는다.
    """
    if predicted == HOLD:
        return (
            f"기준선: 실제 {baseline.actual_grade}"
            f"{' (' + baseline.taken_on + ')' if baseline.taken_on else ''}. "
            f"답변이 더 쌓이면 예측과 비교한다."
        )

    gap = grade_index(predicted) - grade_index(baseline.actual_grade)
    taken = f" ({baseline.taken_on} 응시)" if baseline.taken_on else ""
    head = f"기준선 대비: 실제 {baseline.actual_grade}{taken} → 이번 예측 {predicted}"

    if gap >= 2:
        body = (
            f" — {gap}단계 위. 그 사이 실력이 올랐을 수도 있지만, 이 정도 격차는 "
            f"과대평가를 먼저 의심해야 한다. 특히 실제 시험은 긴장·즉흥성·시간 압박이 "
            f"더해지므로 연습 환경 점수가 높게 나오기 쉽다."
        )
    elif gap == 1:
        body = " — 한 단계 위. 실력 향상이거나 소폭 과대평가. 다음 세션에서 재현되는지 확인 필요."
    elif gap == 0:
        body = " — 일치. 예측 기준이 실제 응시 결과와 어긋나지 않는다."
    else:
        body = (
            f" — {abs(gap)}단계 아래. 이번 세션 컨디션 문제이거나, "
            f"연습 답변이 실제 시험만큼 충분히 길지 않았을 수 있다."
        )

    if baseline.target_grade:
        to_target = grade_index(baseline.target_grade) - grade_index(predicted)
        if to_target > 0:
            body += f" 목표 {baseline.target_grade}까지 {to_target}단계 남았다."
        elif to_target == 0:
            body += f" 목표 {baseline.target_grade}에 도달한 예측이다."
        else:
            body += f" 목표 {baseline.target_grade}를 넘어선 예측이다."

    return head + body


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
    baseline_note: str = ""                                       # 실제 응시 등급과의 비교
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


def summarize_profile(
    ratings: list[OpicRating],
    settings: dict,
    baseline: UserBaseline | None = None,
) -> ProfileSummary:
    """
    누적된 답변 평가들로 Floor / Ceiling / 전체 예상 등급을 추정.

    Args:
        ratings: 같은 응시자의 답변 평가 결과들
        settings: settings.yaml 전체 dict
        baseline: 실제로 받았던 등급 (사후 비교용, 평가 자체에는 영향 없음)
    """
    cfg = settings.get("opic_coach", {})
    min_answers = cfg.get("min_answers_for_overall", 5)
    floor_ratio = cfg.get("floor_ratio", 0.7)
    al_ratio = cfg.get("al_advanced_success_ratio", 0.8)
    success_threshold = cfg.get("advanced_success_threshold", 0.7)
    advanced_keys = cfg.get("advanced_functions", DEFAULT_ADVANCED_FUNCTIONS)
    al_required = cfg.get("al_required_functions", DEFAULT_AL_REQUIRED)

    n = len(ratings)
    baseline = baseline if baseline is not None else load_baseline()

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
        baseline_note=compare_to_baseline(predicted, baseline) if baseline else "",
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
    ]
    if summary.baseline_note:
        lines += [f"{summary.baseline_note}\n"]
    lines += [
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
