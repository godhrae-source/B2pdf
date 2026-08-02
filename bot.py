import os
import io
import re
import math
import logging
from PIL import Image, ImageEnhance, ImageFilter
from pypdf import PdfReader, PdfWriter
import telebot
from telebot import types

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEFAULT_BOT_TOKEN = "8888660501:AAGvIRYpwoQDn6B3JhLNyzNQg2lvoGtDBHc"
BOT_TOKEN = os.environ.get("BOT_TOKEN", DEFAULT_BOT_TOKEN)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# Temp storage for user sessions
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
            "temp_pdf": None,
            "pdf_name": "document.pdf"
        }
    return user_data[chat_id]

def reset_user_session(chat_id):
    if chat_id in user_data:
        user_data[chat_id] = {
            "state": None,
            "images": [],
            "pdfs": [],
            "layout_mode": "1_per_page",
            "temp_pdf": None,
            "pdf_name": "document.pdf"
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
            canvas = create_a4_canvas()
            img_w, img_h = enhanced.size
            ratio = min((A4_WIDTH - 80) / img_w, (A4_HEIGHT - 80) / img_h)
            new_size = (int(img_w * ratio), int(img_h * ratio))
            resized = enhanced.resize(new_size, Image.Resampling.LANCZOS)
            offset = ((A4_WIDTH - new_size[0]) // 2, (A4_HEIGHT - new_size[1]) // 2)
            canvas.paste(resized, offset)
            pdf_pages.append(canvas)

    elif layout_mode == "1_per_page":
        for img in loaded_imgs:
            canvas = create_a4_canvas()
            img_w, img_h = img.size
            ratio = min((A4_WIDTH - 60) / img_w, (A4_HEIGHT - 60) / img_h)
            new_size = (int(img_w * ratio), int(img_h * ratio))
            resized = img.resize(new_size, Image.Resampling.LANCZOS)
            offset = ((A4_WIDTH - new_size[0]) // 2, (A4_HEIGHT - new_size[1]) // 2)
            canvas.paste(resized, offset)
            pdf_pages.append(canvas)

    elif layout_mode == "2_per_page":
        for i in range(0, len(loaded_imgs), 2):
            canvas = create_a4_canvas()
            batch = loaded_imgs[i:i+2]
            box_height = (A4_HEIGHT - 120) // 2
            box_width = A4_WIDTH - 80
            for idx, img in enumerate(batch):
                img_w, img_h = img.size
                ratio = min(box_width / img_w, box_height / img_h)
                new_size = (int(img_w * ratio), int(img_h * ratio))
                resized = img.resize(new_size, Image.Resampling.LANCZOS)
                x_offset = (A4_WIDTH - new_size[0]) // 2
                y_offset = 40 + idx * (box_height + 40) + (box_height - new_size[1]) // 2
                canvas.paste(resized, (x_offset, y_offset))
            pdf_pages.append(canvas)

    elif layout_mode == "4_per_page":
        for i in range(0, len(loaded_imgs), 4):
            canvas = create_a4_canvas()
            batch = loaded_imgs[i:i+4]
            box_width = (A4_WIDTH - 120) // 2
            box_height = (A4_HEIGHT - 120) // 2
            positions = [
                (40, 40),
                (80 + box_width, 40),
                (40, 80 + box_height),
                (80 + box_width, 80 + box_height)
            ]
            for idx, img in enumerate(batch):
                img_w, img_h = img.size
                ratio = min(box_width / img_w, box_height / img_h)
                new_size = (int(img_w * ratio), int(img_h * ratio))
                resized = img.resize(new_size, Image.Resampling.LANCZOS)
                pos_x, pos_y = positions[idx]
                x_offset = pos_x + (box_width - new_size[0]) // 2
                y_offset = pos_y + (box_height - new_size[1]) // 2
                canvas.paste(resized, (x_offset, y_offset))
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

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("📸 Photos to PDF")
    btn2 = types.KeyboardButton("📰 Newspaper HD Scanner")
    btn3 = types.KeyboardButton("📑 Merge PDFs")
    btn4 = types.KeyboardButton("✂️ Delete PDF Pages")
    btn5 = types.KeyboardButton("🗜️ Compress PDF")
    btn6 = types.KeyboardButton("🔒 Protect / Unlock PDF")
    btn7 = types.KeyboardButton("📝 Extract Text")
    btn8 = types.KeyboardButton("🔄 Home / Restart")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8)
    return markup

@bot.message_handler(commands=['start', 'help'])
@bot.message_handler(func=lambda msg: msg.text == "🔄 Home / Restart")
def send_welcome(message):
    reset_user_session(message.chat.id)
    welcome_text = (
        "<b>✨ Welcome to your PDF Organizer Bot!</b>\n\n"
        "Select an option below to get started:\n\n"
        "• <b>📸 Photos to PDF:</b> Convert photos to A4 HD PDF.\n"
        "• <b>📰 Newspaper HD Scanner:</b> Sharpen newspaper clips into PDF.\n"
        "• <b>📑 Merge PDFs:</b> Combine multiple PDFs into 1 file.\n"
        "• <b>✂️ Delete Pages:</b> Remove specific pages from a PDF.\n"
        "• <b>🗜️ Compress PDF:</b> Compress and shrink PDF size.\n"
        "• <b>🔒 Protect/Unlock:</b> Add or remove PDF password.\n"
        "• <b>📝 Extract Text:</b> Extract all readable text from a PDF."
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard())

# --- PHOTOS TO PDF ---
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
        "After sending photos, tap the <b>'⚙️ Generate PDF'</b> button below your photo.",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_layout_"))
def change_layout_callback(call):
    session = get_user_session(call.message.chat.id)
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
        call.message.chat.id,
        call.message.message_id
    )

# --- NEWSPAPER HD SCANNER ---
@bot.message_handler(func=lambda msg: msg.text == "📰 Newspaper HD Scanner")
def newspaper_start(message):
    session = get_user_session(message.chat.id)
    reset_user_session(message.chat.id)
    session['state'] = 'COLLECTING_IMAGES'
    session['layout_mode'] = 'newspaper'
    bot.send_message(message.chat.id, "📰 <b>Newspaper HD Scanner Active!</b>\n\nSend your screenshot or image clip now.")

# --- MERGE PDFS ---
@bot.message_handler(func=lambda msg: msg.text == "📑 Merge PDFs")
def merge_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'MERGE_PDFS'
    bot.send_message(message.chat.id, "📑 <b>Merge PDFs Mode:</b>\n\nSend 2 or more PDF documents one by one.")

# --- DELETE PAGES ---
@bot.message_handler(func=lambda msg: msg.text == "✂️ Delete PDF Pages")
def delete_pages_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'DELETE_PAGES'
    bot.send_message(message.chat.id, "✂️ <b>Delete Pages Mode:</b>\n\nPlease send me the PDF document.")

# --- COMPRESS PDF ---
@bot.message_handler(func=lambda msg: msg.text == "🗜️ Compress PDF")
def compress_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'COMPRESS_PDF'
    bot.send_message(message.chat.id, "🗜️ <b>Compress PDF Mode:</b>\n\nPlease send me the PDF document you want to compress.")

# --- PROTECT / UNLOCK PDF ---
@bot.message_handler(func=lambda msg: msg.text == "🔒 Protect / Unlock PDF")
def protect_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'PROTECT_PDF'
    bot.send_message(message.chat.id, "🔒 <b>Protect / Unlock PDF Mode:</b>\n\nPlease send me the PDF document.")

# --- EXTRACT TEXT ---
@bot.message_handler(func=lambda msg: msg.text == "📝 Extract Text")
def extract_text_start(message):
    reset_user_session(message.chat.id)
    session = get_user_session(message.chat.id)
    session['state'] = 'EXTRACT_TEXT'
    bot.send_message(message.chat.id, "📝 <b>Extract Text Mode:</b>\n\nPlease send me the PDF document you want text from.")

# --- PHOTO / IMAGE HANDLER ---
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
            f"✅ Photo #{len(session['images'])} received!\nTap below to build your PDF:",
            reply_markup=markup
        )
    except Exception as e:
        logging.error(f"Error downloading photo: {e}")

