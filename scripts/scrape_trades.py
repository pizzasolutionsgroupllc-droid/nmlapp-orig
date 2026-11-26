#!/usr/bin/env python3
"""
NML Trade Forum Scraper
Reads trade threads from nationalmaddenleague.com and exports to JSON.

Usage:
    python3 scripts/scrape_trades.py

Output:
    imports/nml_trade_history.json
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import sys
import os

BASE_URL = "https://www.nationalmaddenleague.com/forums/"

FORUMS = [
    {"name": "2026-27 Pre-Draft Trades", "f": 116, "pages": 4},
    {"name": "2025-26 Regular Season Trades", "f": 111, "pages": 5},
]

# phpBB shows 25 topics per page by default
TOPICS_PER_PAGE = 25

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch(session, url, retries=3):
    for attempt in range(retries):
        try:
            r = session.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return r.text
        except Exception as e:
            if attempt == retries - 1:
                print(f"  ERROR fetching {url}: {e}")
                return None
            time.sleep(2)


def get_thread_links(session, forum_id, num_pages):
    """Get all thread topic URLs from a forum."""
    links = []
    for page in range(num_pages):
        start = page * TOPICS_PER_PAGE
        url = f"{BASE_URL}viewforum.php?f={forum_id}&start={start}"
        print(f"  Fetching forum page {page+1}/{num_pages}: {url}")
        html = fetch(session, url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        # phpBB topic links are in <a> tags with class "topictitle"
        for a in soup.find_all("a", class_="topictitle"):
            href = a.get("href", "")
            title = a.get_text(strip=True)
            # Convert relative to absolute
            if href.startswith("./"):
                href = BASE_URL + href[2:]
            elif not href.startswith("http"):
                href = BASE_URL + href
            # Strip session ID from URL for cleanliness
            if "sid=" in href:
                href = href.split("&sid=")[0].split("?sid=")[0]
            if "viewtopic.php" in href and href not in [l["url"] for l in links]:
                links.append({"title": title, "url": href})
        time.sleep(0.5)
    return links


def get_thread_content(session, url, title):
    """Fetch a thread and extract the first post content."""
    html = fetch(session, url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")

    # phpBB post content is in div.content or div[class*="post-body"]
    posts = []
    for post_div in soup.find_all("div", class_="post"):
        # Get poster name
        author_tag = post_div.find("span", class_="username") or post_div.find("a", class_="username")
        author = author_tag.get_text(strip=True) if author_tag else "Unknown"

        # Get post date
        post_time = ""
        time_tag = post_div.find("p", class_="author") or post_div.find("time")
        if time_tag:
            post_time = time_tag.get_text(strip=True)

        # Get post body text
        content_div = post_div.find("div", class_="content")
        if content_div:
            # Remove any quote blocks to get just the original post
            for quote in content_div.find_all("blockquote"):
                quote.decompose()
            text = content_div.get_text(separator="\n", strip=True)
            posts.append({
                "author": author,
                "time": post_time,
                "text": text
            })

    if not posts:
        # Fallback: try alternative phpBB markup
        for div in soup.find_all("div", {"class": lambda c: c and "postbody" in c}):
            text = div.get_text(separator="\n", strip=True)
            if text:
                posts.append({"author": "", "time": "", "text": text})

    return {
        "title": title,
        "url": url,
        "posts": posts[:3]  # First 3 posts (usually commissioner approval in post 2)
    }


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "imports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "nml_trade_history.json")

    session = requests.Session()

    # Test connectivity first
    print("Testing forum access...")
    test = fetch(session, f"{BASE_URL}viewforum.php?f=111")
    if not test:
        print("\nERROR: Cannot reach the forum. Make sure you're connected to the internet.")
        sys.exit(1)
    print("Forum accessible ✓\n")

    all_trades = []

    for forum in FORUMS:
        print(f"\n{'='*60}")
        print(f"Forum: {forum['name']}")
        print(f"{'='*60}")

        links = get_thread_links(session, forum["f"], forum["pages"])
        print(f"Found {len(links)} threads\n")

        for i, link in enumerate(links):
            print(f"  [{i+1}/{len(links)}] {link['title']}")
            thread = get_thread_content(session, link["url"], link["title"])
            if thread:
                thread["forum"] = forum["name"]
                all_trades.append(thread)
            time.sleep(0.5)  # Be polite

    # Save output
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_trades, f, indent=2, ensure_ascii=False)

    print(f"\n\n{'='*60}")
    print(f"Done! {len(all_trades)} threads saved to:")
    print(f"  {out_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
