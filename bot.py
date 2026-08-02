import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# 1. IMMEDIATE WEBSERVER START (Prevents Port Scan Timeout)
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), DummyServer)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# 2. IMPORTS
import io
import re
import time
import json
import logging
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageEnhance, ImageOps
from pypdf import PdfReader, PdfWriter
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEFAULT_BOT_TOKEN = "8888660501:AAGvIRYpwoQDn6B3JhLNyzNQg2lvoGtDBHc"
BOT_TOKEN = os.environ.get("BOT_TOKEN", DEFAULT_BOT_TOKEN)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

user_data = {}

A4_WIDTH = 1240
A4_HEIGHT = 1754

def get_user_session(chat_id):
    if chat_id not in user_data:
        user_data[chat_id] = {
            "state": None,
            "images": [],
            "pdfs": [],
            "layout_mode": "1_per_page",
            "active_pdf_bytes": None,
            "active_pdf_name": "document.pdf"
        }
    return user_data[chat_id]

def reset_user_session(chat_id):
    if chat_id in user_data:
        user_data[chat_id] = {
            "state": None,
            "images": [],
            "pdfs": [],
            "layout_mode": "1_per_page",
            "active_pdf_bytes": None,
            "active_pdf_name": "document.pdf"
        }

def process_images_to_pdf(image_bytes_list, layout_mode="1_per_page"):
    pdf_pages = []
    
    for b in image_bytes_list:
        try:
            img = Image.open(io.BytesIO(b))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            img.thumbnail((A4_WIDTH, A4_HEIGHT), Image.Resampling.LANCZOS)
            filled_img = ImageOps.fit(img, (A4_WIDTH, A4_HEIGHT), Image.Resampling.LANCZOS)
            pdf_pages.append(filled_img)
        except Exception as e:
            logging.error(f"Error processing image: {e}")

    output_buffer = io.BytesIO()
    if pdf_pages:
        pdf_pages[0].save(
            output_buffer,
            format="PDF",
            save_all=True,
            append_images=pdf_pages[1:],
            resolution=100.0,
            quality=75,
            optimize=True
        )
        output_buffer.seek(0)
        return output_buffer
    return None

# --- BULLETPROOF THREADS SCRAPER ---
def extract_images_from_threads(threads_url):
    # Standardize Threads URL
    threads_url = threads_url.split('?')[0] # Remove tracking query parameters
    if not threads_url.endswith('/'):
        threads_url += '/'

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document"
    }
    
    img_urls = []

    try:
        # Method 1: Direct Page HTML & JSON Data Parsing
        response = requests.get(threads_url, headers=headers, timeout=12)
        if response.status_code == 200:
            html_content = response.text
            
            # Search Meta tags
            soup = BeautifulSoup(html_content, 'html.parser')
            for tag in soup.find_all('meta', property=['og:image', 'twitter:image']):
                content = tag.get('content')
                if content and 'scontent' in content and content not in img_urls:
                    img_urls.append(content)

            # Search raw JSON embedded in script tags
            script_matches = re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', html_content, re.DOTALL)
            for script in script_matches:
                if 'image_versions2' in script or 'candidates' in script:
                    raw_links = re.findall(r'https://scontent[^\s"\'\\]+', script)
                    for link in raw_links:
                        clean = link.replace('\\/', '/').replace('\\u0026', '&')
                        if clean not in img_urls and not any(p in clean for p in ['_s.jpg', 'p150x150', '50x50']):
                            img_urls.append(clean)

        # Method 2: OEmbed Fallback if Method 1 missed carousel images
        if not img_urls:
            oembed_url = f"https://www.threads.net/oembed?url={threads_url}"
            o_resp = requests.get(oembed_url, headers=headers, timeout=8)
            if o_resp.status_code == 200:
                data = o_resp.json()
                if 'thumbnail_url' in data:
                    img_urls.append(data['thumbnail_url'])

        # Limit to unique high-res URLs
        clean_urls = []
        for u in img_urls:
            u_clean = u.replace('\\/', '/').replace('\\u0026', '&')
            if u_clean not in clean_urls:
                clean_urls.append(u_clean)

        clean_urls = clean_urls[:20] # Cap to max 20 images to protect RAM
        logging.info(f"Extracted {len(clean_urls)} clean image URLs.")

        # Download image bytes
        image_bytes_list = []
        for url in clean_urls:
            try:
                res = requests.get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=10)
                if res.status_code == 200 and len(res.content) > 10000:
                    image_bytes_list.append(res.content)
            except Exception as err:
                logging.error(f"Image download error: {err}")

        return image_bytes_list

    except Exception as e:
        logging.error(f"Threads extraction failed: {e}")
        return []

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("📸 Photos to PDF")
    btn2 = types.KeyboardButton("🧵 Threads to PDF")
    btn3 = types.KeyboardButton("🔄 Home / Restart")
    markup.add(btn1, btn2, btn3)
    return markup

@bot.message_handler(commands=['start', 'help'])
@bot.message_handler(func=lambda msg: msg.text in ["🔄 Home / Restart"])
def send_welcome(message):
    reset_user_session(message.chat.id)
    bot.send_message(
        message.chat.id,
        "✨ <b>Welcome! Send a Threads link or photo to start:</b>",
        reply_markup=get_main_keyboard()
    )

@bot.message_handler(func=lambda msg: msg.text == "🧵 Threads to PDF")
def threads_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'WAIT_THREADS_LINK'
    bot.send_message(message.chat.id, "🧵 Paste any Threads post URL below:")

@bot.message_handler(func=lambda msg: True)
def handle_text_inputs(message):
    session = get_user_session(message.chat.id)
    chat_id = message.chat.id
    text = message.text.strip()

    threads_match = re.search(r'https?://(?:www\.)?threads\.(?:net|com)/[^\s]+', text)
    
    if threads_match or session['state'] == 'WAIT_THREADS_LINK':
        url = threads_match.group(0) if threads_match else text
        bot.send_message(chat_id, "🔍 <i>Extracting images from Threads...</i>")
        try:
            images = extract_images_from_threads(url)
            if not images:
                bot.send_message(
                    chat_id, 
                    "❌ <b>Could not find images in this post.</b>\n\n"
                    "• The post might be a text-only post or video.\n"
                    "• The post might be from a private account."
                )
                return

            bot.send_message(chat_id, f"✅ Found {len(images)} image(s)! Building PDF...")
            pdf_buffer = process_images_to_pdf(images)

            if pdf_buffer:
                bot.send_document(chat_id, ("threads_post.pdf", pdf_buffer.getvalue()), caption="✅ Threads PDF Ready!")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Failed: {e}")
        finally:
            reset_user_session(chat_id)

if __name__ == "__main__":
    logging.info("Bot started...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
        except Exception as err:
            logging.error(f"Polling error: {err}")
            time.sleep(3)
