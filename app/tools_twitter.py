"""
Clawzd — Twitter/X Watch & Research tool.
Provides search, user timeline, trending topics, and a persisted watchlist.
Uses existing Twitter OAuth credentials (tweepy) when available,
Bearer Token as secondary, and Nitter/DDG scraping as final fallback.
"""
import os
import json
import uuid
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

from config import (
    DATA_DIR,
    TWITTER_API_KEY, TWITTER_API_SECRET,
    TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET,
    TWITTER_BEARER_TOKEN,
)

router = APIRouter()
logger = logging.getLogger("clawzd.twitter")

WATCHLIST_PATH = os.path.join(DATA_DIR, "twitter_watchlist.json")
TWITTER_CACHE_DIR = os.path.join(DATA_DIR, "twitter_cache")
os.makedirs(TWITTER_CACHE_DIR, exist_ok=True)

# Nitter instances to try (public, no auth required)
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.woodland.cafe",
    "https://nitter.1d4.us",
]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _has_twitter_creds() -> bool:
    """Check if we have any form of Twitter API credentials."""
    return bool(TWITTER_BEARER_TOKEN) or all([
        TWITTER_API_KEY, TWITTER_API_SECRET,
        TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET
    ])


def _get_tweepy_client():
    """Build a tweepy.Client using available credentials (same pattern as integrations_social.py)."""
    try:
        import tweepy
    except ImportError:
        return None
    kwargs = {}
    # Bearer token for read-only access (app-level)
    if TWITTER_BEARER_TOKEN:
        kwargs["bearer_token"] = TWITTER_BEARER_TOKEN
    # OAuth user credentials (read + write)
    if all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
        kwargs["consumer_key"] = TWITTER_API_KEY
        kwargs["consumer_secret"] = TWITTER_API_SECRET
        kwargs["access_token"] = TWITTER_ACCESS_TOKEN
        kwargs["access_token_secret"] = TWITTER_ACCESS_SECRET
    if not kwargs:
        return None
    return tweepy.Client(**kwargs, wait_on_rate_limit=False)


# ---------------------------------------------------------------------------
# Twitter API v2 via tweepy (uses existing OAuth or Bearer Token)
# ---------------------------------------------------------------------------

def _tweet_to_dict(tweet, user=None) -> dict:
    """Convert a tweepy Tweet object to our standard dict format."""
    metrics = tweet.public_metrics or {} if hasattr(tweet, 'public_metrics') else {}
    username = getattr(user, 'username', '') if user else ''
    name = getattr(user, 'name', username) if user else ''
    avatar = getattr(user, 'profile_image_url', '') if user else ''
    return {
        "id": str(tweet.id),
        "text": tweet.text or "",
        "created_at": tweet.created_at.isoformat() if hasattr(tweet, 'created_at') and tweet.created_at else "",
        "author_name": name,
        "author_username": username,
        "author_avatar": avatar,
        "likes": metrics.get("like_count", 0),
        "retweets": metrics.get("retweet_count", 0),
        "replies": metrics.get("reply_count", 0),
        "url": f"https://x.com/{username}/status/{tweet.id}" if username else "",
        "source": "api",
    }


async def _twitter_api_search(query: str, max_results: int = 20) -> list[dict]:
    """Search tweets using Twitter API v2 via tweepy."""
    client = _get_tweepy_client()
    if not client:
        return []
    try:
        def _search():
            resp = client.search_recent_tweets(
                query=query,
                max_results=min(max(max_results, 10), 100),
                tweet_fields=["created_at", "public_metrics", "author_id"],
                user_fields=["name", "username", "profile_image_url"],
                expansions=["author_id"],
            )
            tweets = resp.data or []
            users = {}
            if resp.includes and "users" in resp.includes:
                for u in resp.includes["users"]:
                    users[u.id] = u
            return [_tweet_to_dict(t, users.get(t.author_id)) for t in tweets]

        return await asyncio.get_running_loop().run_in_executor(None, _search)
    except Exception as e:
        logger.error("Twitter API search failed: %s", e)
        return []


