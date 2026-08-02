import os
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

# Configure logging
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

def process_images_to_pdf(image_bytes_list, layout_mode="1_per_page"):
    pdf_pages = []
    loaded_imgs = []
    for b in image_bytes_list:
        img = Image.open(io.BytesIO(b))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        loaded_imgs.append(img)
        
    if layout_mode == "newspaper":
        for img in loaded_imgs:
            enhanced = enhance_newspaper_image(img)
            filled_img = ImageOps.fit(enhanced, (A4_WIDTH, A4_HEIGHT), Image.Resampling.LANCZOS)
            pdf_pages.append(filled_img)

    elif layout_mode == "1_per_page":
        for img in loaded_imgs:
            filled_img = ImageOps.fit(img, (A4_WIDTH, A4_HEIGHT), Image.Resampling.LANCZOS)
            pdf_pages.append(filled_img)

    elif layout_mode == "2_per_page":
        for i in range(0, len(loaded_imgs), 2):
            canvas = create_a4_canvas()
            batch = loaded_imgs[i:i+2]
            
            first_img = batch[0]
            is_tall = first_img.height > first_img.width

            if is_tall:
                # SIDE BY SIDE (Left & Right)
                box_w = A4_WIDTH // 2
                box_h = A4_HEIGHT
                positions = [(0, 0), (box_w, 0)]
            else:
                # TOP AND BOTTOM (Up & Down)
                box_w = A4_WIDTH
                box_h = A4_HEIGHT // 2
                positions = [(0, 0), (0, box_h)]

            for idx, img in enumerate(batch):
                cropped_img = ImageOps.fit(img, (box_w, box_h), Image.Resampling.LANCZOS)
                canvas.paste(cropped_img, positions[idx])
                
            pdf_pages.append(canvas)

    elif layout_mode == "4_per_page":
        for i in range(0, len(loaded_imgs), 4):
            canvas = create_a4_canvas()
            batch = loaded_imgs[i:i+4]
            box_w = A4_WIDTH // 2
            box_h = A4_HEIGHT // 2
            positions = [
                (0, 0),
                (box_w, 0),
                (0, box_h),
                (box_w, box_h)
            ]
            for idx, img in enumerate(batch):
                cropped_img = ImageOps.fit(img, (box_w, box_h), Image.Resampling.LANCZOS)
                canvas.paste(cropped_img, positions[idx])
            pdf_pages.append(canvas)

    output_buffer = io.BytesIO()
    if pdf_pages:
        pdf_pages[0].save(
            output_buffer,
            format="PDF",
            save_all=True,
            append_images=pdf_pages[1:],
            resolution=150.0,
            quality=85,
            optimize=True
        )
        output_buffer.seek(0)
        return output_buffer
    return None

# --- THREADS IMAGE EXTRACTOR ---
def extract_images_from_threads(url):
    # Uses Facebook crawler User-Agent to retrieve OpenGraph preview images from Threads
    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            logging.error(f"Threads request failed status: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        image_bytes_list = []
        img_urls = []

        # Find og:image meta tags
        og_images = soup.find_all('meta', property='og:image')
        for tag in og_images:
            content = tag.get('content')
            if content and content not in img_urls:
                img_urls.append(content)

        # Fallback to twitter:image meta tags
        if not img_urls:
            tw_images = soup.find_all('meta', attrs={'name': 'twitter:image'})
            for tag in tw_images:
                content = tag.get('content')
                if content and content not in img_urls:
                    img_urls.append(content)

        dl_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        for img_url in img_urls:
            try:
                img_resp = requests.get(img_url, headers=dl_headers, timeout=10)
                if img_resp.status_code == 200 and len(img_resp.content) > 5000:
                    image_bytes_list.append(img_resp.content)
            except Exception as err:
                logging.error(f"Error fetching image {img_url}: {err}")

        return image_bytes_list

    except Exception as e:
        logging.error(f"Threads extraction exception: {e}")
        return []

# --- MAIN KEYBOARD ---
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

# --- BUTTON HANDLERS ---
@bot.message_handler(func=lambda msg: msg.text == "📸 Photos to PDF")
def photos_to_pdf_start(message):
    session = get_user_session(message.chat.id)
    reset_user_session(message.chat.id)
    session['state'] = 'COLLECTING_IMAGES'
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("1 Photo / A4 Page", callback_data="set_layout_1_per_page"),
        types.InlineKeyboardButton("2 Photos / A4 Page", callback_data="set_layout_2_per_page"),
        types.InlineKeyboardButton("4 Photos Grid / A4 Page", callback_data="set_layout_4_per_page")
    )
    bot.send_message(
        message.chat.id,
        "📸 <b>Send me your photos now!</b>\n\n"
        "After sending photos, tap the <b>'⚙️ Generate PDF'</b> button attached to the photo.",
        reply_markup=markup
    )

