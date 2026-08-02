import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# 1. IMMEDIATE WEBSERVER START (Prevents Render Free Plan Port Scan Timeout)
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

def enhance_newspaper_image(pil_img):
    gray = pil_img.convert('L')
    enhancer = ImageEnhance.Contrast(gray)
    contrasted = enhancer.enhance(1.8)
    sharp_enhancer = ImageEnhance.Sharpness(contrasted)
    sharpened = sharp_enhancer.enhance(2.0)
    return sharpened.convert('RGB')

# RAM-OPTIMIZED PDF PROCESSOR
def process_images_to_pdf(image_bytes_list, layout_mode="1_per_page"):
    pdf_pages = []
    
    for b in image_bytes_list:
        try:
            img = Image.open(io.BytesIO(b))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
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

# --- RECURSIVE JSON PARSER FOR CAROUSEL SLIDES ---
def extract_all_carousel_urls(obj, found_urls):
    if isinstance(obj, dict):
        # Look for image candidates inside Threads GraphQL / HTML structure
        if "candidates" in obj and isinstance(obj["candidates"], list):
            # Take highest quality image candidate
            if len(obj["candidates"]) > 0 and "url" in obj["candidates"][0]:
                found_urls.append(obj["candidates"][0]["url"])
        elif "image_versions2" in obj and isinstance(obj["image_versions2"], dict):
            candidates = obj["image_versions2"].get("candidates", [])
            if candidates and "url" in candidates[0]:
                found_urls.append(candidates[0]["url"])
        
        for k, v in obj.items():
            extract_all_carousel_urls(v, found_urls)
    elif isinstance(obj, list):
        for item in obj:
            extract_all_carousel_urls(item, found_urls)

# --- ADVANCED THREADS CAROUSEL SCRAPER ---
def extract_images_from_threads(threads_url):
    post_code_match = re.search(r'/(?:post|t)/([A-Za-z0-9_-]+)', threads_url)
    post_code = post_code_match.group(1) if post_code_match else None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Mode": "navigate"
    }
    
    img_urls = []

    # 1. Fetch full page source
    try:
        clean_url = f"https://www.threads.net/t/{post_code}/" if post_code else threads_url
        response = requests.get(clean_url, headers=headers, timeout=12)
        if response.status_code == 200:
            html = response.text
            
            # Extract raw embedded JSON blobs
            json_blobs = re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL)
            for blob in json_blobs:
                if 'image_versions2' in blob or 'carousel_media' in blob or 'candidates' in blob:
                    try:
                        data = json.loads(blob)
                        extract_all_carousel_urls(data, img_urls)
                    except Exception:
                        pass

            # Fallback regex search for multi-slide images inside page memory
            if not img_urls:
                raw_matches = re.findall(r'https://scontent[^\s"\'\\]+', html)
                for m in raw_matches:
                    m_clean = m.replace('\\/', '/').replace('\\u0026', '&')
                    if not any(x in m_clean for x in ['_s.jpg', '_a.jpg', 'p150x150', '50x50', 's150x150', 'e15']):
                        if m_clean not in img_urls:
                            img_urls.append(m_clean)

            # Og tag fallback if no carousel slides found
            if not img_urls:
                soup = BeautifulSoup(html, 'html.parser')
                for tag in soup.find_all('meta', property=['og:image', 'twitter:image']):
                    c = tag.get('content')
                    if c and c not in img_urls:
                        img_urls.append(c)

    except Exception as e:
        logging.error(f"Carousel Extraction Error: {e}")

    # Remove duplicates while keeping order
    unique_urls = []
    for u in img_urls:
        u_clean = u.replace('\\/', '/').replace('\\u0026', '&')
        if u_clean not in unique_urls:
            unique_urls.append(u_clean)

    logging.info(f"Found {len(unique_urls)} slide images for PDF.")

    # Download unique slides
    image_bytes_list = []
    dl_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    for url in unique_urls[:30]: # Up to 30 pages max per PDF
        try:
            r = requests.get(url, headers=dl_headers, timeout=10)
            if r.status_code == 200 and len(r.content) > 12000:
                image_bytes_list.append(r.content)
        except Exception as err:
            logging.error(f"Download fail: {err}")

    return image_bytes_list

# --- MENU KEYBOARD ---
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

# --- BUTTON COMMAND HANDLERS ---
@bot.message_handler(func=lambda msg: msg.text == "📸 Photos to PDF")
def photos_to_pdf_start(message):
    session = get_user_session(message.chat.id)
    reset_user_session(message.chat.id)
    session['state'] = 'COLLECTING_IMAGES'
    bot.send_message(message.chat.id, "📸 <b>Send me your photos now!</b>")

