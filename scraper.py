"""
LinkedIn scraper — extracts title, company, location, apply link.
Uses requests + BeautifulSoup (no Selenium/Chrome needed).
"""

import time
import random
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Seniority → LinkedIn f_E filter codes
SENIORITY_FILTERS = {
    "intern":  "1",   # Internship
    "junior":  "2",   # Entry level
    "mid":     "3",   # Associate
    "senior":  "4",   # Mid-Senior level
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


def build_search_url(keyword: str, seniority: str, offset: int = 0) -> str:
    level_code = SENIORITY_FILTERS.get(seniority, "2")
    kw = keyword.replace(" ", "%20")
    return (
        f"https://il.linkedin.com/jobs/search/"
        f"?keywords={kw}"
        f"&location=Israel"
        f"&f_E={level_code}"
        f"&sortBy=DD"
        f"&f_TPR=r86400"   # Posted in last 24 hours
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


def scrape_jobs(keyword: str, seniority: str, limit: int = 10) -> list[dict]:
    """
    Scrape LinkedIn for jobs matching keyword + seniority.
    Returns list of dicts: {title, company, location, url}
    """
    all_jobs = []
    seen_urls = set()

    for page in range(2):  # 2 pages max (25 results each)
        offset = page * 25
        url = build_search_url(keyword, seniority, offset)
        logger.info(f"Scraping page {page+1}: {url}")

        soup = fetch_page(url)
        if not soup:
            break

        jobs = parse_jobs(soup)
        if not jobs:
            logger.info(f"No jobs on page {page+1}, stopping.")
            break

        for job in jobs:
            if job["url"] not in seen_urls:
                seen_urls.add(job["url"])
                all_jobs.append(job)

        if len(all_jobs) >= limit:
            break

        # Polite delay between pages
        time.sleep(random.uniform(1.5, 3.0))

    logger.info(f"Scraped {len(all_jobs)} unique jobs for '{keyword}' ({seniority})")
    return all_jobs[:limit]
