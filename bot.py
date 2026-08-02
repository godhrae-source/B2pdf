import os
import io
import re
import time
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# 1. IMMEDIATE WEBSERVER START (Prevents Render Web Timeout)
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
import requests
from PIL import Image, ImageEnhance, ImageOps
from pypdf import PdfReader, PdfWriter
import telebot
from telebot import types
import yt_dlp

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

def process_images_to_pdf(image_bytes_list):
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
            quality=85,
            optimize=True
        )
        output_buffer.seek(0)
        return output_buffer
    return None

# --- RELIABLE THREADS EXTRACTION USING YT-DLP ---
def extract_images_from_threads(threads_url):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    img_urls = []
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(threads_url, download=False)
            
            # Check for multiple carousel entries/slides
            if 'entries' in info:
                for entry in info['entries']:
                    if entry.get('url'):
                        img_urls.append(entry['url'])
                    elif entry.get('thumbnails'):
                        img_urls.append(entry['thumbnails'][-1]['url'])
            # Check for direct single post image
            elif info.get('url'):
                img_urls.append(info['url'])
            elif info.get('thumbnails'):
                img_urls.append(info['thumbnails'][-1]['url'])
                
        except Exception as e:
            logging.error(f"yt-dlp extraction error: {e}")

    # Download unique slide bytes
    image_bytes_list = []
    headers = {"User-Agent": "Mozilla/5.0"}
    
    for url in img_urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200 and len(r.content) > 10000:
                image_bytes_list.append(r.content)
        except Exception as err:
            logging.error(f"Download fail: {err}")

    return image_bytes_list

# --- MENU KEYBOARD ---
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("📸 Photos to PDF")
    btn2 = types.KeyboardButton("🧵 Threads to PDF")
    btn3 = types.KeyboardButton("📑 Merge PDFs")
    btn4 = types.KeyboardButton("🔄 Home / Restart")
    markup.add(btn1, btn2, btn3, btn4)
    return markup

@bot.message_handler(commands=['start', 'help'])
@bot.message_handler(func=lambda msg: msg.text in ["🔄 Home / Restart"])
def send_welcome(message):
    reset_user_session(message.chat.id)
    welcome_text = "<b>✨ PDF Converter Bot</b>\n\nPaste a <b>Threads link</b> or select an option below:"
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard())

# --- TEXT & THREADS LINK INPUTS ---
@bot.message_handler(func=lambda msg: True)
def handle_text_inputs(message):
    session = get_user_session(message.chat.id)
    chat_id = message.chat.id
    text = message.text.strip()

    threads_match = re.search(r'https?://(?:www\.)?threads\.(?:net|com)/[^\s]+', text)
    
    if threads_match or session['state'] == 'WAIT_THREADS_LINK':
        url = threads_match.group(0) if threads_match else text
        bot.send_message(chat_id, "🔍 <i>Processing post...</i>")
        try:
            images = extract_images_from_threads(url)
            if not images:
                bot.send_message(chat_id, "❌ Could not extract images. Check if the post is public and contains photos.")
                return

            bot.send_message(chat_id, f"✅ Extracted {len(images)} slide(s)! Generating PDF...")
            pdf_buffer = process_images_to_pdf(images)

            if pdf_buffer:
                bot.send_document(
                    chat_id, 
                    ("threads_carousel.pdf", pdf_buffer.getvalue()), 
                    caption=f"✅ Done! PDF created with {len(images)} page(s)."
                )
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error: {e}")
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
