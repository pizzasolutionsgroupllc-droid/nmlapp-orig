#!/usr/bin/env python3
"""
Scrape RAS scores for 2026 NFL Draft prospects from ras.football
Uses the WordPress REST API to pull all posts published in 2026,
then parses each post for player name, position, school, and RAS score.

Output: imports/prospects_ras.json
  [{ "name", "position", "school", "ras" }, ...]

Usage:
    python3 scripts/scrape_prospects_ras.py
"""
import requests
from bs4 import BeautifulSoup
import json, re, os, sys, time, unicodedata

BASE = "https://ras.football"
API  = f"{BASE}/wp-json/wp/v2/posts"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

def clean_name(raw):
    """Strip ' RAS' suffix and normalize."""
    name = re.sub(r'\s+RAS\s*$', '', raw, flags=re.I).strip()
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    return name

def parse_post(post):
    """Extract name, position, school, ras from a WP REST post object."""
    title_raw = post.get('title', {}).get('rendered', '')
    name = clean_name(BeautifulSoup(title_raw, 'html.parser').get_text())

    # Skip non-player posts
    if not re.search(r'\bRAS\b', title_raw, re.I):
        return None

    content_html = post.get('content', {}).get('rendered', '')
    soup = BeautifulSoup(content_html, 'html.parser')
    text = soup.get_text(' ', strip=True)

    # ── RAS score ──────────────────────────────────────────────────────
    ras = None
    # Pattern: "RAS of 9.57" or "RAS Score: 9.57" or just a score in a table cell
    m = re.search(r'RAS(?:\s+(?:score|of|:))?\s*[:\-]?\s*(\d+\.?\d*)', text, re.I)
    if m:
        val = float(m.group(1))
        if 0 <= val <= 10.1:
            ras = round(val, 2)

    # Fallback: scan all decimal numbers 0-10 near "RAS"
    if ras is None:
        for m2 in re.finditer(r'(\d+\.\d+)', text):
            val = float(m2.group(1))
            if 0 < val <= 10.0:
                ras = round(val, 2)
                break

    # ── Position ───────────────────────────────────────────────────────
    position = ''
    pos_match = re.search(
        r'\b(QB|RB|FB|WR|TE|OT|OG|OC|IOL|OL|DE|DT|NT|EDGE|LB|ILB|OLB|MLB|CB|S|SS|FS|DB|K|P|LS|ATH)\b',
        text
    )
    if pos_match:
        position = pos_match.group(1)

    # ── School ─────────────────────────────────────────────────────────
    school = ''
    # Look for "from <School>" or "at <School>" or "out of <School>"
    school_m = re.search(r'(?:from|out of|at)\s+([A-Z][A-Za-z &\(\)]+?)(?:\s+for|\s+in|\s*\.|\s*,|\s*\n)', text)
    if school_m:
        school = school_m.group(1).strip()

    if not name or ras is None:
        return None

    return {'name': name, 'position': position, 'school': school, 'ras': ras}


def fetch_all_posts():
    """Pull all WP posts published Jan 1, 2026 – present via REST API (paginated)."""
    posts = []
    page = 1
    while True:
        params = {
            'after':    '2026-01-01T00:00:00',
            'before':   '2027-01-01T00:00:00',
            'per_page': 100,
            'page':     page,
            'orderby':  'date',
            'order':    'asc',
            '_fields':  'id,title,content,link',
        }
        try:
            r = requests.get(API, headers=HEADERS, params=params, timeout=30)
            if r.status_code == 400:
                print(f"  Page {page}: 400 (no more pages)")
                break
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            print(f"  Page {page}: {len(batch)} posts")
            posts.extend(batch)
            if len(batch) < 100:
                break
            page += 1
            time.sleep(0.5)
        except Exception as e:
            print(f"  ERROR on page {page}: {e}")
            break
    return posts


def main():
    out_dir = os.path.join(os.path.dirname(__file__), '..', 'imports')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'prospects_ras.json')

    print("Fetching 2026 posts from ras.football WordPress API...")
    posts = fetch_all_posts()
    print(f"Total posts fetched: {len(posts)}")

    prospects = []
    skipped = 0
    for post in posts:
        result = parse_post(post)
        if result:
            prospects.append(result)
        else:
            skipped += 1

    print(f"\nParsed: {len(prospects)} prospects, skipped {skipped} non-player posts")

    if not prospects:
        print("ERROR: No RAS data found. The site structure may have changed.")
        sys.exit(1)

    # Sort by name for readability
    prospects.sort(key=lambda x: x['name'])

    with open(out_path, 'w') as f:
        json.dump(prospects, f, indent=2)
    print(f"✅ Saved to {out_path}")
    print(f"\nSample (first 5):")
    for p in prospects[:5]:
        print(f"  {p}")

if __name__ == '__main__':
    main()
