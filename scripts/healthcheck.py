#!/usr/bin/env python3.11
"""
am-blog health check — runs every 4 hours via MiniClaw cron.
Checks all live pages + images load. Self-heals if possible. Alerts if not.
"""
import json, urllib.request, os, sys, base64
from pathlib import Path

SITE = "https://blog.augmentedmike.com"
REPO = "augmentedmike/am-blog"
BASE = "https://api.github.com"
MANIFEST_URL = f"{SITE}/posts-manifest.json"

def get_token():
    return os.popen("gh auth token 2>/dev/null").read().strip()

def http_status(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "am-blog-healthcheck/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except Exception as e:
        return 0

def gh_api(method, path, body=None, token=None):
    token = token or get_token()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        method=method
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def get_live_posts():
    """Fetch manifest, return only posts with date <= today (already published)."""
    from datetime import date
    today = date.today().isoformat()
    try:
        req = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "am-blog-healthcheck/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        posts = data.get("posts", []) if isinstance(data, dict) else data
        return [p for p in posts if isinstance(p, dict) and p.get("date", "9999") <= today]
    except Exception as e:
        return []

def heal_missing_image(slug, filename, token):
    """Try to self-heal a missing image by re-uploading from local build."""
    local_path = Path.home() / f"projects/am-blog/docs/{slug}/{filename}"
    if not local_path.exists():
        return False, f"local file not found: {local_path}"
    try:
        with open(local_path, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        # Get current file SHA if it exists (for update)
        try:
            existing = gh_api("GET", f"/repos/{REPO}/contents/docs/{slug}/{filename}", token=token)
            file_sha = existing.get("sha")
        except Exception:
            file_sha = None

        body = {
            "message": f"fix({slug}): restore missing {filename} (auto-healed)",
            "content": content,
        }
        if file_sha:
            body["sha"] = file_sha

        gh_api("PUT", f"/repos/{REPO}/contents/docs/{slug}/{filename}", body=body, token=token)
        return True, f"re-uploaded {filename}"
    except Exception as e:
        return False, str(e)

def main():
    issues = []
    healed = []
    token = get_token()

    # 1. Check homepage loads
    status = http_status(SITE)
    if status != 200:
        issues.append(f"HOMEPAGE DOWN: {SITE} returned {status}")

    # 2. Get live posts from manifest
    posts = get_live_posts()
    if not posts:
        issues.append("MANIFEST FAILED: could not fetch posts-manifest.json")
    else:
        print(f"Checking {len(posts)} live posts...")
        for post in posts:
            slug = post.get("slug", "")
            if not slug:
                continue

            # Check post page
            page_url = f"{SITE}/{slug}/en/"
            st = http_status(page_url)
            if st != 200:
                issues.append(f"POST PAGE {slug}: HTTP {st}")

            # Check comic image (page_en.jpg preferred, fall back to page.png)
            for img in ["page_en.jpg", "thumb.jpg"]:
                img_url = f"{SITE}/{slug}/{img}"
                st = http_status(img_url)
                if st != 200:
                    # Try to self-heal
                    ok, msg = heal_missing_image(slug, img, token)
                    if ok:
                        healed.append(f"{slug}/{img}: {msg}")
                        print(f"  🔧 Healed: {slug}/{img}")
                    else:
                        issues.append(f"IMAGE BROKEN {slug}/{img}: HTTP {st} — heal failed: {msg}")

    # 3. Check API endpoints
    for endpoint in ["/api/react?slug=test&type=get"]:
        st = http_status(f"{SITE}{endpoint}")
        # react API can return 200 or 404 for non-existent slug — just check it's not 500
        if st >= 500:
            issues.append(f"API ERROR {endpoint}: HTTP {st}")

    # Report
    print("\n--- Health Check Results ---")
    if healed:
        print(f"✅ Self-healed {len(healed)} issue(s):")
        for h in healed:
            print(f"   {h}")
    if issues:
        print(f"❌ {len(issues)} unresolved issue(s):")
        for i in issues:
            print(f"   {i}")
        # Output for MiniClaw to pick up as alert
        sys.exit(1)
    else:
        print(f"✅ All {len(posts)} posts healthy. No issues.")
        sys.exit(0)

if __name__ == "__main__":
    main()