@bot.message_handler(func=lambda msg: msg.text == "📰 Newspaper HD Scanner")
def newspaper_start(message):
    session = get_user_session(message.chat.id)
    reset_user_session(message.chat.id)
    session['state'] = 'COLLECTING_IMAGES'
    session['layout_mode'] = 'newspaper'
    bot.send_message(message.chat.id, "📰 <b>Newspaper HD Scanner Active!</b>\n\nSend your screenshot or photo clip now.")

@bot.message_handler(func=lambda msg: msg.text == "🧵 Threads to PDF")
def threads_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'WAIT_THREADS_LINK'
    bot.send_message(
        message.chat.id,
        "🧵 <b>Threads Post to PDF:</b>\n\nPlease send/paste the Threads post URL.\n\n<i>Example:</i> <code>https://www.threads.net/@user/post/C123456789</code>"
    )

@bot.message_handler(func=lambda msg: msg.text == "📑 Merge PDFs")
def merge_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'MERGE_PDFS'
    bot.send_message(message.chat.id, "📑 <b>Merge PDFs Mode:</b>\n\nSend 2 or more PDF documents one by one.")

@bot.message_handler(func=lambda msg: msg.text == "✂️ Delete PDF Pages")
def delete_pages_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'DELETE_PAGES'
    bot.send_message(message.chat.id, "✂️ <b>Delete Pages Mode:</b>\n\nPlease send me your PDF document.")

@bot.message_handler(func=lambda msg: msg.text == "🗜️ Compress PDF")
def compress_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'COMPRESS_PDF'
    bot.send_message(message.chat.id, "🗜️ <b>Compress PDF Mode:</b>\n\nPlease send me your PDF document.")

@bot.message_handler(func=lambda msg: msg.text == "🔒 Protect / Unlock PDF")
def protect_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'PROTECT_PDF'
    bot.send_message(message.chat.id, "🔒 <b>Protect / Unlock PDF Mode:</b>\n\nPlease send me your PDF document.")

@bot.message_handler(func=lambda msg: msg.text == "📝 Extract Text")
def extract_text_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'EXTRACT_TEXT'
    bot.send_message(message.chat.id, "📝 <b>Extract Text Mode:</b>\n\nPlease send me your PDF document.")

# --- PHOTO HANDLER ---
@bot.message_handler(content_types=['photo'])
def receive_image(message):
    session = get_user_session(message.chat.id)
    if session['state'] != 'COLLECTING_IMAGES':
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
        
        bot.reply_to(
            message,
            f"✅ Photo #{len(session['images'])} received!\nTap below to build your HD PDF:",
            reply_markup=markup
        )
    except Exception as e:
        logging.error(f"Error downloading photo: {e}")

# --- PDF DOCUMENT HANDLER ---
@bot.message_handler(content_types=['document'])
def handle_document(message):
    session = get_user_session(message.chat.id)
    chat_id = message.chat.id
    doc = message.document
    
    if doc.mime_type and doc.mime_type.startswith("image/"):
        file_info = bot.get_file(doc.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        session['images'].append(downloaded_file)
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(f"⚙️ Generate PDF ({len(session['images'])} Photos)", callback_data="build_image_pdf"),
            types.InlineKeyboardButton("❌ Clear", callback_data="clear_images")
        )
        bot.reply_to(message, f"✅ Photo #{len(session['images'])} received!", reply_markup=markup)
        return

    if not doc.file_name.lower().endswith('.pdf'):
        bot.reply_to(message, "❌ Please send a valid `.pdf` document or photo.")
        return

    file_info = bot.get_file(doc.file_id)
    pdf_bytes = bot.download_file(file_info.file_path)

    session['active_pdf_bytes'] = pdf_bytes
    session['active_pdf_name'] = doc.file_name

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🗜️ Compress PDF", callback_data="act_compress"),
        types.InlineKeyboardButton("🔒 Protect / Unlock", callback_data="act_protect_unlock"),
        types.InlineKeyboardButton("✂️ Delete Pages", callback_data="act_delete_pages"),
        types.InlineKeyboardButton("📝 Extract Text", callback_data="act_extract_text"),
        types.InlineKeyboardButton("📑 Add to Merge Queue", callback_data="act_add_to_merge")
    )

    bot.reply_to(
        message,
        f"📄 <b>File Received:</b> <code>{doc.file_name}</code>\n\nWhat would you like to do with this file?",
        reply_markup=markup
    )