@bot.message_handler(func=lambda msg: msg.text == "📰 Newspaper HD Scanner")
def newspaper_start(message):
    session = get_user_session(message.chat.id)
    reset_user_session(message.chat.id)
    session['state'] = 'COLLECTING_IMAGES'
    session['layout_mode'] = 'newspaper'
    bot.send_message(message.chat.id, "📰 <b>Newspaper HD Scanner Active!</b>\n\nSend your screenshots/photos now.")

@bot.message_handler(func=lambda msg: msg.text == "🧵 Threads to PDF")
def threads_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'WAIT_THREADS_LINK'
    bot.send_message(message.chat.id, "🧵 <b>Paste any Threads post URL below:</b>")

@bot.message_handler(func=lambda msg: msg.text == "📑 Merge PDFs")
def merge_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'MERGE_PDFS'
    bot.send_message(message.chat.id, "📑 <b>Merge PDFs Mode:</b>\n\nSend 2 or more PDF files one by one.")

@bot.message_handler(func=lambda msg: msg.text == "✂️ Delete PDF Pages")
def delete_pages_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'DELETE_PAGES'
    bot.send_message(message.chat.id, "✂️ <b>Delete Pages Mode:</b>\n\nSend me your PDF file.")

@bot.message_handler(func=lambda msg: msg.text == "🗜️ Compress PDF")
def compress_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'COMPRESS_PDF'
    bot.send_message(message.chat.id, "🗜️ <b>Compress PDF Mode:</b>\n\nSend me your PDF file.")

@bot.message_handler(func=lambda msg: msg.text == "🔒 Protect / Unlock PDF")
def protect_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'PROTECT_PDF'
    bot.send_message(message.chat.id, "🔒 <b>Protect / Unlock PDF Mode:</b>\n\nSend me your PDF file.")

@bot.message_handler(func=lambda msg: msg.text == "📝 Extract Text")
def extract_text_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'EXTRACT_TEXT'
    bot.send_message(message.chat.id, "📝 <b>Extract Text Mode:</b>\n\nSend me your PDF file.")

# --- PHOTO HANDLER ---
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
        markup.add(
            types.InlineKeyboardButton(f"⚙️ Generate PDF ({len(session['images'])} Photos)", callback_data="build_image_pdf"),
            types.InlineKeyboardButton("❌ Clear", callback_data="clear_images")
        )
        bot.reply_to(message, f"✅ Photo #{len(session['images'])} received!", reply_markup=markup)
    except Exception as e:
        logging.error(f"Error: {e}")

# --- DOCUMENT HANDLER ---
@bot.message_handler(content_types=['document'])
def handle_document(message):
    session = get_user_session(message.chat.id)
    doc = message.document

    if doc.mime_type and doc.mime_type.startswith("image/"):
        file_info = bot.get_file(doc.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        session['images'].append(downloaded_file)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"⚙️ Generate PDF ({len(session['images'])} Photos)", callback_data="build_image_pdf"))
        bot.reply_to(message, f"✅ Photo #{len(session['images'])} received!", reply_markup=markup)
        return

    if not doc.file_name.lower().endswith('.pdf'):
        bot.reply_to(message, "❌ Please send a valid `.pdf` document or photo.")
        return

    file_info = bot.get_file(doc.file_id)
    session['active_pdf_bytes'] = bot.download_file(file_info.file_path)
    session['active_pdf_name'] = doc.file_name

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🗜️ Compress PDF", callback_data="act_compress"),
        types.InlineKeyboardButton("🔒 Protect / Unlock", callback_data="act_protect_unlock"),
        types.InlineKeyboardButton("✂️ Delete Pages", callback_data="act_delete_pages"),
        types.InlineKeyboardButton("📝 Extract Text", callback_data="act_extract_text"),
        types.InlineKeyboardButton("📑 Add to Merge Queue", callback_data="act_add_to_merge")
    )

    bot.reply_to(message, f"📄 <b>File Received:</b> <code>{doc.file_name}</code>", reply_markup=markup)

# --- ACTION CALLBACK HANDLERS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("act_"))
def handle_action_choice(call):
    session = get_user_session(call.message.chat.id)
    chat_id = call.message.chat.id
    action = call.data.replace("act_", "")

    pdf_bytes = session.get('active_pdf_bytes')

    if action == "compress":
        bot.send_message(chat_id, "⏳ <i>Compressing PDF...</i>")
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            writer = PdfWriter()
            writer.append(reader)
            for page in writer.pages:
                page.compress_content_streams()
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            bot.send_document(chat_id, (f"compressed_{session['active_pdf_name']}", out.getvalue()), caption="✅ Compressed!")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Failed: {e}")

    elif action == "protect_unlock":
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted:
            session['state'] = 'WAIT_UNLOCK_PASSWORD'
            bot.send_message(chat_id, "🔓 <b>PDF is Protected!</b> Enter password to unlock:")
        else:
            session['state'] = 'WAIT_PROTECT_PASSWORD'
            bot.send_message(chat_id, "🔒 <b>Protect PDF:</b> Enter new password:")

    elif action == "delete_pages":
        session['state'] = 'WAIT_DELETE_PAGE_NUMS'
        reader = PdfReader(io.BytesIO(pdf_bytes))
        bot.send_message(chat_id, f"📖 PDF has {len(reader.pages)} pages. Type page numbers to delete (e.g. `1, 3` or `2-4`):")

    elif action == "extract_text":
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            full_text = "".join([f"\n--- Page {i+1} ---\n" + (p.extract_text() or "") for i, p in enumerate(reader.pages)])
            if full_text.strip():
                bot.send_message(chat_id, full_text[:4000])
            else:
                bot.send_message(chat_id, "⚠️ No readable text found.")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Failed: {e}")

    elif action == "add_to_merge":
        session['state'] = 'MERGE_PDFS'
        session['pdfs'].append(pdf_bytes)
        bot.send_message(chat_id, f"📑 Added to Merge queue! ({len(session['pdfs'])} total). Send another or tap Merge.")