# --- DOCUMENT HANDLER ---
@bot.message_handler(content_types=['document'])
def handle_document(message):
    session = get_user_session(message.chat.id)
    chat_id = message.chat.id
    doc = message.document
    
    # Handle image documents in photo collection mode
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
        bot.reply_to(message, "❌ Please send a valid `.pdf` document.")
        return

    file_info = bot.get_file(doc.file_id)
    pdf_bytes = bot.download_file(file_info.file_path)

    # 1. MERGE PDFS
    if session['state'] == 'MERGE_PDFS':
        session['pdfs'].append(pdf_bytes)
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(f"⚙️ Merge Now ({len(session['pdfs'])} PDFs)", callback_data="do_merge_pdfs"),
            types.InlineKeyboardButton("❌ Clear", callback_data="clear_images")
        )
        bot.reply_to(message, f"✅ PDF #{len(session['pdfs'])} added! Send more or tap 'Merge Now'.", reply_markup=markup)

    # 2. DELETE PAGES
    elif session['state'] == 'DELETE_PAGES':
        session['temp_pdf'] = pdf_bytes
        session['state'] = 'WAIT_DELETE_PAGE_NUMS'
        reader = PdfReader(io.BytesIO(pdf_bytes))
        total = len(reader.pages)
        bot.reply_to(message, f"📖 PDF loaded ({total} total pages).\n\n<b>Reply with the page numbers to DELETE</b> (e.g. `1, 3, 5` or `2-4`):")

    # 3. COMPRESS PDF
    elif session['state'] == 'COMPRESS_PDF':
        bot.send_message(chat_id, "⏳ <i>Compressing PDF... Please wait.</i>")
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            writer = PdfWriter()
            for page in reader.pages:
                page.compress_content_streams()
                writer.add_page(page)
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            bot.send_document(chat_id, (f"compressed_{doc.file_name}", out.getvalue()), caption="✅ <b>Compressed PDF ready!</b>")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Compression failed: {e}")
        finally:
            reset_user_session(chat_id)

    # 4. PROTECT PDF
    elif session['state'] == 'PROTECT_PDF':
        session['temp_pdf'] = pdf_bytes
        session['state'] = 'WAIT_PASSWORD'
        bot.reply_to(message, "🔑 <b>Please type the password</b> you want to set on this PDF:")

    # 5. EXTRACT TEXT
    elif session['state'] == 'EXTRACT_TEXT':
        bot.send_message(chat_id, "⏳ <i>Extracting text...</i>")
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
                bot.send_message(chat_id, "⚠️ No readable text found (PDF might be scanned images).")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Text extraction failed: {e}")
        finally:
            reset_user_session(chat_id)
    else:
        bot.reply_to(message, "ℹ️ Please select an option from the menu first.")

