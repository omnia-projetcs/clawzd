"""
Clawzd — Document Generation (Business Card & CV) via AI.
Generates professional business cards and CVs as HTML→PNG images.
Supports LinkedIn profile scraping for CV auto-population with SEO keywords.
"""
import os
import re
import uuid
import json
import logging
import base64
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from config import DATA_DIR

logger = logging.getLogger("clawzd.docgen")
router = APIRouter()

IMAGES_DIR = os.path.join(DATA_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# LinkedIn Profile Scraper
# ---------------------------------------------------------------------------

async def _scrape_linkedin_profile(url: str) -> dict:
    """Scrape a public LinkedIn profile page."""
    import re
    import httpx

    profile = {
        "name": "", "headline": "", "summary": "",
        "photo_url": "", "location": "", "url": url,
        "experience": [], "education": [], "skills": [],
    }

    username_match = re.search(r'linkedin\.com/in/([^/]+)', url)
    if not username_match:
        return profile
    
    username = username_match.group(1).strip()
    if username.endswith('/'): username = username[:-1]
    
    query = f"site:linkedin.com/in/{username}"
    
    try:
        def _sync_ddgs():
            from ddgs import DDGS
            res = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=3):
                    res.append(r)
            return res

        import asyncio
        results = await asyncio.to_thread(_sync_ddgs)
        
        if results:
            first = results[0]
            for r in results:
                if username.lower() in r.get("href", "").lower():
                    first = r
                    break
                    
            title = first.get("title", "")
            body = first.get("body", "")
            
            parts = title.split(" - ")
            if parts:
                profile["name"] = parts[0].replace(" | LinkedIn", "").strip()
            if len(parts) > 1:
                profile["headline"] = parts[1].replace(" | LinkedIn", "").strip()
                
            profile["summary"] = body.strip()
            return profile
    except ImportError:
        logger.warning("ddgs not installed, falling back to httpx")
    except Exception as e:
        logger.error("LinkedIn scrape error via DDG: %s", e)

    # Fallback to direct httpx scrape
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                html = resp.text[:50000]
                m = re.search(r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', html)
                if not m: m = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']', html)
                if m:
                    raw = m.group(1).strip()
                    parts = raw.split(" - ", 1)
                    profile["name"] = parts[0].strip().replace(" | LinkedIn", "")
                    if len(parts) > 1: profile["headline"] = parts[1].replace(" | LinkedIn", "").strip()

                m = re.search(r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']', html)
                if not m: m = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:description["\']', html)
                if m: profile["summary"] = m.group(1).strip()

                m = re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', html)
                if not m: m = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', html)
                if m:
                    photo = m.group(1).strip()
                    if photo and "static.licdn.com" not in photo.lower(): profile["photo_url"] = photo

                m = re.search(r'<meta[^>]*name=["\']geo\.placename["\'][^>]*content=["\']([^"\']+)["\']', html)
                if m: profile["location"] = m.group(1).strip()
    except Exception as e:
        logger.error("LinkedIn scrape fallback error: %s", e)

    return profile


async def _enrich_profile_with_llm(profile: dict, target_role: str = "") -> dict:
    """Use LLM to generate SEO keywords and skills from profile data."""
    import httpx
    from config import OLLAMA_HOST, OLLAMA_MODEL

    context = json.dumps({k: v for k, v in profile.items() if k != "photo_url"}, ensure_ascii=False)

    system = (
        "You are an HR/SEO expert. Given a LinkedIn profile, extract and generate:\n"
        "1. A list of 10-15 SEO keywords for ATS matching (job-relevant skills, technologies, certifications)\n"
        "2. A list of 5-10 professional skills\n"
        "3. A polished professional summary (2-3 sentences)\n"
        "4. Suggested experience entries if inferable from the headline/summary\n"
        f"{'Target role: ' + target_role if target_role else ''}\n"
        "Return ONLY valid JSON: {\"seo_keywords\":[...], \"skills\":[...], \"summary\":\"...\", \"experience\":[{\"title\":\"...\",\"company\":\"...\",\"period\":\"...\"}]}\n"
        "No markdown fences, no explanation."
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": context,
        "system": system,
        "stream": False,
        "options": {"temperature": 0.5, "num_predict": 1024},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{OLLAMA_HOST}/api/generate", json=payload)
            resp.raise_for_status()
            raw = resp.json().get("response", "")

        raw = re.sub(r"<think>.*?(?:</think>|$)", "", raw, flags=re.DOTALL).strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(raw[start:end + 1])
            profile["seo_keywords"] = data.get("seo_keywords", [])
            profile["skills"] = data.get("skills", profile.get("skills", []))
            if data.get("summary"):
                profile["enriched_summary"] = data["summary"]
            if data.get("experience") and not profile.get("experience"):
                profile["experience"] = data["experience"]
    except Exception as e:
        logger.warning("LLM enrichment failed: %s", e)
        profile["seo_keywords"] = []

    return profile


# ---------------------------------------------------------------------------
# Business Card Layout Generator
# ---------------------------------------------------------------------------

_CARD_STYLES = {
    "modern": {
        "bg": "linear-gradient(135deg, #0f0c29, #302b63, #24243e)",
        "accent": "#6c63ff", "text": "#ffffff", "text2": "#b8b8d4",
    },
    "minimalist": {
        "bg": "#ffffff",
        "accent": "#1a1a2e", "text": "#1a1a2e", "text2": "#555555",
    },
    "corporate": {
        "bg": "linear-gradient(135deg, #0a1628, #1a2744)",
        "accent": "#0ea5e9", "text": "#ffffff", "text2": "#94a3b8",
    },
    "creative": {
        "bg": "linear-gradient(135deg, #ff6b6b, #ffa36c)",
        "accent": "#ffffff", "text": "#ffffff", "text2": "#ffffff",
    },
    "luxury": {
        "bg": "linear-gradient(135deg, #1a1a1a, #2d2d2d)",
        "accent": "#d4af37", "text": "#f5f5f5", "text2": "#aaaaaa",
    },
}

def _generate_business_card_presentation(data: dict, style_key: str = "modern") -> dict:
    s = _CARD_STYLES.get(style_key, _CARD_STYLES["modern"])
    name = data.get("name", "John Doe")
    title = data.get("title", "")
    company = data.get("company", "")
    email = data.get("email", "")
    phone = data.get("phone", "")
    website = data.get("website", "")
    
    bg_color = s["bg"]
    if "linear-gradient" in bg_color:
        m = re.search(r'#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})', bg_color)
        bg_color = m.group(0) if m else "#ffffff"

    elements = []
    def add_el(el):
        el["id"] = f"el_{uuid.uuid4().hex[:8]}"
        elements.append(el)

    add_el({"type": "shape", "shapeType": "rect", "x": 0, "y": 0, "width": 638, "height": 368, "backgroundColor": bg_color, "borderWidth": 0})
    add_el({"type": "shape", "shapeType": "rect", "x": 0, "y": 0, "width": 8, "height": 368, "backgroundColor": s["accent"], "borderWidth": 0})
    
    add_el({"type": "text", "x": 40, "y": 80, "width": 500, "height": 40, "content": name, "color": s["text"], "fontSize": 32, "fontWeight": "bold", "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
    
    cur_y = 130
    if title:
        add_el({"type": "text", "x": 40, "y": cur_y, "width": 500, "height": 20, "content": title, "color": s["accent"], "fontSize": 14, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
        cur_y += 25
    if company:
        add_el({"type": "text", "x": 40, "y": cur_y, "width": 500, "height": 20, "content": company, "color": s["text2"], "fontSize": 14, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
        cur_y += 35
    else:
        cur_y += 20
        
    add_el({"type": "shape", "shapeType": "rect", "x": 40, "y": cur_y, "width": 40, "height": 2, "backgroundColor": s["accent"], "borderWidth": 0})
    cur_y += 20

    if email:
        add_el({"type": "text", "x": 40, "y": cur_y, "width": 500, "height": 20, "content": f"✉ {email}", "color": s["text2"], "fontSize": 12, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
        cur_y += 22
    if phone:
        add_el({"type": "text", "x": 40, "y": cur_y, "width": 500, "height": 20, "content": f"☎ {phone}", "color": s["text2"], "fontSize": 12, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
        cur_y += 22
    if website:
        add_el({"type": "text", "x": 40, "y": cur_y, "width": 500, "height": 20, "content": f"⊕ {website}", "color": s["text2"], "fontSize": 12, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})

    return {
        "pages": [{"elements": elements}],
        "canvas_width": 638,
        "canvas_height": 368
    }

# ---------------------------------------------------------------------------
# CV Layout Generator
# ---------------------------------------------------------------------------

_CV_STYLES = {
    "professional": {"accent": "#1e40af", "bg": "#ffffff", "sidebar": "#f0f4ff", "text": "#1e293b"},
    "modern": {"accent": "#7c3aed", "bg": "#ffffff", "sidebar": "#faf5ff", "text": "#1e293b"},
    "creative": {"accent": "#ea580c", "bg": "#fffbeb", "sidebar": "#fff7ed", "text": "#1c1917"},
    "ats_optimized": {"accent": "#1e293b", "bg": "#ffffff", "sidebar": "#f8fafc", "text": "#1e293b"},
}

def _generate_cv_presentation(data: dict, style_key: str = "professional") -> dict:
    s = _CV_STYLES.get(style_key, _CV_STYLES["professional"])
    name = data.get("name", "First Last")
    title = data.get("title", data.get("headline", ""))
    summary = data.get("enriched_summary", data.get("summary", ""))
    email = data.get("email", "")
    phone = data.get("phone", "")
    location = data.get("location", "")
    website = data.get("website", "")
    photo_url = data.get("photo_url", "")
    skills = data.get("skills", [])
    seo_keywords = data.get("seo_keywords", [])
    experience = data.get("experience", [])
    education = data.get("education", [])

    elements = []
    def add_el(el):
        el["id"] = f"el_{uuid.uuid4().hex[:8]}"
        elements.append(el)

    add_el({"type": "shape", "shapeType": "rect", "x": 0, "y": 0, "width": 794, "height": 1123, "backgroundColor": s["bg"], "borderWidth": 0})
    
    sidebar_w = 260
    add_el({"type": "shape", "shapeType": "rect", "x": 0, "y": 0, "width": sidebar_w, "height": 1123, "backgroundColor": s["sidebar"], "borderWidth": 0})
    add_el({"type": "shape", "shapeType": "rect", "x": sidebar_w - 3, "y": 0, "width": 3, "height": 1123, "backgroundColor": s["accent"], "borderWidth": 0})

    left_x = 24
    right_x = sidebar_w + 32
    
    cur_y_left = 40
    # Always add a photo placeholder if no photo (1x1 gray pixel base64 to avoid SSL/network errors)
    placeholder_b64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    actual_photo_url = photo_url if photo_url else placeholder_b64
    add_el({"type": "image", "src": actual_photo_url, "x": (sidebar_w - 120)//2, "y": cur_y_left, "width": 120, "height": 120, "opacity": 100})
    cur_y_left += 140

    add_el({"type": "text", "x": left_x, "y": cur_y_left, "width": sidebar_w - 48, "height": 30, "content": name, "color": s["accent"], "fontSize": 24, "fontWeight": "bold", "textAlign": "center", "backgroundColor": "transparent", "borderWidth": 0})
    cur_y_left += 35
    if title:
        add_el({"type": "text", "x": left_x, "y": cur_y_left, "width": sidebar_w - 48, "height": 20, "content": title, "color": s["accent"], "fontSize": 12, "textAlign": "center", "backgroundColor": "transparent", "borderWidth": 0})
        cur_y_left += 40
    else:
        cur_y_left += 20
        
    def add_section_title(x, y, text, width):
        add_el({"type": "text", "x": x, "y": y, "width": width, "height": 20, "content": text.upper(), "color": s["accent"], "fontSize": 12, "fontWeight": "bold", "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
        add_el({"type": "shape", "shapeType": "rect", "x": x, "y": y + 22, "width": width, "height": 2, "backgroundColor": s["accent"], "borderWidth": 0})
        return y + 35

    cur_y_left = add_section_title(left_x, cur_y_left, "Contact", sidebar_w - 48)
    for c_info, prefix in [(email, "✉"), (phone, "☎"), (location, "📍"), (website, "🌐")]:
        if c_info:
            add_el({"type": "text", "x": left_x, "y": cur_y_left, "width": sidebar_w - 48, "height": 20, "content": f"{prefix} {c_info}", "color": s["text"], "fontSize": 11, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
            cur_y_left += 25
    cur_y_left += 20
    
    if skills:
        cur_y_left = add_section_title(left_x, cur_y_left, "Skills", sidebar_w - 48)
        skills_str = ", ".join(skills)
        add_el({"type": "text", "x": left_x, "y": cur_y_left, "width": sidebar_w - 48, "height": 100, "content": skills_str, "color": s["text"], "fontSize": 11, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
        cur_y_left += 100
        
    if seo_keywords:
        cur_y_left = add_section_title(left_x, cur_y_left, "SEO Keywords", sidebar_w - 48)
        seo_str = ", ".join(seo_keywords[:15])
        add_el({"type": "text", "x": left_x, "y": cur_y_left, "width": sidebar_w - 48, "height": 100, "content": seo_str, "color": "#166534", "fontSize": 10, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})

    cur_y_main = 40
    main_w = 794 - right_x - 32
    actual_summary = summary if summary else "Your professional summary will go here. Click to modify this text and add a compelling description of your goals and profile."
    cur_y_main = add_section_title(right_x, cur_y_main, "Profile", main_w)
    add_el({"type": "text", "x": right_x, "y": cur_y_main, "width": main_w, "height": 80, "content": actual_summary, "color": s["text"], "fontSize": 12, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
    cur_y_main += 90

    actual_experience = experience if experience else [
        {"title": "Your Current Position", "company": "Company Name", "period": "2020 - Present", "description": "Description of your missions and achievements."},
        {"title": "Previous Position", "company": "Previous Company", "period": "2015 - 2020", "description": "Description of your missions and achievements."}
    ]
    cur_y_main = add_section_title(right_x, cur_y_main, "Experience", main_w)
    for exp in actual_experience[:5]:
        if isinstance(exp, str):
            add_el({"type": "text", "x": right_x, "y": cur_y_main, "width": main_w, "height": 20, "content": exp, "color": s["text"], "fontSize": 12, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
            cur_y_main += 25
            continue
            
        title_text = exp.get('title', '')
        add_el({"type": "text", "x": right_x, "y": cur_y_main, "width": main_w, "height": 20, "content": title_text, "color": s["text"], "fontSize": 13, "fontWeight": "bold", "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
        cur_y_main += 20
        company_text = exp.get('company', '')
        period = exp.get('period', '')
        comp_str = f"{company_text} · {period}" if period else company_text
        add_el({"type": "text", "x": right_x, "y": cur_y_main, "width": main_w, "height": 15, "content": comp_str, "color": s["accent"], "fontSize": 11, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
        cur_y_main += 20
        desc = exp.get('description', '')
        if desc:
            add_el({"type": "text", "x": right_x, "y": cur_y_main, "width": main_w, "height": 40, "content": desc, "color": s["text"], "fontSize": 11, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
            cur_y_main += 45
        else:
            cur_y_main += 10
    cur_y_main += 10

    actual_education = education if education else [
        {"degree": "Your Degree / Education", "school": "Name of school or university", "year": "2015"}
    ]
    cur_y_main = add_section_title(right_x, cur_y_main, "Education", main_w)
    for edu in actual_education[:3]:
        if isinstance(edu, str):
            add_el({"type": "text", "x": right_x, "y": cur_y_main, "width": main_w, "height": 20, "content": edu, "color": s["text"], "fontSize": 11, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
            cur_y_main += 25
        elif isinstance(edu, dict):
            degree = edu.get('degree', edu.get('title', ''))
            add_el({"type": "text", "x": right_x, "y": cur_y_main, "width": main_w, "height": 20, "content": degree, "color": s["text"], "fontSize": 12, "fontWeight": "bold", "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
            cur_y_main += 20
            school = edu.get('school', edu.get('institution', ''))
            year = edu.get('year', edu.get('period', ''))
            sc_str = f"{school} · {year}" if year else school
            add_el({"type": "text", "x": right_x, "y": cur_y_main, "width": main_w, "height": 15, "content": sc_str, "color": s["accent"], "fontSize": 11, "textAlign": "left", "backgroundColor": "transparent", "borderWidth": 0})
            cur_y_main += 25

    return {
        "pages": [{"elements": elements}],
        "canvas_width": 794,
        "canvas_height": 1123
    }


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.post("/scrape-linkedin")
async def api_scrape_linkedin(request: Request):
    """Scrape a LinkedIn profile and enrich with SEO keywords."""
    data = await request.json()
    url = data.get("url", "").strip()
    target_role = data.get("target_role", "")

    if not url:
        raise HTTPException(400, "LinkedIn URL is required")
    if "linkedin.com" not in url.lower():
        raise HTTPException(400, "Please provide a valid LinkedIn URL")

    profile = await _scrape_linkedin_profile(url)
    profile = await _enrich_profile_with_llm(profile, target_role)

    return {"status": "ok", "profile": profile}


@router.post("/generate-business-card")
async def api_generate_business_card(request: Request):
    """Generate a business card as PNG image."""
    data = await request.json()
    style = data.get("style", "modern")
    card_data = {
        "name": data.get("name", ""),
        "title": data.get("title", ""),
        "company": data.get("company", ""),
        "email": data.get("email", ""),
        "phone": data.get("phone", ""),
        "website": data.get("website", ""),
    }

    if not card_data["name"]:
        raise HTTPException(400, "Name is required")

    presentation_data = _generate_business_card_presentation(card_data, style)

    logger.info("Business card generated as Presentation")
    return {"status": "ok", "presentation": presentation_data}


@router.post("/generate-cv")
async def api_generate_cv(request: Request):
    """Generate a CV/resume as PNG image, optionally from LinkedIn profile."""
    data = await request.json()
    style = data.get("style", "professional")
    linkedin_url = data.get("linkedin_url", "").strip()
    target_role = data.get("target_role", "")

    cv_data = {
        "name": data.get("name", ""),
        "title": data.get("title", ""),
        "summary": data.get("summary", ""),
        "email": data.get("email", ""),
        "phone": data.get("phone", ""),
        "location": data.get("location", ""),
        "website": data.get("website", ""),
        "photo_url": data.get("photo_url", ""),
        "skills": data.get("skills", []),
        "seo_keywords": data.get("seo_keywords", []),
        "experience": data.get("experience", []),
        "education": data.get("education", []),
    }

    # If LinkedIn URL provided, scrape and merge
    if linkedin_url:
        profile = await _scrape_linkedin_profile(linkedin_url)
        profile = await _enrich_profile_with_llm(profile, target_role)

        # Merge: LinkedIn data fills in blanks
        for key in ["name", "headline", "summary", "location", "photo_url"]:
            if not cv_data.get(key) and profile.get(key):
                target_key = "title" if key == "headline" else key
                cv_data[target_key] = profile[key]
        if not cv_data.get("skills") and profile.get("skills"):
            cv_data["skills"] = profile["skills"]
        if not cv_data.get("seo_keywords") and profile.get("seo_keywords"):
            cv_data["seo_keywords"] = profile["seo_keywords"]
        if not cv_data.get("experience") and profile.get("experience"):
            cv_data["experience"] = profile["experience"]
        if profile.get("enriched_summary") and not data.get("summary"):
            cv_data["enriched_summary"] = profile["enriched_summary"]

    if not cv_data.get("name"):
        raise HTTPException(400, "Name is required (provide it or use a LinkedIn URL)")

    if cv_data.get("photo_url") and not cv_data["photo_url"].startswith("data:"):
        data_uri = await _download_photo_as_data_uri(cv_data["photo_url"])
        if data_uri:
            cv_data["photo_url"] = data_uri

    presentation_data = _generate_cv_presentation(cv_data, style)

    logger.info("CV generated as Presentation")
    return {
        "status": "ok",
        "presentation": presentation_data,
        "seo_keywords": cv_data.get("seo_keywords", []),
    }