# --- ACTION MENU CALLBACKS FOR SENT PDFS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("act_"))
def handle_action_choice(call):
    session = get_user_session(call.message.chat.id)
    chat_id = call.message.chat.id
    action = call.data.replace("act_", "")

    pdf_bytes = session.get('active_pdf_bytes')
    if not pdf_bytes and action != "add_to_merge":
        bot.answer_callback_query(call.id, "Please re-send your PDF file.")
        return

    if action == "compress":
        bot.answer_callback_query(call.id, "Compressing PDF...")
        bot.send_message(chat_id, "⏳ <i>Compressing PDF... Please wait.</i>")
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            writer = PdfWriter()
            writer.append(reader)
            for page in writer.pages:
                page.compress_content_streams()

            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            bot.send_document(chat_id, (f"compressed_{session['active_pdf_name']}", out.getvalue()), caption="✅ <b>Compressed PDF ready!</b>")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Compression failed: {e}")

    elif action == "protect_unlock":
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted:
            session['state'] = 'WAIT_UNLOCK_PASSWORD'
            bot.send_message(chat_id, "🔓 <b>PDF is Protected!</b>\n\nPlease type the password to unlock it:")
        else:
            session['state'] = 'WAIT_PROTECT_PASSWORD'
            bot.send_message(chat_id, "🔒 <b>Protect PDF:</b>\n\nPlease type the password you want to set:")

    elif action == "delete_pages":
        session['state'] = 'WAIT_DELETE_PAGE_NUMS'
        reader = PdfReader(io.BytesIO(pdf_bytes))
        total = len(reader.pages)
        bot.send_message(chat_id, f"📖 PDF loaded ({total} total pages).\n\n<b>Type page numbers to DELETE</b> (e.g. `1, 3` or `2-4`):")

    elif action == "extract_text":
        bot.answer_callback_query(call.id, "Extracting text...")
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            full_text = ""
            for idx, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    full_text += f"<b>--- Page {idx+1} ---</b>\n{text}\n\n"
            
            if full_text.strip():
                if len(full_text) > 4000:
                    txt_file = io.BytesIO(full_text.encode('utf-8'))
                    bot.send_document(chat_id, ("extracted_text.txt", txt_file.getvalue()), caption="📝 Extracted Text File")
                else:
                    bot.send_message(chat_id, full_text)
            else:
                bot.send_message(chat_id, "⚠️ No readable text found in PDF.")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Extraction failed: {e}")

    elif action == "add_to_merge":
        session['state'] = 'MERGE_PDFS'
        session['pdfs'].append(pdf_bytes)
        bot.send_message(chat_id, f"📑 Added to Merge queue! ({len(session['pdfs'])} total). Send another PDF or tap 'Merge PDFs' in main menu.")

