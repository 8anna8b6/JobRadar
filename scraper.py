
import re
import time
import random
import logging
import requests
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
                "job_id":      job_id,
                "title":       title,
                "company":     company,
                "location":    location,
                "linkedin_url": linkedin_url,
            })
        except Exception as e:
            logger.debug(f"Card parse error: {e}")
            continue
    return stubs


# ── Pass 2: job API page → real apply link ────────────────────────────────

def get_apply_link(job_id: str) -> str | None:
    """
    Fetch the LinkedIn guest API page for this job and extract
    the external apply button URL (company's own careers page / ATS).

    Returns the direct apply URL, or None if not found.
    """
    soup = fetch_page(api_url(job_id))
    if not soup:
        return None

    # Primary: the "Apply" button with an external href
    # LinkedIn renders it as <a class="apply-button" href="https://...">
    for selector in [
        "a.apply-button--link",
        "a[data-tracking-control-name='public_jobs_apply-link-offsite_sign-up-modal']",
        "a[data-tracking-control-name='public_jobs_apply-link-offsite']",
        "a.apply-button",
    ]:
        el = soup.select_one(selector)
        if el and el.get("href", "").startswith("http"):
            href = el["href"]
            # Filter out LinkedIn-internal redirect loops
            if "linkedin.com/jobs" not in href and "linkedin.com/login" not in href:
                return href

    # Fallback: any <a> whose text says "Apply" pointing off-LinkedIn
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        href = a["href"]
        if "apply" in text and href.startswith("http") and "linkedin.com" not in href:
            return href

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
      2. Fetch real apply link for each stub from the job API
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

            apply_link = get_apply_link(stub["job_id"])

            results.append({
                "title":    stub["title"],
                "company":  stub["company"],
                "location": stub["location"],
                # Use the real apply link if found, otherwise fall back to LinkedIn post
                "url": apply_link or stub["linkedin_url"],
                "has_direct_link": apply_link is not None,
            })
            seen_ids.add(stub["job_id"])

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

    Returns up to `limit` unique jobs, deduplicated across all roles.
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

    direct = sum(1 for j in jobs if j.get("has_direct_link"))
    logger.info(f"Scraped {len(jobs)} jobs total | {direct} with direct apply links")

    return jobs