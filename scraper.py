"""
LinkedIn scraper — extracts title, company, location, apply link.
Supports multiple roles and multiple seniority levels per user.
"""

import time
import random
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Seniority key → LinkedIn f_E filter code
SENIORITY_CODES = {
    "intern":  "1",
    "junior":  "2",
    "mid":     "3",
    "senior":  "4",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def build_search_url(keyword: str, seniority_codes: list, offset: int = 0) -> str:
    kw = keyword.replace(" ", "%20")
    level_param = "%2C".join(seniority_codes)  # e.g. "2%2C3" for junior+mid
    return (
        f"https://il.linkedin.com/jobs/search/"
        f"?keywords={kw}"
        f"&location=Israel"
        f"&f_E={level_param}"
        f"&sortBy=DD"
        f"&f_TPR=r86400"
        f"&start={offset}"
    )


def fetch_page(url: str) -> BeautifulSoup | None:
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def parse_jobs(soup: BeautifulSoup) -> list[dict]:
    jobs = []
    cards = soup.select("ul.jobs-search__results-list li")

    for card in cards:
        try:
            title_el = card.select_one("h3.base-search-card__title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)

            company_el = card.select_one("h4.base-search-card__subtitle")
            company = company_el.get_text(strip=True) if company_el else "N/A"

            location_el = card.select_one("span.job-search-card__location")
            location = location_el.get_text(strip=True) if location_el else "Israel"

            link_el = card.select_one("a.base-card__full-link")
            if not link_el:
                continue
            url = link_el.get("href", "").split("?")[0]

            if not url or not title:
                continue

            jobs.append({
                "title":    title,
                "company":  company,
                "location": location,
                "url":      url,
            })
        except Exception as e:
            logger.debug(f"Card parse error: {e}")
            continue

    return jobs


def scrape_one_role(keyword: str, seniority_codes: list, limit: int = 10) -> list[dict]:
    """Scrape one role keyword across the given seniority codes."""
    all_jobs = []
    seen_urls = set()

    for page in range(2):
        offset = page * 25
        url = build_search_url(keyword, seniority_codes, offset)
        logger.info(f"Scraping '{keyword}' page {page+1}")

        soup = fetch_page(url)
        if not soup:
            break

        jobs = parse_jobs(soup)
        if not jobs:
            break

        for job in jobs:
            if job["url"] not in seen_urls:
                seen_urls.add(job["url"])
                all_jobs.append(job)

        if len(all_jobs) >= limit:
            break

        time.sleep(random.uniform(1.5, 2.5))

    return all_jobs[:limit]


def scrape_jobs_multi(
    role_keys: list,
    seniority_keys: list,
    role_keywords_map: dict,
    limit: int = 15,
) -> list[dict]:
    """
    Scrape multiple roles + multiple seniority levels.
    Deduplicates across all role searches.
    Returns up to `limit` unique jobs total.
    """
    # Convert seniority keys to LinkedIn codes
    codes = [SENIORITY_CODES[s] for s in seniority_keys if s in SENIORITY_CODES]
    if not codes:
        codes = ["2"]  # default to junior

    all_jobs = []
    seen_urls = set()

    for role_key in role_keys:
        keyword = role_keywords_map.get(role_key, role_key.replace("_", " ").title())
        jobs = scrape_one_role(keyword, codes, limit=8)

        for job in jobs:
            if job["url"] not in seen_urls:
                seen_urls.add(job["url"])
                all_jobs.append(job)

        if len(all_jobs) >= limit:
            break

        # Polite delay between different role searches
        time.sleep(random.uniform(1.0, 2.0))

    logger.info(f"Total scraped: {len(all_jobs)} unique jobs across {len(role_keys)} roles")
    return all_jobs[:limit]
