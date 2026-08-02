import json
import re
import requests
import logging

def extract_images_from_threads(threads_url):
    # Extract shortcode/post code
    match = re.search(r'/(?:post|t)/([A-Za-z0-9_-]+)', threads_url)
    if not match:
        return []
    
    code = match.group(1)
    img_urls = []

    # METHOD 1: Direct GraphQL Endpoint (Bypasses regular HTML scraping)
    try:
        gql_url = f"https://www.threads.net/api/graphql"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "X-IG-App-ID": "238260118697367",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        # Standard Threads Post Query ID
        payload = {
            "lsd": "AVqBsD8v",
            "variables": json.dumps({"postID": code}),
            "doc_id": "5578654128849925"
        }
        res = requests.post(gql_url, data=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            # Navigate nested GraphQL data
            edges = data.get('data', {}).get('data', {}).get('edges', [])
            for edge in edges:
                node = edge.get('node', {}).get('thread_items', [{}])[0].get('post', {})
                carousel = node.get('carousel_media')
                if carousel:
                    for item in carousel:
                        candidates = item.get('image_versions2', {}).get('candidates', [])
                        if candidates:
                            img_urls.append(candidates[0]['url'])
                else:
                    candidates = node.get('image_versions2', {}).get('candidates', [])
                    if candidates:
                        img_urls.append(candidates[0]['url'])
    except Exception as e:
        logging.error(f"GraphQL method failed: {e}")

    # METHOD 2: Direct Embed/JSON Scrape if GraphQL was blocked
    if not img_urls:
        try:
            embed_url = f"https://www.threads.net/t/{code}/embed"
            headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15"}
            res = requests.get(embed_url, headers=headers, timeout=8)
            if res.status_code == 200:
                # Find all high-res image links in embed markup
                found_urls = re.findall(r'https://scontent[^\s"\'<]+', res.text)
                for u in found_urls:
                    clean_u = u.replace('\\u0026', '&').replace('\\/', '/')
                    if 's150x150' not in clean_u and 's320x320' not in clean_u: # Filter out profile icons
                        if clean_u not in img_urls:
                            img_urls.append(clean_u)
        except Exception as e:
            logging.error(f"Embed method failed: {e}")

    # Download image bytes
    image_bytes_list = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in img_urls:
        try:
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 200 and len(r.content) > 15000:
                image_bytes_list.append(r.content)
        except Exception as err:
            logging.error(f"Download fail: {err}")

    return image_bytes_list
