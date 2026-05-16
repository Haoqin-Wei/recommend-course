#!/usr/bin/env python3
"""
Scrape UCI Catalogue undergraduate major requirements.

Stage 1 (MVP): for every undergrad B.A./B.S./B.Mus./B.F.A./B.F.A. listed at
https://catalogue.uci.edu/undergraduatedegrees/, fetch the major's page and
extract:

  • all course refs in the Requirements section
  • the raw text of the Requirements section (for audit)

Output: data/uci_general/major_requirements_raw/<slug>.json

Skips minors entirely (scope is full majors only).

Usage:
    pip install requests beautifulsoup4
    python3 scripts/scrape_major_requirements.py
    # Resume support: re-running skips files already written.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag


INDEX_URL = "https://catalogue.uci.edu/undergraduatedegrees/"
BASE_URL = "https://catalogue.uci.edu"
OUT_DIR = Path("data/uci_general/major_requirements_raw")
SLEEP = 0.5            # be polite to the catalogue server
USER_AGENT = "uci-course-advisor-scraper/1.0 (educational demo project)"


# ── HTTP helpers ──────────────────────────────────────────

def fetch(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()
    return resp.text


# ── Index page: list of major links ───────────────────────

# Examples to match:
#   Aerospace Engineering, B.S.
#   Chemistry, B.S.
#   Music, B.A.
#   Music, B.Mus.
#   Dance, B.F.A.
# Skip:
#   Accounting, Minor
#   Asian Studies, Minor
DEGREE_RE = re.compile(r",\s*(B\.S\.|B\.A\.|B\.Mus\.|B\.F\.A\.)\s*$")


def extract_major_links(index_html: str) -> list[tuple[str, str, str]]:
    """
    Walk the alphabetical major list at the top of the index page.
    Return list of (full_label, degree_type, absolute_url).

    Stops at the "organized by focus/interest" section to avoid double-counting.
    """
    soup = BeautifulSoup(index_html, "html.parser")

    out: list[tuple[str, str, str]] = []
    seen_urls: set[str] = set()

    # The first section is alphabetical; the second is by focus area. They
    # contain the same majors. We use the alphabetical section.
    # All major links are <a> in <ul><li> blocks under the heading
    # "UNDERGRADUATE MAJORS AND MINORS (organized alphabetically)".
    # Simplest robust strategy: take EVERY <a> with text matching DEGREE_RE,
    # dedupe by URL.
    for a in soup.find_all("a"):
        if not isinstance(a, Tag):
            continue
        label = a.get_text(strip=True)
        m = DEGREE_RE.search(label)
        if not m:
            continue
        href = a.get("href", "")
        if not href:
            continue
        url = href if href.startswith("http") else BASE_URL + href
        url = url.rstrip("/") + "/"   # normalize trailing slash
        if url in seen_urls:
            continue
        seen_urls.add(url)
        out.append((label, m.group(1), url))

    return out


# ── Major page: requirements section ──────────────────────

# Course refs in the catalogue look like:
#   <a href="https://catalogue.uci.edu/search/?P=I%26C%20SCI%2031" ...>I&C SCI 31</a>
COURSE_REF_RE = re.compile(r"\?P=([^\"&]+)")


def _find_requirements_container(soup: BeautifulSoup) -> Tag | None:
    """
    The Requirements section lives inside <div id="requirementstextcontainer">.
    Some pages use minor variants. Try a couple of fallbacks.
    """
    for sel in (
        {"id": "requirementstextcontainer"},
        {"id": "requirementstext"},
        {"id": "majorrequirementstext"},
    ):
        div = soup.find("div", attrs=sel)
        if div:
            return div
    return None


def extract_requirements(major_html: str) -> dict:
    soup = BeautifulSoup(major_html, "html.parser")

    # Title is in the breadcrumb / h1; school is the second breadcrumb crumb.
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""

    school = ""
    crumb_links = soup.select("ol.breadcrumb a, nav.breadcrumb a, ul.breadcrumbs a")
    for a in crumb_links:
        text = a.get_text(strip=True)
        if "school" in text.lower() or "department" in text.lower():
            school = text
            break

    req_div = _find_requirements_container(soup)
    if req_div is None:
        return {
            "title": title,
            "school": school,
            "requirements_text": "",
            "course_refs": [],
            "warning": "Requirements section not found.",
        }

    # Course refs: walk every <a href="...?P=COURSE">.
    course_refs: list[str] = []
    seen: set[str] = set()
    for a in req_div.find_all("a"):
        href = a.get("href", "") if isinstance(a, Tag) else ""
        m = COURSE_REF_RE.search(href)
        if not m:
            continue
        cid = urllib.parse.unquote(m.group(1))    # "I%26C%20SCI%2031" → "I&C SCI 31"
        if cid in seen:
            continue
        seen.add(cid)
        course_refs.append(cid)

    # Raw text of the requirements section, with rough table structure
    # preserved (rows separated by newlines, cells by " | ").
    lines: list[str] = []
    for row in req_div.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if cells:
            lines.append(" | ".join(cells))
    # Also include non-table paragraphs.
    for p in req_div.find_all(["p", "h2", "h3", "h4", "h5", "li"]):
        text = p.get_text(" ", strip=True)
        if text and len(text) < 500:
            lines.append(text)

    requirements_text = "\n".join(dict.fromkeys(lines))  # preserve order, dedupe

    return {
        "title": title,
        "school": school,
        "requirements_text": requirements_text,
        "course_refs": course_refs,
    }


# ── URL → slug ────────────────────────────────────────────

def url_to_slug(url: str) -> str:
    """https://catalogue.uci.edu/.../computerscience_bs/ → computerscience_bs"""
    parts = [p for p in url.rstrip("/").split("/") if p]
    return parts[-1] if parts else "unknown"


# ── Main ──────────────────────────────────────────────────

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Fetching index from {INDEX_URL} ...")
    index_html = fetch(INDEX_URL)
    majors = extract_major_links(index_html)
    print(f"  found {len(majors)} undergraduate majors\n")

    successes = 0
    failures: list[tuple[str, str]] = []

    for i, (label, degree, url) in enumerate(majors, 1):
        slug = url_to_slug(url)
        out_path = OUT_DIR / f"{slug}.json"
        if out_path.exists():
            print(f"  [{i:3}/{len(majors)}] ⏭  {slug} (already cached)")
            continue

        try:
            page_html = fetch(url)
            data = extract_requirements(page_html)
            data["label"] = label
            data["degree_type"] = degree
            data["url"] = url
            data["slug"] = slug
            out_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            n_refs = len(data.get("course_refs", []))
            warning = "  ⚠ no Requirements section" if data.get("warning") else ""
            print(f"  [{i:3}/{len(majors)}] ✓ {slug:55} ({n_refs:3} courses){warning}")
            successes += 1
        except Exception as e:
            print(f"  [{i:3}/{len(majors)}] ✗ {slug} ({type(e).__name__}: {e})",
                  file=sys.stderr)
            failures.append((slug, str(e)))

        time.sleep(SLEEP)

    print(f"\n✅ Done. {successes} new files in {OUT_DIR}/")
    if failures:
        print(f"❌ {len(failures)} failures:")
        for slug, err in failures:
            print(f"   - {slug}: {err}")


if __name__ == "__main__":
    main()