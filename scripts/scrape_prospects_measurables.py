#!/usr/bin/env python3
"""
Scrape Mockdraftable.com for 2026 NFL Combine / Pro Day measurables.
Output: imports/prospects_measurables.json
  [{ "name", "position", "school", "height", "weight",
     "forty_combine", "forty_proday", "bench", "vertical",
     "broad", "three_cone", "shuttle" }, ...]
"""
import requests
from bs4 import BeautifulSoup
import json, time, re, os, sys

BASE = "https://www.mockdraftable.com"
SEARCH_URL = f"{BASE}/search?pos=&year=2026"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

def clean_float(s):
    try:
        return float(re.sub(r'[^\d.]', '', s))
    except Exception:
        return None

def clean_int(s):
    try:
        return int(re.sub(r'[^\d]', '', s))
    except Exception:
        return None

def main():
    out_dir = os.path.join(os.path.dirname(__file__), '..', 'imports')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'prospects_measurables.json')

    print(f"Fetching prospect list: {SEARCH_URL}")
    r = requests.get(SEARCH_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')

    # Mockdraftable lists prospects — find links to individual prospect pages
    prospect_links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/player/' in href or '/prospect/' in href:
            full = href if href.startswith('http') else BASE + href
            name = a.get_text(strip=True)
            if name and full not in [p['url'] for p in prospect_links]:
                prospect_links.append({'name': name, 'url': full})

    # Also try table rows
    for row in soup.select('table tbody tr'):
        cells = row.find_all('td')
        if cells:
            link = row.find('a', href=True)
            if link and ('/player/' in link['href'] or '/prospect/' in link['href']):
                full = link['href'] if link['href'].startswith('http') else BASE + link['href']
                name = link.get_text(strip=True)
                if name and full not in [p['url'] for p in prospect_links]:
                    prospect_links.append({'name': name, 'url': full})

    if not prospect_links:
        print("WARNING: Could not find prospect links. Saving debug HTML.")
        with open(os.path.join(out_dir, 'measurables_debug.html'), 'w') as f:
            f.write(r.text)
        print("Check imports/measurables_debug.html and adjust selectors.")
        sys.exit(1)

    print(f"Found {len(prospect_links)} prospect links. Fetching individual pages...")
    prospects = []

    for i, p in enumerate(prospect_links):
        print(f"  [{i+1}/{len(prospect_links)}] {p['name']}")
        try:
            pr = requests.get(p['url'], headers=HEADERS, timeout=15)
            pr.raise_for_status()
            ps = BeautifulSoup(pr.text, 'html.parser')

            data = {'name': p['name']}

            # Extract position, school from header/meta
            for label_tag in ps.find_all(['span', 'div', 'p']):
                txt = label_tag.get_text(strip=True)
                if not data.get('position') and re.match(r'^(QB|RB|WR|TE|OT|OG|C|DE|DT|LB|CB|S|K|P|LS|FB|EDGE|OL|DL|DB)$', txt):
                    data['position'] = txt
                if not data.get('school') and len(txt) > 5 and 'University' in txt or 'State' in txt or 'College' in txt:
                    data['school'] = txt[:50]

            # Extract measurables from stat table
            stat_map = {
                '40': ('forty_combine', clean_float),
                '40-yard': ('forty_combine', clean_float),
                'bench': ('bench', clean_int),
                'vertical': ('vertical', clean_float),
                'broad': ('broad', clean_int),
                '3-cone': ('three_cone', clean_float),
                'cone': ('three_cone', clean_float),
                'shuttle': ('shuttle', clean_float),
                'height': ('height', lambda x: x),
                'weight': ('weight', clean_int),
            }

            for row_el in ps.find_all('tr'):
                cells = row_el.find_all(['td', 'th'])
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True).lower()
                    val = cells[1].get_text(strip=True)
                    for key, (field, fn) in stat_map.items():
                        if key in label and field not in data:
                            result = fn(val)
                            if result:
                                data[field] = result

            prospects.append(data)
        except Exception as e:
            print(f"    ERROR: {e}")
        time.sleep(0.4)

    with open(out_path, 'w') as f:
        json.dump(prospects, f, indent=2)
    print(f"\n✅ {len(prospects)} prospects saved to {out_path}")

if __name__ == '__main__':
    main()
