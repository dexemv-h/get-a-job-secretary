"""사람인 알림 메일에서 공고 URL 파싱."""
import re
from typing import Generator


# 사람인 공고 URL 패턴: https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=XXXXXXXX
_REC_IDX_RE = re.compile(r"rec_idx[=\-](\d+)", re.IGNORECASE)
_URL_RE = re.compile(
    r"https?://(?:www\.)?saramin\.co\.kr[^\s\"'<>]*rec_idx[^\s\"'<>]*",
    re.IGNORECASE,
)


def extract_job_urls(body_text: str) -> Generator[str, None, None]:
    """
    사람인 메일 본문에서 공고 URL 목록 추출.

    메일 본문에 직접 URL이 있으면 그대로 반환,
    없으면 rec_idx만 뽑아 표준 URL 재구성.
    """
    # 1) 직접 URL 있는 경우
    found_direct = False
    for m in _URL_RE.finditer(body_text):
        yield m.group(0).rstrip(".,;)")
        found_direct = True

    if found_direct:
        return

    # 2) rec_idx만 있는 경우 → URL 재구성
    for m in _REC_IDX_RE.finditer(body_text):
        rec_idx = m.group(1)
        yield (
            f"https://www.saramin.co.kr/zf_user/jobs/relay/view"
            f"?rec_idx={rec_idx}&utm_source=email"
        )
