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

# 2. HEAVY IMPORTS (Loaded after server starts)
import io
import re
import time
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

def enhance_newspaper_image(pil_img):
    gray = pil_img.convert('L')
    enhancer = ImageEnhance.Contrast(gray)
    contrasted = enhancer.enhance(1.8)
    sharp_enhancer = ImageEnhance.Sharpness(contrasted)
    sharpened = sharp_enhancer.enhance(2.0)
    return sharpened.convert('RGB')

def create_a4_canvas():
    return Image.new('RGB', (A4_WIDTH, A4_HEIGHT), (255, 255, 255))

# RAM-OPTIMIZED PDF PROCESSOR
def process_images_to_pdf(image_bytes_list, layout_mode="1_per_page"):
    pdf_pages = []
    
    for b in image_bytes_list:
        try:
            img = Image.open(io.BytesIO(b))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Downscale large image resolution to prevent status 137 memory limits
            img.thumbnail((A4_WIDTH, A4_HEIGHT), Image.Resampling.LANCZOS)

            if layout_mode == "newspaper":
                enhanced = enhance_newspaper_image(img)
                filled_img = ImageOps.fit(enhanced, (A4_WIDTH, A4_HEIGHT), Image.Resampling.LANCZOS)
                pdf_pages.append(filled_img)
            else:
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

def extract_images_from_threads(threads_url):
    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    try:
        response = requests.get(threads_url, headers=headers, timeout=12)
        if response.status_code != 200:
            return []

        html_content = response.text
        img_urls = []

        raw_urls = re.findall(r'https://scontent[^\s"\'\\]+', html_content)
        if not raw_urls:
            raw_urls = re.findall(r'https://[^\s"\'\\]*fbcdn[^\s"\'\\]+', html_content)

        for u in raw_urls:
            clean_url = u.replace('\\/', '/').replace('\\u0026', '&')
            if any(x in clean_url for x in ['_s.jpg', '_a.jpg', 'p150x150', 'p50x50', '150x150', '50x50']):
                continue
            if clean_url not in img_urls:
                img_urls.append(clean_url)

        if not img_urls:
            soup = BeautifulSoup(html_content, 'html.parser')
            for tag in soup.find_all('meta', property='og:image'):
                content = tag.get('content')
                if content and content not in img_urls:
                    img_urls.append(content)

        # Cap max downloaded photos to 30 to prevent 512MB RAM overflow
        img_urls = img_urls[:30]

        image_bytes_list = []
        dl_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }

        for img_url in img_urls:
            try:
                img_resp = requests.get(img_url, headers=dl_headers, timeout=10)
                if img_resp.status_code == 200 and len(img_resp.content) > 15000:
                    image_bytes_list.append(img_resp.content)
            except Exception as err:
                logging.error(f"Error downloading image: {err}")

        return image_bytes_list

    except Exception as e:
        logging.error(f"Threads extraction exception: {e}")
        return []

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("📸 Photos to PDF")
    btn2 = types.KeyboardButton("📰 Newspaper HD Scanner")
    btn3 = types.KeyboardButton("🧵 Threads to PDF")
    btn4 = types.KeyboardButton("📑 Merge PDFs")
    btn5 = types.KeyboardButton("✂️ Delete PDF Pages")
    btn6 = types.KeyboardButton("🗜️ Compress PDF")
    btn7 = types.KeyboardButton("🔒 Protect / Unlock PDF")
    btn8 = types.KeyboardButton("📝 Extract Text")
    btn9 = types.KeyboardButton("🔄 Home / Restart")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8, btn9)
    return markup

@bot.message_handler(commands=['start', 'help'])
@bot.message_handler(func=lambda msg: msg.text in ["🔄 Home / Restart", "🔄 Reset / Clear Session"])
def send_welcome(message):
    reset_user_session(message.chat.id)
    welcome_text = (
        "<b>✨ Welcome to your PDF Organizer Bot!</b>\n\n"
        "Select an option below, send a file, or paste a <b>Threads post link</b> to start:"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "📸 Photos to PDF")
def photos_to_pdf_start(message):
    session = get_user_session(message.chat.id)
    reset_user_session(message.chat.id)
    session['state'] = 'COLLECTING_IMAGES'
    bot.send_message(message.chat.id, "📸 Send me your photos now!")

@bot.message_handler(func=lambda msg: msg.text == "🧵 Threads to PDF")
def threads_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'WAIT_THREADS_LINK'
    bot.send_message(message.chat.id, "🧵 Paste any Threads post URL below:")

@bot.message_handler(content_types=['photo'])
def receive_image(message):
    session = get_user_session(message.chat.id)
    session['state'] = 'COLLECTING_IMAGES'
    try:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        session['images'].append(downloaded_file)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"⚙️ Generate PDF ({len(session['images'])} Photos)", callback_data="build_image_pdf"))
        bot.reply_to(message, f"✅ Photo #{len(session['images'])} received!", reply_markup=markup)
    except Exception as e:
        logging.error(f"Error: {e}")

@bot.message_handler(func=lambda msg: True)
def handle_text_inputs(message):
    session = get_user_session(message.chat.id)
    chat_id = message.chat.id
    text = message.text.strip()

    threads_match = re.search(r'https?://(?:www\.)?threads\.(?:net|com)/[^\s]+', text)
    
    if threads_match or session['state'] == 'WAIT_THREADS_LINK':
        url = threads_match.group(0) if threads_match else text
        bot.send_message(chat_id, "🔍 <i>Fetching photos from post...</i>")
        try:
            images = extract_images_from_threads(url)
            if not images:
                bot.send_message(chat_id, "❌ Could not find images in that post.")
                return

            bot.send_message(chat_id, f"✅ Found {len(images)} images! Generating PDF...")
            pdf_buffer = process_images_to_pdf(images, layout_mode="1_per_page")

            if pdf_buffer:
                bot.send_document(chat_id, ("threads_post.pdf", pdf_buffer.getvalue()), caption="✅ PDF Ready!")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Failed: {e}")
        finally:
            reset_user_session(chat_id)

@bot.callback_query_handler(func=lambda call: call.data == "build_image_pdf")
def handle_callbacks(call):
    session = get_user_session(call.message.chat.id)
    chat_id = call.message.chat.id

    if session['images']:
        bot.send_message(chat_id, "⏳ Building PDF...")
        pdf_buffer = process_images_to_pdf(session['images'])
        if pdf_buffer:
            bot.send_document(chat_id, ("document.pdf", pdf_buffer.getvalue()), caption="✅ Here is your PDF!")
        reset_user_session(chat_id)

if __name__ == "__main__":
    logging.info("Bot started...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
        except Exception as err:
            logging.error(f"Polling error: {err}")
            time.sleep(3)