# --- TEXT RESPONSES & THREADS LINKS ---
@bot.message_handler(func=lambda msg: True)
def handle_text_inputs(message):
    session = get_user_session(message.chat.id)
    chat_id = message.chat.id
    text = message.text.strip()

    threads_match = re.search(r'https?://(?:www\.)?threads\.net/[^\s]+', text)
    
    if threads_match or session['state'] == 'WAIT_THREADS_LINK':
        url = threads_match.group(0) if threads_match else text
        if not url.startswith("http"):
            bot.send_message(chat_id, "❌ Invalid URL format. Send a valid Threads post link.")
            return

        bot.send_message(chat_id, "🔍 <i>Fetching images from Threads post... Please wait.</i>")
        
        try:
            images = extract_images_from_threads(url)
            if not images:
                bot.send_message(chat_id, "❌ Could not find any images in that Threads post or the link is private/invalid.")
                return

            bot.send_message(chat_id, f"✅ Found {len(images)} image(s)! Converting to PDF...")
            pdf_buffer = process_images_to_pdf(images, layout_mode="1_per_page")

            if pdf_buffer:
                bot.send_document(
                    chat_id,
                    ("threads_post.pdf", pdf_buffer.getvalue()),
                    caption=f"✅ <b>Threads Post PDF Ready!</b>\n\nDownloaded {len(images)} images."
                )
            else:
                bot.send_message(chat_id, "❌ Error generating PDF from post images.")

        except Exception as e:
            bot.send_message(chat_id, f"❌ Failed to process Threads post: {e}")
        finally:
            reset_user_session(chat_id)

    elif session['state'] == 'WAIT_DELETE_PAGE_NUMS':
        try:
            input_text = message.text
            pages_to_remove = set()
            for part in input_text.split(','):
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
            bot.send_document(chat_id, ("edited.pdf", out.getvalue()), caption="✅ <b>Updated PDF (Pages deleted)!</b>")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Failed: {e}. Enter numbers like `1, 3` or `2-4`.")
        finally:
            reset_user_session(chat_id)

    elif session['state'] == 'WAIT_PROTECT_PASSWORD':
        try:
            pwd = message.text.strip()
            reader = PdfReader(io.BytesIO(session['active_pdf_bytes']))
            writer = PdfWriter()
            writer.append(reader)
            writer.encrypt(pwd)
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            bot.send_document(chat_id, ("protected.pdf", out.getvalue()), caption="🔒 <b>Password Protected PDF created!</b>")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Protection failed: {e}")
        finally:
            reset_user_session(chat_id)

    elif session['state'] == 'WAIT_UNLOCK_PASSWORD':
        try:
            pwd = message.text.strip()
            reader = PdfReader(io.BytesIO(session['active_pdf_bytes']))
            reader.decrypt(pwd)
            writer = PdfWriter()
            writer.append(reader)
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            bot.send_document(chat_id, ("unlocked.pdf", out.getvalue()), caption="🔓 <b>PDF Password Removed Successfully!</b>")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Unlock failed (Wrong Password): {e}")
        finally:
            reset_user_session(chat_id)

# --- CALLBACK BUTTON HANDLERS ---
@bot.callback_query_handler(func=lambda call: call.data in ["build_image_pdf", "clear_images", "do_merge_pdfs"] or call.data.startswith("set_layout_"))
def handle_callbacks(call):
    session = get_user_session(call.message.chat.id)
    chat_id = call.message.chat.id

    if call.data.startswith("set_layout_"):
        layout = call.data.replace("set_layout_", "")
        session['layout_mode'] = layout
        names = {
            "1_per_page": "1 Photo / A4 Page",
            "2_per_page": "2 Photos / A4 Page",
            "4_per_page": "4 Photos Grid / A4 Page"
        }
        bot.answer_callback_query(call.id, f"Layout set to: {names[layout]}")
        bot.edit_message_text(
            f"✅ Layout changed to: <b>{names[layout]}</b>\n\nNow send your photo(s)!",
            chat_id,
            call.message.message_id
        )

    elif call.data == "clear_images":
        reset_user_session(chat_id)
        bot.answer_callback_query(call.id, "Cleared!")
        bot.send_message(chat_id, "🗑️ All queued items cleared.")

    elif call.data == "build_image_pdf":
        if not session['images']:
            bot.answer_callback_query(call.id, "No photos added yet!")
            return
            
        bot.answer_callback_query(call.id, "Generating HD PDF...")
        bot.send_message(chat_id, "⏳ <i>Processing HD PDF... Please wait.</i>")
        try:
            pdf_buffer = process_images_to_pdf(session['images'], session['layout_mode'])
            if pdf_buffer:
                filename = "newspaper_scan.pdf" if session['layout_mode'] == 'newspaper' else "document_photos.pdf"
                bot.send_document(chat_id, (filename, pdf_buffer.getvalue()), caption="✅ <b>Here is your HD Compressed PDF!</b>")
            else:
                bot.send_message(chat_id, "❌ Error generating PDF.")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Failed to build PDF: {str(e)}")
        finally:
            reset_user_session(chat_id)

    elif call.data == "do_merge_pdfs":
        if len(session['pdfs']) < 2:
            bot.answer_callback_query(call.id, "Send at least 2 PDFs to merge!")
            return
            
        bot.answer_callback_query(call.id, "Merging PDFs...")
        bot.send_message(chat_id, "⏳ <i>Merging your PDFs...</i>")
        try:
            writer = PdfWriter()
            for pdf_bytes in session['pdfs']:
                reader = PdfReader(io.BytesIO(pdf_bytes))
                writer.append(reader)
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            bot.send_document(chat_id, ("merged.pdf", out.getvalue()), caption="✅ <b>Merged PDF ready!</b>")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Merge failed: {e}")
        finally:
            reset_user_session(chat_id)

if __name__ == "__main__":
    logging.info("PDF Telegram Bot starting resilience loop...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
        except Exception as err:
            logging.error(f"Polling connection error encountered: {err}")
            time.sleep(3)
