"""
공고 URL을 실제로 열어서 지역/직무명을 확정한 뒤
설정 필터를 통과한 공고만 반환.

"메일 타이틀만 믿으면 인천·경기도 공고가 섞여 들어온다"는 문제를
URL 한 번 더 열어서 차단.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


@dataclass
class JobPosting:
    url: str
    title: str = ""
    company: str = ""
    location: str = ""
    experience: str = ""
    deadline: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = ""       # saramin / jobkorea / wanted


def fetch_job_detail(url: str, timeout: int = 10) -> Optional[JobPosting]:
    """
    공고 URL을 GET으로 열어 상세 정보를 파싱.
    파싱 실패 시 None 반환.
    """
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    if "saramin" in url:
        return _parse_saramin(url, soup)
    if "jobkorea" in url:
        return _parse_jobkorea(url, soup)
    if "wanted" in url:
        return _parse_wanted(url, soup)

    # 알 수 없는 플랫폼: 타이틀만 추출
    title = soup.find("title")
    return JobPosting(url=url, title=title.text.strip() if title else "", source="unknown")


def _parse_saramin(url: str, soup: BeautifulSoup) -> JobPosting:
    posting = JobPosting(url=url, source="saramin")
    posting.title = _text(soup, ".job_tit span") or _text(soup, "h1.tit_job")
    posting.company = _text(soup, ".corp_name a") or _text(soup, ".company_nm")
    posting.location = _text(soup, ".work_place") or _text(soup, ".info_period .cont")
    posting.experience = _text(soup, ".career") or ""
    posting.deadline = _text(soup, ".date") or ""
    return posting


def _parse_jobkorea(url: str, soup: BeautifulSoup) -> JobPosting:
    posting = JobPosting(url=url, source="jobkorea")
    posting.title = _text(soup, ".tit-job-offer") or _text(soup, "h1.title")
    posting.company = _text(soup, ".name") or _text(soup, ".corp-name")
    posting.location = _text(soup, ".work-place") or _text(soup, ".info-item .cont")
    posting.experience = _text(soup, ".career") or ""
    return posting


def _parse_wanted(url: str, soup: BeautifulSoup) -> JobPosting:
    posting = JobPosting(url=url, source="wanted")
    posting.title = _text(soup, "h2.position-title") or _text(soup, "h1")
    posting.company = _text(soup, ".company-name") or ""
    posting.location = _text(soup, ".location") or ""
    return posting


def _text(soup: BeautifulSoup, selector: str) -> str:
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else ""


def passes_filter(posting: JobPosting, settings: dict) -> bool:
    """
    settings.yaml의 job_filter 설정을 기준으로 공고 통과 여부 판단.
    True면 트래커에 추가할 공고.
    """
    f = settings.get("job_filter", {})

    # 1) 지역 필터
    allowed = f.get("allowed_locations", [])
    if allowed:
        location_str = posting.location.lower()
        if not any(loc in location_str for loc in [a.lower() for a in allowed]):
            return False

    # 2) 제외 키워드 필터
    exclude = f.get("exclude_keywords", [])
    title_lower = posting.title.lower()
    if any(kw.lower() in title_lower for kw in exclude):
        return False

    # 3) 타겟 직무 키워드
    target = f.get("target_roles", [])
    if target:
        if not any(t.lower() in title_lower for t in target):
            return False

    return True


def fetch_and_filter(
    urls: list[str],
    settings: dict,
    delay_seconds: float = 1.0,
) -> list[JobPosting]:
    """
    URL 목록을 순회하며 상세 조회 → 필터 통과한 것만 반환.
    rate-limiting 방지용 delay 삽입.
    """
    results = []
    for url in urls:
        posting = fetch_job_detail(url)
        if posting and passes_filter(posting, settings):
            results.append(posting)
        time.sleep(delay_seconds)
    return results
