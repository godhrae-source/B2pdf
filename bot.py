import os
import io
import re
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# 1. RENDER HEALTH CHECK SERVER
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

# 2. BOT DEPENDENCIES
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

# --- MULTI-ENGINE SOCIAL MEDIA EXTRACTOR ---
def fetch_meta_post_images(url):
    """
    Extracts post photos using proxy engines (fxthreads, ddinstagram, oEmbed)
    that bypass Meta server IP blocks completely.
    """
    headers = {
        "User-Agent": "TelegramBot (like TwitterBot)"
    }

    # Resolve redirected /share/ app links
    try:
        if "/share/" in url:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True, timeout=8)
            url = r.url
    except Exception as e:
        logging.error(f"Redirect resolution failed: {e}")

    # Extract shortcode
    match = re.search(r'/(?:p|post|reel|t|share)/([A-Za-z0-9_-]+)', url)
    if not match:
        return []
    
    code = match.group(1)
    img_urls = []

    # METHOD 1: FXTHREADS / DDINSTAGRAM PARSER
    try:
        if "threads" in url:
            proxy_url = f"https://www.fxthreads.net/t/{code}"
        else:
            proxy_url = f"https://www.ddinstagram.com/p/{code}"

        res = requests.get(proxy_url, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # Find image meta tags
            meta_imgs = soup.find_all('meta', property=re.compile(r'og:image|twitter:image'))
            for tag in meta_imgs:
                content = tag.get('content')
                if content and 'scontent' in content or 'cdninstagram' in content or 'external' in content:
                    if content not in img_urls:
                        img_urls.append(content)
    except Exception as e:
        logging.error(f"Method 1 (FxProxy) failed: {e}")

    # METHOD 2: OEMBED API FALLBACK
    if not img_urls:
        try:
            if "threads" in url:
                oembed_endpoint = f"https://www.threads.net/oembed?url=https://www.threads.net/t/{code}"
            else:
                oembed_endpoint = f"https://api.instagram.com/oembed/?url=https://www.instagram.com/p/{code}"

            res = requests.get(oembed_endpoint, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            if res.status_code == 200:
                data = res.json()
                if data.get('thumbnail_url'):
                    img_urls.append(data['thumbnail_url'])
        except Exception as e:
            logging.error(f"Method 2 (oEmbed) failed: {e}")

    # STEP 1 COMPLETE: Download image raw bytes from extracted URLs
    image_bytes_list = []
    for img_url in img_urls:
        try:
            r = requests.get(img_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if r.status_code == 200 and len(r.content) > 5000:
                image_bytes_list.append(r.content)
        except Exception as err:
            logging.error(f"Image download failed: {err}")

    return image_bytes_list

# --- STEP 2: CONVERT IMAGES TO PDF ---
def enhance_newspaper_image(pil_img):
    gray = pil_img.convert('L')
    enhancer = ImageEnhance.Contrast(gray)
    contrasted = enhancer.enhance(1.8)
    sharp_enhancer = ImageEnhance.Sharpness(contrasted)
    sharpened = sharp_enhancer.enhance(2.0)
    return sharpened.convert('RGB')

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
            logging.error(f"Error converting image to page: {e}")

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

# --- KEYBOARD MENU (ALL 9 BUTTONS) ---
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("📸 Photos to PDF")
    btn2 = types.KeyboardButton("📰 Newspaper HD Scanner")
    btn3 = types.KeyboardButton("🧵 Threads & Insta to PDF")
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
        "Select an option below or paste any <b>Instagram / Threads post link</b> to generate a PDF instantly:"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard())

# --- BUTTON HANDLERS ---
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

@bot.message_handler(func=lambda msg: msg.text in ["🧵 Threads to PDF", "🧵 Threads & Insta to PDF"])
def threads_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'WAIT_THREADS_LINK'
    bot.send_message(message.chat.id, "🧵 <b>Paste any Instagram or Threads post link below:</b>")

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

# --- INSTAGRAM & THREADS LINK PROCESSOR ---
@bot.message_handler(func=lambda msg: True)
def handle_text_inputs(message):
    session = get_user_session(message.chat.id)
    chat_id = message.chat.id
    text = message.text.strip()

    # Detect Instagram or Threads links automatically
    link_match = re.search(r'https?://(?:www\.)?(?:threads\.(?:net|com)|instagram\.com|instagr\.am)/[^\s]+', text)
    
    if link_match or session['state'] == 'WAIT_THREADS_LINK':
        url = link_match.group(0) if link_match else text
        bot.send_message(chat_id, "🔍 <i>Downloading post images...</i>")
        try:
            # Step 1: Download post images using proxy engine
            image_bytes_list = fetch_meta_post_images(url)
            
            if not image_bytes_list:
                bot.send_message(
                    chat_id, 
                    "❌ <b>Could not extract post images.</b>\n\n"
                    "• Ensure the post contains photos.\n"
                    "• Ensure the profile is public."
                )
                return

            bot.send_message(chat_id, f"✅ Downloaded {len(image_bytes_list)} image(s)! Generating PDF...")
            
            # Step 2: Make PDF
            pdf_buffer = process_images_to_pdf(image_bytes_list, session.get('layout_mode', '1_per_page'))

            if pdf_buffer:
                bot.send_document(
                    chat_id, 
                    ("social_post.pdf", pdf_buffer.getvalue()), 
                    caption=f"✅ <b>PDF Ready!</b>\nConverted {len(image_bytes_list)} image(s)."
                )
        except Exception as e:
            bot.send_message(chat_id, f"❌ Processing Error: {e}")
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
    logging.info("Bot starting up...")
    bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