async def _twitter_api_user_tweets(username: str, max_results: int = 10) -> list[dict]:
    """Get recent tweets from a user via Twitter API v2 (tweepy)."""
    client = _get_tweepy_client()
    if not client:
        return []
    try:
        def _fetch():
            # Step 1: Resolve username → user object
            user_resp = client.get_user(
                username=username,
                user_fields=["name", "username", "profile_image_url", "public_metrics"],
            )
            if not user_resp.data:
                return []
            user = user_resp.data
            # Step 2: Get timeline
            tweets_resp = client.get_users_tweets(
                id=user.id,
                max_results=min(max(max_results, 5), 100),
                tweet_fields=["created_at", "public_metrics"],
            )
            return [_tweet_to_dict(t, user) for t in (tweets_resp.data or [])]

        return await asyncio.get_running_loop().run_in_executor(None, _fetch)
    except Exception as e:
        logger.error("Twitter API user tweets failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Nitter scraping fallback (no auth required)
# ---------------------------------------------------------------------------

async def _nitter_request(path: str) -> Optional[str]:
    """Try Nitter instances until one responds, return HTML or None."""
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        for instance in NITTER_INSTANCES:
            try:
                url = f"{instance}{path}"
                resp = await client.get(url, headers=_HEADERS)
                if resp.status_code == 200 and len(resp.text) > 500:
                    return resp.text
            except Exception:
                continue
    return None


def _parse_nitter_tweets(html: str) -> list[dict]:
    """Extract tweet data from Nitter HTML."""
    tweets = []
    # Find timeline items
    items = re.findall(
        r'<div class="timeline-item[^"]*">(.*?)</div>\s*</div>\s*</div>',
        html, re.DOTALL
    )
    if not items:
        # Alternative pattern
        items = re.findall(
            r'<div class="timeline-item[^"]*?">(.*?)<div class="timeline-item',
            html + '<div class="timeline-item', re.DOTALL
        )

    for item in items[:30]:
        # Username
        username_m = re.search(r'<a class="username"[^>]*>@?([^<]+)</a>', item)
        username = username_m.group(1).strip() if username_m else ""
        # Display name
        name_m = re.search(r'<a class="fullname"[^>]*>([^<]+)</a>', item)
        name = name_m.group(1).strip() if name_m else username
        # Tweet text
        text_m = re.search(r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>', item, re.DOTALL)
        text = ""
        if text_m:
            text = re.sub(r'<[^>]+>', '', text_m.group(1)).strip()
        # Date
        date_m = re.search(r'<span class="tweet-date"><a[^>]*title="([^"]*)"', item)
        date_str = date_m.group(1).strip() if date_m else ""
        # Stats
        likes_m = re.search(r'<span class="icon-heart[^"]*"></span>\s*(\d[\d,]*)', item)
        likes = int(likes_m.group(1).replace(",", "")) if likes_m else 0
        rt_m = re.search(r'<span class="icon-retweet[^"]*"></span>\s*(\d[\d,]*)', item)
        retweets = int(rt_m.group(1).replace(",", "")) if rt_m else 0
        replies_m = re.search(r'<span class="icon-comment[^"]*"></span>\s*(\d[\d,]*)', item)
        replies = int(replies_m.group(1).replace(",", "")) if replies_m else 0
        # Tweet link
        link_m = re.search(r'<a class="tweet-link"[^>]*href="([^"]*)"', item)
        tweet_path = link_m.group(1).strip() if link_m else ""
        tweet_url = f"https://x.com{tweet_path}" if tweet_path else ""
        # Tweet ID from path
        tid_m = re.search(r'/status/(\d+)', tweet_path)
        tid = tid_m.group(1) if tid_m else ""

        if text:
            tweets.append({
                "id": tid,
                "text": text[:500],
                "created_at": date_str,
                "author_name": name,
                "author_username": username,
                "author_avatar": "",
                "likes": likes,
                "retweets": retweets,
                "replies": replies,
                "url": tweet_url,
                "source": "nitter",
            })
    return tweets


async def _nitter_search(query: str, max_results: int = 20) -> list[dict]:
    """Search tweets via Nitter scraping."""
    from urllib.parse import quote_plus
    html = await _nitter_request(f"/search?f=tweets&q={quote_plus(query)}")
    if not html:
        return []
    return _parse_nitter_tweets(html)[:max_results]


async def _nitter_user_tweets(username: str, max_results: int = 10) -> list[dict]:
    """Get recent tweets from a user via Nitter scraping."""
    html = await _nitter_request(f"/{username}")
    if not html:
        return []
    return _parse_nitter_tweets(html)[:max_results]


async def _nitter_trending() -> list[dict]:
    """Get trending topics from Nitter (limited availability)."""
    # Most Nitter instances don't expose trending; use DuckDuckGo as fallback
    trends = []
    try:
        from app.tools_web import _do_search
        results = await asyncio.to_thread(_do_search, "trending Twitter topics today", 10)
        for i, r in enumerate(results):
            trends.append({
                "rank": i + 1,
                "name": r.get("title", "")[:80],
                "url": r.get("url", ""),
                "tweet_count": "",
            })
    except Exception as e:
        logger.error("Trending fallback failed: %s", e)
    return trends


# ---------------------------------------------------------------------------
# Unified search functions (API → Nitter fallback)
# ---------------------------------------------------------------------------

async def search_tweets(query: str, max_results: int = 20) -> list[dict]:
    """Search tweets using the best available method."""
    # Try Twitter API first (uses OAuth creds or Bearer Token)
    if _has_twitter_creds():
        results = await _twitter_api_search(query, max_results)
        if results:
            return results
    # Fallback to Nitter
    results = await _nitter_search(query, max_results)
    if results:
        return results
    # Last resort: DuckDuckGo search for tweets
    try:
        from app.tools_web import _do_search
        ddg = await asyncio.to_thread(
            _do_search, f"site:twitter.com OR site:x.com {query}", min(max_results, 10)
        )
        return [{
            "id": "",
            "text": r.get("snippet", "")[:500],
            "created_at": "",
            "author_name": "",
            "author_username": "",
            "author_avatar": "",
            "likes": 0,
            "retweets": 0,
            "replies": 0,
            "url": r.get("url", ""),
            "source": "ddg",
        } for r in ddg]
    except Exception:
        return []


async def get_user_tweets(username: str, max_results: int = 10) -> list[dict]:
    """Get recent tweets from a user."""
    username = username.lstrip("@").strip()
    if _has_twitter_creds():
        results = await _twitter_api_user_tweets(username, max_results)
        if results:
            return results
    return await _nitter_user_tweets(username, max_results)


async def get_trending() -> list[dict]:
    """Get trending topics."""
    return await _nitter_trending()


# ---------------------------------------------------------------------------
# Watchlist persistence
# ---------------------------------------------------------------------------

def _load_watchlist() -> list[dict]:
    if os.path.exists(WATCHLIST_PATH):
        try:
            with open(WATCHLIST_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_watchlist(items: list[dict]):
    os.makedirs(os.path.dirname(WATCHLIST_PATH), exist_ok=True)
    with open(WATCHLIST_PATH, "w") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@router.get("/search")
async def api_search(q: str, max_results: int = 20):
    """Search tweets by keyword."""
    if not q.strip():
        raise HTTPException(400, "Query is required")
    tweets = await search_tweets(q.strip(), max_results)
    return {"query": q, "count": len(tweets), "tweets": tweets}


@router.get("/user/{username}")
async def api_user_tweets(username: str, max_results: int = 10):
    """Get recent tweets from a user."""
    username = username.lstrip("@").strip()
    if not username:
        raise HTTPException(400, "Username is required")
    tweets = await get_user_tweets(username, max_results)
    return {"username": username, "count": len(tweets), "tweets": tweets}


@router.get("/trending")
async def api_trending():
    """Get trending topics."""
    trends = await get_trending()
    return {"trends": trends}


@router.get("/watchlist")
async def api_get_watchlist():
    """Return saved watchlist entries."""
    return {"watchlist": _load_watchlist()}


@router.post("/watchlist")
async def api_add_watchlist(request: Request):
    """Add a watchlist entry (keyword, user, linkedin_profile, linkedin_article)."""
    data = await request.json()
    entry_type = data.get("type", "keyword")
    value = data.get("value", "").strip()
    platform = data.get("platform", "twitter")  # "twitter" or "linkedin"
    if not value:
        raise HTTPException(400, "Value is required")

    items = _load_watchlist()
    entry = {
        "id": uuid.uuid4().hex[:8],
        "type": entry_type,
        "value": value,
        "platform": platform,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    items.append(entry)
    _save_watchlist(items)
    return {"status": "added", "entry": entry}


@router.delete("/watchlist/{entry_id}")
async def api_delete_watchlist(entry_id: str):
    """Delete a watchlist entry."""
    items = _load_watchlist()
    items = [i for i in items if i.get("id") != entry_id]
    _save_watchlist(items)
    return {"status": "deleted"}


@router.post("/watchlist/refresh")
async def api_refresh_watchlist():
    """Refresh all watchlist entries and return latest results."""
    items = _load_watchlist()
    results = {}
    for item in items:
        platform = item.get("platform", "twitter")
        if platform == "linkedin":
            if item["type"] == "article":
                res = await search_linkedin_articles(item["value"], 5)
            else:
                res = await search_linkedin_profiles(item["value"], 5)
            results[item["id"]] = res
        else:
            if item["type"] == "keyword":
                results[item["id"]] = await search_tweets(item["value"], 5)
            else:
                results[item["id"]] = await get_user_tweets(item["value"], 5)
    return {"results": results}


# ===========================================================================
# LinkedIn Search (profiles, articles) — via DuckDuckGo + og:image extraction
# ===========================================================================

async def _fetch_og_image(url: str) -> str:
    """Try to fetch the og:image meta tag from a URL (for LinkedIn profile photos)."""
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(url, headers=_HEADERS)
            if resp.status_code != 200:
                return ""
            html = resp.text[:20000]  # Only first 20KB
            m = re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', html)
            if not m:
                m = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', html)
            return m.group(1) if m else ""
    except Exception:
        return ""


async def search_linkedin_profiles(query: str, max_results: int = 10) -> list[dict]:
    """Search LinkedIn profiles (CV/people) via DuckDuckGo site:linkedin.com/in/."""
    try:
        from app.tools_web import _do_search
        ddg = await asyncio.to_thread(
            _do_search, f"site:linkedin.com/in/ {query}", min(max_results, 15)
        )
        results = []
        # Fetch og:image for each profile (parallel, with limit)
        async def _enrich(r):
            url = r.get("url", "")
            title = r.get("title", "")
            snippet = r.get("snippet", r.get("body", ""))
            # Extract name from title: "Firstname Lastname - Title | LinkedIn"
            name = title.split(" - ")[0].split(" | ")[0].strip() if title else ""
            headline = title.split(" - ")[1].split(" | ")[0].strip() if " - " in title else ""
            photo = await _fetch_og_image(url) if url else ""
            return {
                "id": url,
                "type": "profile",
                "name": name,
                "headline": headline,
                "photo": photo,
                "url": url,
                "snippet": snippet[:300],
                "source": "linkedin",
            }

        tasks = [_enrich(r) for r in ddg[:max_results]]
        results = await asyncio.gather(*tasks)
        return list(results)
    except Exception as e:
        logger.error("LinkedIn profile search failed: %s", e)
        return []


async def search_linkedin_articles(query: str, max_results: int = 10) -> list[dict]:
    """Search LinkedIn articles/posts via DuckDuckGo site:linkedin.com/pulse/."""
    try:
        from app.tools_web import _do_search
        ddg = await asyncio.to_thread(
            _do_search, f"site:linkedin.com/pulse/ OR site:linkedin.com/posts/ {query}", min(max_results, 15)
        )
        results = []
        for r in ddg[:max_results]:
            url = r.get("url", "")
            title = r.get("title", "")
            snippet = r.get("snippet", r.get("body", ""))
            # Extract author if in title format "Article Title | Author"
            parts = title.rsplit(" | ", 1)
            article_title = parts[0].strip()
            author = parts[1].strip() if len(parts) > 1 and parts[1].strip() != "LinkedIn" else ""
            results.append({
                "id": url,
                "type": "article",
                "title": article_title,
                "author": author,
                "url": url,
                "snippet": snippet[:300],
                "source": "linkedin",
            })
        return results
    except Exception as e:
        logger.error("LinkedIn article search failed: %s", e)
        return []


# --- LinkedIn API routes ---

@router.get("/linkedin/profiles")
async def api_linkedin_profiles(q: str, max_results: int = 10):
    """Search LinkedIn profiles by keyword."""
    if not q.strip():
        raise HTTPException(400, "Query is required")
    results = await search_linkedin_profiles(q.strip(), max_results)
    return {"query": q, "count": len(results), "results": results}


@router.get("/linkedin/articles")
async def api_linkedin_articles(q: str, max_results: int = 10):
    """Search LinkedIn articles by keyword."""
    if not q.strip():
        raise HTTPException(400, "Query is required")
    results = await search_linkedin_articles(q.strip(), max_results)
    return {"query": q, "count": len(results), "results": results}
