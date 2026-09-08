#!/usr/bin/env python3
"""
Bigg Boss Season 20 — Automated Scraping Pipeline
-------------------------------------------------
Scrapes moviesdrive -> mdrive archives -> extracts HubCloud & GDFlix IDs
for 480p, 720p, 1080p, and automatically merges new episodes into public/episodes.json.

Usage:
  python3 pipeline_scraper.py              # Scrapes and updates public/episodes.json
  python3 pipeline_scraper.py --dry-run    # Preview changes without modifying file
"""

import sys
import os
import re
import json
import argparse
import urllib.request
import urllib.error
from datetime import datetime

# Default URLs & Config
MAIN_URL = "https://new3.moviesdrive.christmas/bigg-boss-season-20-2026/"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EPISODES_FILE = os.path.join(BASE_DIR, "episodes.json") if os.path.exists(os.path.join(BASE_DIR, "episodes.json")) else os.path.join(BASE_DIR, "public", "episodes.json")
STREAM_API_BASE = "https://steam-api.madmax.dpdns.org"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}

def fetch_url(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")

def extract_quality_archives(main_html):
    """
    Finds the 480p, 720p, and 1080p mdrive archive URLs from the main page.
    """
    qualities = {}
    
    # Method 1: Find link text with quality and href containing mdrive
    link_patterns = [
        r"<a[^>]*href=[\x27\"](https?://mdrive\.[^\x27\"]+)[\x27\"][^>]*>([\s\S]*?)</a>",
        r"<a[^>]*>([\s\S]*?)</a>\s*<a[^>]*href=[\x27\"](https?://mdrive\.[^\x27\"]+)[\x27\"][^>]*>"
    ]
    
    for match in re.finditer(link_patterns[0], main_html, re.IGNORECASE):
        href = match.group(1)
        text = re.sub(r"<[^>]+>", "", match.group(2)).lower()
        if "480p" in text:
            qualities["480p"] = href
        elif "720p" in text:
            qualities["720p"] = href
        elif "1080p" in text:
            qualities["1080p"] = href
            
    # Method 2 fallback: search around h5/p headers if text was outside the <a> tag
    if len(qualities) < 3:
        sections = re.split(r"<hr[^>]*>|<h5[^>]*>", main_html)
        for sec in sections:
            href_m = re.search(r"href=[\x27\"](https?://mdrive\.[^\x27\"]+)[\x27\"]", sec)
            if href_m:
                href = href_m.group(1)
                sec_lower = sec.lower()
                if "480p" in sec_lower and "480p" not in qualities:
                    qualities["480p"] = href
                elif "720p" in sec_lower and "720p" not in qualities:
                    qualities["720p"] = href
                elif "1080p" in sec_lower and "1080p" not in qualities:
                    qualities["1080p"] = href
                    
    return qualities

def scrape_archive(archive_url):
    """
    Scrapes an mdrive archive page and returns episode mapping with HubCloud and GDFlix IDs.
    Returns: { 1: {'hubcloud': id, 'gdflix': id}, 2: {...} }
    """
    html = fetch_url(archive_url)
    episodes = {}
    
    # Split content by Episode headers (e.g., [EP01], Episode 2, EP 03, etc.)
    parts = re.split(r"(\[?EP\s*0?\d+\]?|Episode\s*0?\d+)", html, flags=re.IGNORECASE)
    
    for i in range(1, len(parts), 2):
        ep_label = parts[i]
        ep_num_match = re.search(r"\d+", ep_label)
        if not ep_num_match:
            continue
        ep_num = int(ep_num_match.group(0))
        
        ep_content = parts[i+1] if i+1 < len(parts) else ""
        
        # HubCloud extraction: https://hubcloud.cx/drive/ID or /drive/ID
        hub_m = re.search(r"href=[\x27\"]https?://hubcloud\.[^/]+/drive/([a-zA-Z0-9_-]+)[\x27\"]", ep_content)
        # GDFlix extraction: https://gdflix.dev/file/ID or /file/ID
        gd_m = re.search(r"href=[\x27\"]https?://gdflix\.[^/]+/file/([a-zA-Z0-9_-]+)[\x27\"]", ep_content)
        
        episodes[ep_num] = {
            "hubcloud": hub_m.group(1) if hub_m else None,
            "gdflix": gd_m.group(1) if gd_m else None
        }
        
    return episodes

def get_stream_file_size(provider_type, file_id):
    """
    Optionally queries stream-api to get precise file size (e.g. 1.76 GB)
    """
    if not file_id:
        return ""
    try:
        url = f"{STREAM_API_BASE}/?type={provider_type}&id={file_id}"
        req = urllib.request.Request(url, headers={"Origin": "http://localhost:3000", **HEADERS})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("file"):
                return data["file"].get("size", "")
    except Exception:
        pass
    return ""

def load_existing_episodes():
    if os.path.exists(EPISODES_FILE):
        with open(EPISODES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "show": {
            "title": "Bigg Boss",
            "season": 20,
            "year": "2026",
            "network": "JioHotstar",
            "genre": "Reality, Drama, Game Show",
            "host": "Salman Khan",
            "backdrop": "https://m.media-amazon.com/images/M/MV5BOGJmMzdiNTktNzJmYi00MjMxLTk0YjItNmZkMWVkYmNjNzE1XkEyXkFqcGc@._V1_QL75_UX1000_CR0,52,1000,563_.jpg"
        },
        "episodes": []
    }

def run_pipeline(dry_run=False, check_sizes=True):
    print("==================================================")
    print("  Bigg Boss Season 20 — Pipeline Scraper")
    print("==================================================")
    print(f"[*] Step 1: Fetching main show page: {MAIN_URL}")
    
    try:
        main_html = fetch_url(MAIN_URL)
    except Exception as e:
        print(f"[!] Error fetching main page: {e}")
        return False
        
    archives = extract_quality_archives(main_html)
    print(f"[*] Found {len(archives)} quality archive URLs:")
    for q in ["1080p", "720p", "480p"]:
        print(f"    - {q}: {archives.get(q, 'NOT FOUND')}")
        
    if not archives:
        print("[!] No quality archives found. Exiting.")
        return False
        
    print("\n[*] Step 2: Scraping quality archives...")
    scraped_data = {}  # { ep_num: { "1080p": {...}, "720p": {...}, "480p": {...} } }
    
    for q, arch_url in archives.items():
        print(f"    Scraping {q} from {arch_url}...")
        try:
            ep_dict = scrape_archive(arch_url)
            for ep_num, links in ep_dict.items():
                if ep_num not in scraped_data:
                    scraped_data[ep_num] = {}
                scraped_data[ep_num][q] = links
        except Exception as e:
            print(f"    [!] Error scraping {q}: {e}")
            
    all_ep_nums = sorted(scraped_data.keys(), reverse=True)
    print(f"\n[*] Extracted episodes: {[f'EP {n}' for n in all_ep_nums]}")
    
    # Load existing episodes
    existing_data = load_existing_episodes()
    existing_eps = existing_data.get("episodes", [])
    existing_by_num = {ep.get("episode"): ep for ep in existing_eps if "episode" in ep}
    
    updated_eps = []
    changes_count = 0
    
    print("\n[*] Step 3: Merging with public/episodes.json...")
    for ep_num in all_ep_nums:
        ep_qualities_scraped = scraped_data[ep_num]
        
        # Determine 1080p, 720p, 480p info
        q1080 = ep_qualities_scraped.get("1080p", {})
        q720 = ep_qualities_scraped.get("720p", {})
        q480 = ep_qualities_scraped.get("480p", {})
        
        existing_ep = existing_by_num.get(ep_num)
        
        if existing_ep:
            # Update existing episode's qualities if changed
            ep_obj = existing_ep.copy()
            if "qualities" not in ep_obj:
                ep_obj["qualities"] = {}
                
            for q_name, q_links, default_label in [
                ("1080p", q1080, "1080p FHD"),
                ("720p", q720, "720p HD"),
                ("480p", q480, "480p SD")
            ]:
                if q_links.get("hubcloud") or q_links.get("gdflix"):
                    current_q = ep_obj["qualities"].get(q_name, {})
                    old_hub = current_q.get("HubCloud-stream")
                    old_gd = current_q.get("GDFlix-stream")
                    new_hub = q_links.get("hubcloud") or old_hub
                    new_gd = q_links.get("gdflix") or old_gd
                    
                    if old_hub != new_hub or old_gd != new_gd:
                        changes_count += 1
                        print(f"    [UPDATE] Episode {ep_num} {q_name} IDs updated")
                        
                    size_val = current_q.get("size", "")
                    if check_sizes and not size_val and new_hub:
                        size_val = get_stream_file_size("hubcloud", new_hub)
                        
                    ep_obj["qualities"][q_name] = {
                        "label": current_q.get("label", default_label),
                        "size": size_val,
                        "HubCloud-stream": new_hub,
                        "GDFlix-stream": new_gd
                    }
                    
            # Set default top-level stream to 1080p (fallback 720p -> 480p)
            best_q = ep_obj["qualities"].get("1080p") or ep_obj["qualities"].get("720p") or ep_obj["qualities"].get("480p")
            if best_q:
                ep_obj["HubCloud-stream"] = best_q.get("HubCloud-stream")
                ep_obj["GDFlix-stream"] = best_q.get("GDFlix-stream")
                
            updated_eps.append(ep_obj)
        else:
            # Brand new episode found!
            print(f"    [NEW] Found new Episode {ep_num}!")
            changes_count += 1
            
            # Fetch sizes
            size_1080 = get_stream_file_size("hubcloud", q1080.get("hubcloud")) if check_sizes else ""
            size_720 = get_stream_file_size("hubcloud", q720.get("hubcloud")) if check_sizes else ""
            size_480 = get_stream_file_size("hubcloud", q480.get("hubcloud")) if check_sizes else ""
            
            new_ep = {
                "id": f"bb-s20-e{ep_num:02d}",
                "title": f"Bigg Boss Season 20 Episode {ep_num}",
                "season": 20,
                "episode": ep_num,
                "date": datetime.now().strftime("%d %b %Y"),
                "duration": "1h 30m",
                "description": f"Catch all the uncut drama, nominations, and weekend action of Bigg Boss Season 20 Episode {ep_num}.",
                "thumbnail": existing_data.get("show", {}).get("backdrop", ""),
                "qualities": {
                    "1080p": {
                        "label": "1080p FHD",
                        "size": size_1080,
                        "HubCloud-stream": q1080.get("hubcloud"),
                        "GDFlix-stream": q1080.get("gdflix")
                    },
                    "720p": {
                        "label": "720p HD",
                        "size": size_720,
                        "HubCloud-stream": q720.get("hubcloud"),
                        "GDFlix-stream": q720.get("gdflix")
                    },
                    "480p": {
                        "label": "480p SD",
                        "size": size_480,
                        "HubCloud-stream": q480.get("hubcloud"),
                        "GDFlix-stream": q480.get("gdflix")
                    }
                },
                "HubCloud-stream": q1080.get("hubcloud") or q720.get("hubcloud") or q480.get("hubcloud"),
                "GDFlix-stream": q1080.get("gdflix") or q720.get("gdflix") or q480.get("gdflix")
            }
            updated_eps.append(new_ep)
            
    # Preserve any older episodes that might not be on the first page
    for ep in existing_eps:
        if ep.get("episode") not in [e.get("episode") for e in updated_eps]:
            updated_eps.append(ep)
            
    # Sort episodes descending (latest first)
    updated_eps.sort(key=lambda x: x.get("episode", 0), reverse=True)
    existing_data["episodes"] = updated_eps
    
    if dry_run:
        print("\n" + "=" * 50)
        print("  [!] DRY RUN PREVIEW (No changes written to disk)")
        print("=" * 50)
        print(f"[*] Total episodes in result: {len(updated_eps)}\n")
        for ep in updated_eps:
            q_info = []
            for qk in ["1080p", "720p", "480p"]:
                q_data = ep.get("qualities", {}).get(qk, {})
                hub = q_data.get("HubCloud-stream") or "N/A"
                gd = q_data.get("GDFlix-stream") or "N/A"
                sz = q_data.get("size") or "--"
                q_info.append(f"{qk} ({sz}): Hub={hub}, GD={gd}")
            print(f"▶ Episode {ep.get('episode')}: {ep.get('title')}")
            print(f"  ID: {ep.get('id')} | Date: {ep.get('date')} | Duration: {ep.get('duration')}")
            for qi in q_info:
                print(f"    • {qi}")
            print()

        print("--- FULL JSON OUTPUT ---")
        print(json.dumps(existing_data, indent=2, ensure_ascii=False))
        return True
        
    if changes_count > 0 or not os.path.exists(EPISODES_FILE):
        with open(EPISODES_FILE, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2, ensure_ascii=False)
        print(f"\n[✓] Successfully updated {EPISODES_FILE} with {len(updated_eps)} episodes ({changes_count} changes)!")
        
        # Automatically push to public GitHub feed for instant live reflection
        # push_to_remote_feed handled by git commit in action
    else:
        print(f"\n[✓] No new episodes or ID changes found. {EPISODES_FILE} is already up to date.")
        
    return True

def push_to_remote_feed(episodes_file):
    try:
        import subprocess, base64
        with open(episodes_file, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("utf-8")
        
        # Get existing sha
        get_res = subprocess.run(
            ["gh", "api", "repos/bbrooks870/stream-feed-vault/contents/episodes.json", "--jq", ".sha"],
            capture_output=True, text=True
        )
        sha = get_res.stdout.strip()
        
        payload = {
            "message": "chore: auto-update episodes.json from pipeline",
            "content": content_b64
        }
        if sha:
            payload["sha"] = sha
        
        put_res = subprocess.run(
            ["gh", "api", "--method", "PUT", "repos/bbrooks870/stream-feed-vault/contents/episodes.json", "--input", "-"],
            input=json.dumps(payload), capture_output=True, text=True
        )
        if put_res.returncode == 0:
            print("[✓] Pushed updated episodes to GitHub feed: bbrooks870/stream-feed-vault (LIVE INSTANTLY!)")
            return True
        else:
            print(f"[!] Warning: Could not push to GitHub feed: {put_res.stderr.strip()}")
    except Exception as e:
        print(f"[!] Warning: Push to GitHub feed failed: {e}")
    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bigg Boss Season 20 Scraper Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Preview output without writing to episodes.json")
    parser.add_argument("--no-sizes", action="store_true", help="Skip stream-api file size checks for faster scraping")
    args = parser.parse_args()
    
    success = run_pipeline(dry_run=args.dry_run, check_sizes=not args.no_sizes)
    sys.exit(0 if success else 1)