# --- TEXT RESPONSES FOR INPUT MODES ---
@bot.message_handler(func=lambda msg: True)
def handle_text_inputs(message):
    session = get_user_session(message.chat.id)
    chat_id = message.chat.id

    if session['state'] == 'WAIT_DELETE_PAGE_NUMS':
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
            
            reader = PdfReader(io.BytesIO(session['temp_pdf']))
            writer = PdfWriter()
            total_pages = len(reader.pages)
            
            for i in range(total_pages):
                if (i + 1) not in pages_to_remove:
                    writer.add_page(reader.pages[i])
            
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            bot.send_document(chat_id, ("edited.pdf", out.getvalue()), caption="✅ <b>Updated PDF (Pages deleted)!</b>")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Failed: {e}. Please enter numbers like `1, 3` or `2-4`.")
        finally:
            reset_user_session(chat_id)

    elif session['state'] == 'WAIT_PASSWORD':
        try:
            pwd = message.text.strip()
            reader = PdfReader(io.BytesIO(session['temp_pdf']))
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            writer.encrypt(pwd)
            
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            bot.send_document(chat_id, ("protected.pdf", out.getvalue()), caption="🔒 <b>Password Protected PDF created!</b>")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Encryption failed: {e}")
        finally:
            reset_user_session(chat_id)

# --- CALLBACK BUTTON HANDLERS ---
@bot.callback_query_handler(func=lambda call: call.data in ["build_image_pdf", "clear_images", "do_merge_pdfs"])
def handle_callbacks(call):
    session = get_user_session(call.message.chat.id)
    chat_id = call.message.chat.id

    if call.data == "clear_images":
        reset_user_session(chat_id)
        bot.answer_callback_query(call.id, "Cleared!")
        bot.send_message(chat_id, "🗑️ All queued items cleared.")
        return

    if call.data == "build_image_pdf":
        if not session['images']:
            bot.answer_callback_query(call.id, "No photos added!")
            return
            
        bot.answer_callback_query(call.id, "Generating PDF...")
        bot.send_message(chat_id, "⏳ <i>Processing HD PDF... Please wait.</i>")
        try:
            pdf_buffer = process_images_to_pdf(session['images'], session['layout_mode'])
            if pdf_buffer:
                filename = "newspaper_scan.pdf" if session['layout_mode'] == 'newspaper' else "document_photos.pdf"
                bot.send_document(chat_id, (filename, pdf_buffer.getvalue()), caption="✅ <b>Here is your HD Compressed PDF!</b>")
            else:
                bot.send_message(chat_id, "❌ Error generating PDF.")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Failed: {str(e)}")
        finally:
            reset_user_session(chat_id)

    if call.data == "do_merge_pdfs":
        if len(session['pdfs']) < 2:
            bot.answer_callback_query(call.id, "Send at least 2 PDFs to merge!")
            return
            
        bot.answer_callback_query(call.id, "Merging PDFs...")
        bot.send_message(chat_id, "⏳ <i>Merging your PDFs...</i>")
        try:
            writer = PdfWriter()
            for pdf_bytes in session['pdfs']:
                reader = PdfReader(io.BytesIO(pdf_bytes))
                for page in reader.pages:
                    writer.add_page(page)
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            bot.send_document(chat_id, ("merged.pdf", out.getvalue()), caption="✅ <b>Merged PDF ready!</b>")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Merge failed: {e}")
        finally:
            reset_user_session(chat_id)

if __name__ == "__main__":
    logging.info("PDF Telegram Bot is running...")
    bot.infinity_polling(skip_pending=True)
