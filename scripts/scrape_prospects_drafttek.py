#!/usr/bin/env python3
"""
Scrape DraftTek 2026 Big Board rankings.
Output: imports/prospects_drafttek.json
  [{ "name", "position", "school", "drafttek_rank" }, ...]
"""
import requests
from bs4 import BeautifulSoup
import json, re, os, sys, time

BASE_URL = "https://www.drafttek.com/2026-NFL-Draft-Big-Board/Top-NFL-Draft-Prospects-2026-Page-{page}.asp"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
MAX_PAGES = 12  # ~25 per page = 300 prospects

def main():
    out_dir = os.path.join(os.path.dirname(__file__), '..', 'imports')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'prospects_drafttek.json')

    prospects = []
    seen_ranks = set()

    for page in range(1, MAX_PAGES + 1):
        url = BASE_URL.format(page=page)
        print(f"Page {page}: {url}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 404:
                print(f"  Page {page} not found, stopping.")
                break
            r.raise_for_status()
        except Exception as e:
            print(f"  ERROR: {e}")
            break

        soup = BeautifulSoup(r.text, 'html.parser')
        page_prospects = []

        # DraftTek uses tables with prospect rows
        for row in soup.select('table tr'):
            cells = row.find_all(['td', 'th'])
            if len(cells) < 3:
                continue
            text = [c.get_text(strip=True) for c in cells]

            # First cell is rank
            try:
                rank = int(re.sub(r'[^\d]', '', text[0]))
            except (ValueError, IndexError):
                continue

            if rank in seen_ranks:
                continue
            seen_ranks.add(rank)

            name = text[1] if len(text) > 1 else ''
            position = text[2] if len(text) > 2 else ''
            school = text[3] if len(text) > 3 else ''

            # Clean up position (sometimes includes grade info)
            position = re.sub(r'\s+\d+.*$', '', position).strip()

            if name and rank:
                page_prospects.append({
                    'drafttek_rank': rank,
                    'name': name,
                    'position': position,
                    'school': school,
                })

        if not page_prospects:
            print(f"  No prospects found on page {page}, stopping.")
            break

        prospects.extend(page_prospects)
        print(f"  Found {len(page_prospects)} prospects (total: {len(prospects)})")
        time.sleep(0.6)

    if not prospects:
        print("ERROR: No prospects found. Check site structure.")
        sys.exit(1)

    with open(out_path, 'w') as f:
        json.dump(prospects, f, indent=2)
    print(f"\n✅ {len(prospects)} DraftTek prospects saved to {out_path}")

if __name__ == '__main__':
    main()
