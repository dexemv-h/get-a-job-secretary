"""잡코리아 알림 메일에서 공고 URL 파싱."""
import re
from typing import Generator


# 잡코리아 공고 URL 패턴: https://www.jobkorea.co.kr/Recruit/GI_Read/XXXXXXXX
_GI_URL_RE = re.compile(
    r"https?://(?:www\.)?jobkorea\.co\.kr[^\s\"'<>]*(?:GI_Read|recruit)[^\s\"'<>]*",
    re.IGNORECASE,
)
_GI_ID_RE = re.compile(r"GI_Read[/=](\d+)", re.IGNORECASE)


def extract_job_urls(body_text: str) -> Generator[str, None, None]:
    """잡코리아 메일 본문에서 공고 URL 목록 추출."""
    found_direct = False
    for m in _GI_URL_RE.finditer(body_text):
        yield m.group(0).rstrip(".,;)")
        found_direct = True

    if found_direct:
        return

    for m in _GI_ID_RE.finditer(body_text):
        gi_id = m.group(1)
        yield f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gi_id}"