# --- TEXT & THREADS LINK INPUTS ---
@bot.message_handler(func=lambda msg: True)
def handle_text_inputs(message):
    session = get_user_session(message.chat.id)
    chat_id = message.chat.id
    text = message.text.strip()

    threads_match = re.search(r'https?://(?:www\.)?threads\.(?:net|com)/[^\s]+', text)
    
    if threads_match or session['state'] == 'WAIT_THREADS_LINK':
        url = threads_match.group(0) if threads_match else text
        bot.send_message(chat_id, "🔍 <i>Extracting all pages/slides from post...</i>")
        try:
            images = extract_images_from_threads(url)
            if not images:
                bot.send_message(
                    chat_id, 
                    "❌ <b>Could not extract images from this post.</b>\n\n"
                    "• Ensure the post contains images/slides.\n"
                    "• Ensure the user account is public."
                )
                return

            bot.send_message(chat_id, f"✅ Found {len(images)} slide(s)! Creating PDF document...")
            pdf_buffer = process_images_to_pdf(images, layout_mode="1_per_page")

            if pdf_buffer:
                bot.send_document(
                    chat_id, 
                    ("threads_carousel.pdf", pdf_buffer.getvalue()), 
                    caption=f"✅ <b>Threads PDF Ready!</b>\nConverted all {len(images)} pages."
                )
        except Exception as e:
            bot.send_message(chat_id, f"❌ Failed: {e}")
        finally:
            reset_user_session(chat_id)

    elif session['state'] == 'WAIT_DELETE_PAGE_NUMS':
        try:
            pages_to_remove = set()
            for part in text.split(','):
                part = part.strip()
                if '-' in part:
                    s, e = map(int, part.split('-'))
                    pages_to_remove.update(range(s, e + 1))
                else:
                    pages_to_remove.add(int(part))
            
            reader = PdfReader(io.BytesIO(session['active_pdf_bytes']))
            writer = PdfWriter()
            writer.append(reader)
            
            for p_num in sorted(list(pages_to_remove), reverse=True):
                if 1 <= p_num <= len(writer.pages):
                    writer.remove_page(p_num - 1)
            
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            bot.send_document(chat_id, ("edited.pdf", out.getvalue()), caption="✅ PDF updated!")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error: {e}")
        finally:
            reset_user_session(chat_id)

    elif session['state'] in ['WAIT_PROTECT_PASSWORD', 'WAIT_UNLOCK_PASSWORD']:
        try:
            reader = PdfReader(io.BytesIO(session['active_pdf_bytes']))
            writer = PdfWriter()
            if session['state'] == 'WAIT_UNLOCK_PASSWORD':
                reader.decrypt(text)
                writer.append(reader)
            else:
                writer.append(reader)
                writer.encrypt(text)
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            bot.send_document(chat_id, ("processed.pdf", out.getvalue()), caption="✅ Success!")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Password Error: {e}")
        finally:
            reset_user_session(chat_id)

# --- CALLBACK ROUTER ---
@bot.callback_query_handler(func=lambda call: call.data in ["build_image_pdf", "clear_images"])
def handle_callbacks(call):
    session = get_user_session(call.message.chat.id)
    chat_id = call.message.chat.id

    if call.data == "clear_images":
        reset_user_session(chat_id)
        bot.send_message(chat_id, "🗑️ Cleared queue.")

    elif call.data == "build_image_pdf":
        if session['images']:
            bot.send_message(chat_id, "⏳ Generating PDF...")
            pdf_buffer = process_images_to_pdf(session['images'], session['layout_mode'])
            if pdf_buffer:
                bot.send_document(chat_id, ("document.pdf", pdf_buffer.getvalue()), caption="✅ Your PDF is ready!")
            reset_user_session(chat_id)

if __name__ == "__main__":
    logging.info("Bot started...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
        except Exception as err:
            logging.error(f"Polling error: {err}")
            time.sleep(3)
