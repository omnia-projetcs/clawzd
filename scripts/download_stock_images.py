#!/usr/bin/env python3
"""
Download a curated set of open-source stock images for the Presentation Studio.
Images are sourced from LoremFlickr (Creative Commons Flickr photos, free to use).
It fetches metadata (author, link) to provide proper attributions.
Run once: python scripts/download_stock_images.py
"""
import os, json, urllib.request, sys, time

STOCK_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "img", "stock")
CATALOG_PATH = os.path.join(STOCK_DIR, "catalog.json")

CATEGORIES = [
    "business", "technology", "nature", "city", 
    "people", "abstract", "education", "food", "finance"
]

IMAGES_PER_CATEGORY = 50  # 9 categories = 450 images

def download_images():
    os.makedirs(STOCK_DIR, exist_ok=True)
    catalog = []
    
    # Load existing metadata to preserve author attributions
    existing_metadata = {}
    if os.path.exists(CATALOG_PATH):
        try:
            with open(CATALOG_PATH, "r") as f:
                old_data = json.load(f)
                for img in old_data.get("images", []):
                    existing_metadata[img["filename"]] = img
        except Exception:
            pass

    total = len(CATEGORIES) * IMAGES_PER_CATEGORY
    skipped = 0
    downloaded = 0
    current = 0

    print(f"Starting download of {total} images across {len(CATEGORIES)} categories...")

    for category in CATEGORIES:
        for i in range(1, IMAGES_PER_CATEGORY + 1):
            current += 1
            filename = f"{category}_{i}.jpg"
            filepath = os.path.join(STOCK_DIR, filename)
            trash_filepath = os.path.join(STOCK_DIR, "trash", filename)
            url = f"/static/img/stock/{filename}"
            
            # Use lock to ensure we get different images
            json_url = f"https://loremflickr.com/json/1920/1080/{category}?lock={i}"
            
            # If the user moved this image to trash, skip it entirely
            if os.path.exists(trash_filepath):
                skipped += 1
                sys.stdout.write(f"\r[{current}/{total}] 🗑  {filename} (in trash)")
                sys.stdout.flush()
                continue
            
            if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
                skipped += 1
                sys.stdout.write(f"\r[{current}/{total}] ⏭ {filename} (exists)")
                sys.stdout.flush()
                # Preserve existing metadata if available
                if filename in existing_metadata:
                    catalog.append(existing_metadata[filename])
                else:
                    catalog.append({
                        "filename": filename,
                        "url": url,
                        "category": category,
                        "description": f"{category.capitalize()} image",
                        "author_name": "Flickr Contributor",
                        "author_link": "https://flickr.com"
                    })
                continue
                
            try:
                sys.stdout.write(f"\r[{current}/{total}] ⬇ {filename}...")
                sys.stdout.flush()
                
                req = urllib.request.Request(json_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode())
                
                dl_url = data.get("rawFileUrl") or data.get("file")
                author_name = data.get("owner", "Flickr Contributor")
                # rawFileUrl is usually https://live.staticflickr.com/... 
                # For author link we'll use flickr root since we don't have the exact profile URL
                author_link = "https://flickr.com" 
                
                # Download the actual image
                req_img = urllib.request.Request(dl_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req_img, timeout=15) as response, open(filepath, 'wb') as out_file:
                    out_file.write(response.read())
                    
                catalog.append({
                    "filename": filename,
                    "url": url,
                    "category": category,
                    "description": f"{category.capitalize()} image",
                    "author_name": author_name,
                    "author_link": author_link
                })
                    
                downloaded += 1
                time.sleep(0.5)  # be nice to the server
            except Exception as e:
                sys.stdout.write(f"\r[{current}/{total}] ✗ {filename}: {e}\n")
                continue

    # Save catalog
    with open(CATALOG_PATH, "w") as f:
        json.dump({
            "images": catalog,
            "categories": sorted(set(img["category"] for img in catalog)),
            "total": len(catalog)
        }, f, indent=2)

    print(f"\n\n✓ Done! {downloaded} downloaded, {skipped} already existed.")
    print(f"  Catalog: {CATALOG_PATH}")
    print(f"  Images:  {STOCK_DIR}/")

if __name__ == "__main__":
    download_images()
