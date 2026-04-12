"""
LinkedIn scraper — two-pass approach:
  Pass 1: search page  → collect job stubs (title, company, location, job_id)
  Pass 2: job API page → extract the real external apply link + verify recency

Tries last-1-hour jobs first, falls back to last-24-hours if nothing found.
Only jobs with a REAL direct apply link are returned — no LinkedIn post fallbacks.
"""

import re
import json
import time
import random
import logging
import requests
from urllib.parse import urlparse, parse_qs, unquote
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Seniority key → LinkedIn f_E filter code
SENIORITY_CODES = {
    "intern": "1",
    "junior": "2",
    "mid":    "3",
    "senior": "4",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.linkedin.com/jobs/search/",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "navigate",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ── URL builders ──────────────────────────────────────────────────────────

def search_url(keyword: str, seniority_codes: list, time_filter: str, offset: int = 0) -> str:
    """
    time_filter: "r3600" = last hour, "r86400" = last 24 hours
    """
    kw = keyword.replace(" ", "%20")
    level_param = "%2C".join(seniority_codes)
    return (
        f"https://il.linkedin.com/jobs/search/"
        f"?keywords={kw}"
        f"&location=Israel"
        f"&f_E={level_param}"
        f"&sortBy=DD"
        f"&f_TPR={time_filter}"
        f"&start={offset}"
    )


def api_url(job_id: str) -> str:
    """
    LinkedIn's guest job API — returns full job detail HTML including
    the external apply button, no login required.
    """
    return f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"


def public_url(job_id: str) -> str:
    """Public LinkedIn job post page."""
    return f"https://www.linkedin.com/jobs/view/{job_id}/"


# ── Helpers ───────────────────────────────────────────────────────────────

def extract_job_id(url: str) -> str | None:
    """Pull the numeric LinkedIn job ID out of any LinkedIn job URL."""
    match = re.search(r"-(\d{7,})", url)
    if match:
        return match.group(1)
    match = re.search(r"(\d{10,})", url)
    return match.group(1) if match else None


def fetch_page(url: str) -> BeautifulSoup | None:
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        logger.warning(f"Fetch failed [{url}]: {e}")
        return None


def _is_external(href: str) -> bool:
    """Return True if the URL is a real external (non-LinkedIn) apply link."""
    if not href or not href.startswith("http"):
        return False
    blocked = ["linkedin.com/jobs", "linkedin.com/login", "linkedin.com/authwall"]
    return not any(b in href for b in blocked)


# ── Pass 1: search page → job stubs ──────────────────────────────────────

def parse_search_page(soup: BeautifulSoup, seen_ids: set) -> list[dict]:
    """
    Extract job stubs from the LinkedIn search results page.
    Each stub: {job_id, title, company, location, linkedin_url}
    """
    stubs = []
    for card in soup.select("ul.jobs-search__results-list li"):
        try:
            title_el = card.select_one("h3.base-search-card__title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title:
                continue

            link_el = card.select_one("a.base-card__full-link")
            if not link_el:
                continue
            linkedin_url = link_el.get("href", "").split("?")[0]
            job_id = extract_job_id(linkedin_url)
            if not job_id or job_id in seen_ids:
                continue

            company_el = card.select_one("h4.base-search-card__subtitle")
            company = company_el.get_text(strip=True) if company_el else "N/A"

            location_el = card.select_one("span.job-search-card__location")
            location = location_el.get_text(strip=True) if location_el else "Israel"

            stubs.append({
                "job_id":       job_id,
                "title":        title,
                "company":      company,
                "location":     location,
                "linkedin_url": linkedin_url,
            })
        except Exception as e:
            logger.debug(f"Card parse error: {e}")
            continue
    return stubs


# ── Pass 2: multi-source apply link extraction ────────────────────────────

def _unwrap_safety_url(href: str) -> str:
    """
    LinkedIn wraps external apply links in a safety redirect:
      https://www.linkedin.com/safety/go/?url=https%3A%2F%2F...&urlhash=...
    This function extracts and URL-decodes the real destination URL.
    If the href is not a safety redirect, returns it unchanged.
    """
    if "linkedin.com/safety/go" in href:
        try:
            params = parse_qs(urlparse(href).query)
            real = params.get("url", [None])[0]
            if real:
                return unquote(real)
        except Exception:
            pass
    return href


def get_apply_link(job_id: str) -> str | None:
    """
    Try multiple sources in order to find the real external apply URL.

    Source 1 — Public job post page
                → <a aria-label="Apply on company website"> with a
                  linkedin.com/safety/go/?url=REAL_URL redirect href.
                  This is exactly what the browser renders.

    Source 2 — Guest API page (lightweight fallback)

    Returns the direct company apply URL, or None if only Easy Apply is available.
    """

    # ── Source 1: Public job post page ───────────────────────────────────
    # LinkedIn wraps the real URL in: /safety/go/?url=<encoded_real_url>
    # The <a> tag always has aria-label="Apply on company website"
    time.sleep(random.uniform(0.5, 1.0))
    soup = fetch_page(public_url(job_id))
    if soup:
        # Primary: aria-label targets the exact button we see in the browser
        el = soup.find("a", attrs={"aria-label": "Apply on company website"})
        if el:
            href = el.get("href", "")
            real = _unwrap_safety_url(href)
            if _is_external(real):
                logger.debug(f"[{job_id}] Found via aria-label (public page): {real}")
                return real

        # Fallback A: any <a> whose href contains /safety/go/ and points off-LinkedIn
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "linkedin.com/safety/go" in href:
                real = _unwrap_safety_url(href)
                if _is_external(real):
                    logger.debug(f"[{job_id}] Found via safety/go scan: {real}")
                    return real

        # Fallback B: scan embedded JSON blobs for companyApplyUrl
        for script in soup.find_all("script", type="application/json"):
            try:
                raw = script.string or ""
                if "companyApplyUrl" not in raw and "applyMethod" not in raw:
                    continue
                data = json.loads(raw)
                url = _dig_apply_url(data)
                if url:
                    real = _unwrap_safety_url(url)
                    if _is_external(real):
                        logger.debug(f"[{job_id}] Found via JSON blob: {real}")
                        return real
            except Exception:
                continue

        # Fallback C: regex over inline scripts
        for script in soup.find_all("script"):
            raw = script.string or ""
            if "companyApplyUrl" not in raw and "applyUrl" not in raw:
                continue
            for pattern in [
                r'"companyApplyUrl"\s*:\s*"(https?://[^"]+)"',
                r'"applyUrl"\s*:\s*"(https?://[^"]+)"',
            ]:
                match = re.search(pattern, raw)
                if match:
                    href = match.group(1).replace("\\u0026", "&").replace("\\/", "/")
                    real = _unwrap_safety_url(href)
                    if _is_external(real):
                        logger.debug(f"[{job_id}] Found via script regex: {real}")
                        return real

    # ── Source 2: Guest API (lightweight second attempt) ──────────────────
    time.sleep(random.uniform(0.5, 1.0))
    soup2 = fetch_page(api_url(job_id))
    if soup2:
        for selector in [
            "a.apply-button--link",
            "a[data-tracking-control-name='public_jobs_apply-link-offsite_sign-up-modal']",
            "a[data-tracking-control-name='public_jobs_apply-link-offsite']",
            "a.apply-button",
        ]:
            el = soup2.select_one(selector)
            if el:
                href = el.get("href", "")
                real = _unwrap_safety_url(href)
                if _is_external(real):
                    logger.debug(f"[{job_id}] Found via guest API selector: {real}")
                    return real

        for a in soup2.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            href = a["href"]
            if "apply" in text:
                real = _unwrap_safety_url(href)
                if _is_external(real):
                    logger.debug(f"[{job_id}] Found via guest API text scan: {real}")
                    return real

    logger.debug(f"[{job_id}] No external apply link found (likely Easy Apply only)")
    return None


def _dig_apply_url(obj, depth: int = 0) -> str | None:
    """
    Recursively walk a parsed JSON object looking for companyApplyUrl
    or applyMethod.easyApplyUrl / companyApplyUrl keys.
    Limit recursion depth to avoid infinite loops on huge blobs.
    """
    if depth > 8:
        return None
    if isinstance(obj, dict):
        for key in ("companyApplyUrl", "applyUrl", "externalApplyLink"):
            if key in obj and isinstance(obj[key], str) and obj[key].startswith("http"):
                return obj[key]
        for v in obj.values():
            result = _dig_apply_url(v, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _dig_apply_url(item, depth + 1)
            if result:
                return result
    return None


# ── Core scrape functions ─────────────────────────────────────────────────

def scrape_one_role(
    keyword: str,
    seniority_codes: list,
    seen_ids: set,
    time_filter: str,
    per_role_limit: int = 5,
) -> list[dict]:
    """
    Scrape one role keyword, two-pass:
      1. Collect stubs from search page
      2. Fetch real apply link for each stub
      3. SKIP any job that has no direct external apply link (Easy Apply only)
    """
    results = []

    for page in range(2):  # up to 2 pages per role
        offset = page * 25
        url = search_url(keyword, seniority_codes, time_filter, offset)
        soup = fetch_page(url)
        if not soup:
            break

        stubs = parse_search_page(soup, seen_ids)
        if not stubs:
            break

        for stub in stubs:
            if len(results) >= per_role_limit:
                break

            seen_ids.add(stub["job_id"])  # mark as seen regardless of outcome

            apply_link = get_apply_link(stub["job_id"])

            # ✅ Only include jobs with a real external apply link
            if not apply_link:
                logger.debug(f"Skipping {stub['title']} @ {stub['company']} — no direct link")
                continue

            results.append({
                "title":           stub["title"],
                "company":         stub["company"],
                "location":        stub["location"],
                "url":             apply_link,
                "has_direct_link": True,
            })

            # Polite delay between API calls
            time.sleep(random.uniform(1.0, 2.0))

        if len(results) >= per_role_limit:
            break

        time.sleep(random.uniform(1.5, 2.5))

    return results


def scrape_jobs_multi(
    role_keys: list,
    seniority_keys: list,
    role_keywords_map: dict,
    limit: int = 15,
) -> list[dict]:
    """
    Main entry point. Scrapes multiple roles + seniority levels.

    Strategy:
      - First try last-1-hour jobs (freshest possible)
      - If total results < 5, fall back to last-24-hours

    Returns up to `limit` unique jobs, all with direct company apply links.
    """
    codes = [SENIORITY_CODES[s] for s in seniority_keys if s in SENIORITY_CODES]
    if not codes:
        codes = ["2"]

    per_role = max(3, limit // max(len(role_keys), 1))

    def run_scrape(time_filter: str) -> list[dict]:
        seen_ids: set = set()
        all_jobs: list = []
        for role_key in role_keys:
            keyword = role_keywords_map.get(role_key, role_key.replace("_", " ").title())
            jobs = scrape_one_role(keyword, codes, seen_ids, time_filter, per_role_limit=per_role)
            all_jobs.extend(jobs)
            if len(all_jobs) >= limit:
                break
            time.sleep(random.uniform(1.0, 1.5))
        return all_jobs[:limit]

    # Try last hour first
    logger.info("Trying last-1-hour jobs...")
    jobs = run_scrape("r3600")

    if len(jobs) < 5:
        logger.info(f"Only {len(jobs)} jobs in last hour — falling back to last 24 hours")
        jobs = run_scrape("r86400")

    logger.info(f"Scraped {len(jobs)} jobs total — all with direct apply links")
    return jobs