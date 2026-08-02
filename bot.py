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

# Fetch Bot Token from Environment Variable or use provided Token as fallback
DEFAULT_BOT_TOKEN = "8888660501:AAGvIRYpwoQDn6B3JhLNyzNQg2lvoGtDBHc"
BOT_TOKEN = os.environ.get("BOT_TOKEN", DEFAULT_BOT_TOKEN)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# Temp storage for user sessions
user_data = {}

# Constants for A4 dimensions at 150 DPI (High Quality + Compressed file size)
A4_WIDTH = 1240
A4_HEIGHT = 1754

def get_user_session(chat_id):
    if chat_id not in user_data:
        user_data[chat_id] = {
            "state": None,
            "images": [],
            "pdfs": [],
            "layout_mode": "1_per_page", # Options: 1_per_page, 2_per_page, 4_per_page, newspaper
            "temp_pdf": None
        }
    return user_data[chat_id]

def reset_user_session(chat_id):
    if chat_id in user_data:
        user_data[chat_id] = {
            "state": None,
            "images": [],
            "pdfs": [],
            "layout_mode": "1_per_page",
            "temp_pdf": None
        }

# ----------------- IMAGE ENHANCEMENT & LAYOUT -----------------

def enhance_newspaper_image(pil_img):
    """Enhance image contrast and sharpness for newspaper screenshots for clear studying."""
    # Convert to Grayscale
    gray = pil_img.convert('L')
    # Increase Contrast
    enhancer = ImageEnhance.Contrast(gray)
    contrasted = enhancer.enhance(1.8)
    # Increase Sharpness for clear text
    sharp_enhancer = ImageEnhance.Sharpness(contrasted)
    sharpened = sharp_enhancer.enhance(2.0)
    # Convert back to RGB for PDF export
    return sharpened.convert('RGB')

def create_a4_canvas():
    return Image.new('RGB', (A4_WIDTH, A4_HEIGHT), (255, 255, 255))

def process_images_to_pdf(image_bytes_list, layout_mode="1_per_page"):
    """
    Combines a list of image bytes into a single HD compressed PDF based on layout.
    """
    pdf_pages = []
    
    # Load PIL Images
    loaded_imgs = []
    for b in image_bytes_list:
        img = Image.open(io.BytesIO(b))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        loaded_imgs.append(img)
        
    if layout_mode == "newspaper":
        # Enhanced contrast + 1 per page A4
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
        # 2 Images per A4 Page (Top & Bottom)
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
        # 4 Images per A4 Page (2x2 Grid)
        for i in range(0, len(loaded_imgs), 4):
            canvas = create_a4_canvas()
            batch = loaded_imgs[i:i+4]
            
            box_width = (A4_WIDTH - 120) // 2
            box_height = (A4_HEIGHT - 120) // 2
            
            positions = [
                (40, 40), # Top Left
                (80 + box_width, 40), # Top Right
                (40, 80 + box_height), # Bottom Left
                (80 + box_width, 80 + box_height) # Bottom Right
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

    # Export to PDF in-memory buffer with compression
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

# ----------------- TELEGRAM BOT HANDLERS -----------------

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    reset_user_session(message.chat.id)
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    
    btn1 = types.KeyboardButton("📸 Photos to PDF")
    btn2 = types.KeyboardButton("📰 Newspaper HD Scanner")
    btn3 = types.KeyboardButton("📑 Merge PDFs")
    btn4 = types.KeyboardButton("✂️ Delete PDF Pages")
    btn5 = types.KeyboardButton("🗜️ Compress PDF")
    btn6 = types.KeyboardButton("🔒 Protect / Unlock PDF")
    btn7 = types.KeyboardButton("📝 Extract Text")
    
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7)
    
    welcome_text = (
        "<b>✨ Welcome to your PDF Organizer Bot!</b>\n\n"
        "Select an option below to get started:\n\n"
        "• <b>📸 Photos to PDF:</b> Converts photos to full HD A4 PDF (1, 2, or 4 photos per page).\n"
        "• <b>📰 Newspaper HD Scanner:</b> Converts clips/screenshots into sharp HD study PDFs.\n"
        "• <b>📑 Merge PDFs:</b> Combine multiple PDF files into one.\n"
        "• <b>✂️ Delete Pages:</b> Easily remove unwanted pages.\n"
        "• <b>🗜️ Compress PDF:</b> Save storage space while preserving readable text.\n"
        "• <b>🔒 Protect/Unlock:</b> Add or remove passwords on PDF files.\n"
        "• <b>📝 Extract Text:</b> Copy editable text directly from PDF files."
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

# --- 1. PHOTOS TO PDF FLOW ---
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
        "📸 <b>Send me your photos one by one or in a batch.</b>\n\n"
        "Current Layout: <b>1 Photo per A4 Page</b>\n"
        "You can change the layout mode below:",
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
        f"✅ Layout changed to: <b>{names[layout]}</b>\n\nKeep sending photos or tap <b>'Generate PDF'</b> when finished.",
        call.message.chat.id,
        call.message.message_id
    )

# --- 2. NEWSPAPER SCREENSHOT SCANNER FLOW ---
@bot.message_handler(func=lambda msg: msg.text == "📰 Newspaper HD Scanner")
def newspaper_start(message):
    session = get_user_session(message.chat.id)
    reset_user_session(message.chat.id)
    session['state'] = 'COLLECTING_IMAGES'
    session['layout_mode'] = 'newspaper'
    
    bot.send_message(
        message.chat.id,
        "📰 <b>Newspaper HD Scanner</b>\n\n"
        "Send your newspaper screenshots or photo clips.\n"
        "I will apply contrast enhancement and text sharpening for easy reading and low file size!"
    )

# --- PHOTO / DOCUMENT RECEIVER ---
@bot.message_handler(content_types=['photo', 'document'], func=lambda msg: get_user_session(msg.chat.id)['state'] == 'COLLECTING_IMAGES')
def receive_image(message):
    session = get_user_session(message.chat.id)
    
    try:
        if message.content_type == 'photo':
            file_id = message.photo[-1].file_id
        else:
            if not message.document.mime_type.startswith("image/"):
                bot.reply_to(message, "⚠️ Please send valid image files.")
                return
            file_id = message.document.file_id
            
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        session['images'].append(downloaded_file)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(f"⚙️ Generate PDF ({len(session['images'])} Photos)", callback_data="build_image_pdf"),
            types.InlineKeyboardButton("❌ Clear Queue", callback_data="clear_images")
        )
        
        bot.reply_to(
            message,
            f"✅ Photo #{len(session['images'])} added to queue!",
            reply_markup=markup
        )
    except Exception as e:
        logging.error(f"Error downloading photo: {e}")
        bot.reply_to(message, "❌ Failed to process image. Try again.")

@bot.callback_query_handler(func=lambda call: call.data in ["build_image_pdf", "clear_images"])
def handle_image_pdf_actions(call):
    session = get_user_session(call.message.chat.id)
    
    if call.data == "clear_images":
        session['images'] = []
        bot.answer_callback_query(call.id, "Queue cleared!")
        bot.send_message(call.message.chat.id, "🗑️ All queued photos have been cleared.")
        return

    if call.data == "build_image_pdf":
        if not session['images']:
            bot.answer_callback_query(call.id, "No photos added yet!")
            return
            
        bot.answer_callback_query(call.id, "Generating HD PDF...")
        bot.send_message(call.message.chat.id, "⏳ <i>Processing and compressing HD PDF... Please wait.</i>")
        
        try:
            pdf_buffer = process_images_to_pdf(session['images'], session['layout_mode'])
            
            if pdf_buffer:
                filename = "newspaper_scan.pdf" if session['layout_mode'] == 'newspaper' else "document_photos.pdf"
                bot.send_document(
                    call.message.chat.id,
                    document=(filename, pdf_buffer.getvalue()),
                    caption="✅ <b>Here is your HD Compressed PDF!</b>"
                )
            else:
                bot.send_message(call.message.chat.id, "❌ Error generating PDF.")
        except Exception as e:
            logging.error(f"PDF build error: {e}")
            bot.send_message(call.message.chat.id, f"❌ Failed to build PDF: {str(e)}")
        finally:
            reset_user_session(call.message.chat.id)

# --- 3. MERGE PDFS FLOW ---
@bot.message_handler(func=lambda msg: msg.text == "📑 Merge PDFs")
def merge_start(message):
    session = get_user_session(message.chat.id)
    reset_user_session(message.chat.id)
    session['state'] = 'COLLECTING_PDFS'
    
    bot.send_message(
        message.chat.id,
        "📑 <b>Merge PDFs Mode</b>\n\n"
        "Send me 2 or more PDF files one by one.\n"
        "When ready, tap <b>'Merge Now'</b>."
    )

@bot.message_handler(content_types=['document'], func=lambda msg: get_user_session(msg.chat.id)['state'] == 'COLLECTING_PDFS')
def receive_pdf_for_merge(message):
    session = get_user_session(message.chat.id)
    
    if not message.document.file_name.endswith('.pdf'):
        bot.reply_to(message, "⚠️ Please upload a valid PDF document.")
        return
        
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        session['pdfs'].append(downloaded_file)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(f"📑 Merge Now ({len(session['pdfs'])} PDFs)", callback_data="exec_merge"),
            types.InlineKeyboardButton("❌ Cancel", callback_data="clear_images")
        )
        
        bot.reply_to(
            message,
            f"✅ Received PDF #{len(session['pdfs'])}: <i>{message.document.file_name}</i>",
            reply_markup=markup
        )
    except Exception as e:
        bot.reply_to(message, "❌ Failed to download PDF.")

@bot.callback_query_handler(func=lambda call: call.data == "exec_merge")
def process_merge(call):
    session = get_user_session(call.message.chat.id)
    
    if len(session['pdfs']) < 2:
        bot.answer_callback_query(call.id, "Send at least 2 PDFs to merge!")
        return
        
    bot.send_message(call.message.chat.id, "⏳ <i>Merging your PDFs...</i>")
    
    try:
        merger = PdfWriter()
        for pdf_bytes in session['pdfs']:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                merger.add_page(page)
                
        output_buffer = io.BytesIO()
        merger.write(output_buffer)
        output_buffer.seek(0)
        
        bot.send_document(
            call.message.chat.id,
            document=("merged_document.pdf", output_buffer.getvalue()),
            caption="✅ <b>PDFs merged successfully!</b>"
        )
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Error merging PDFs: {str(e)}")
    finally:
        reset_user_session(call.message.chat.id)

# --- 4. DELETE PDF PAGES FLOW ---
@bot.message_handler(func=lambda msg: msg.text == "✂️ Delete PDF Pages")
def delete_pages_start(message):
    session = get_user_session(message.chat.id)
    reset_user_session(message.chat.id)
    session['state'] = 'AWAITING_DELETE_PDF'
    
    bot.send_message(
        message.chat.id,
        "✂️ <b>Delete PDF Pages</b>\n\n"
        "Send me the PDF file you want to edit."
    )

@bot.message_handler(content_types=['document'], func=lambda msg: get_user_session(msg.chat.id)['state'] == 'AWAITING_DELETE_PDF')
def receive_pdf_for_deletion(message):
    session = get_user_session(message.chat.id)
    
    if not message.document.file_name.endswith('.pdf'):
        bot.reply_to(message, "⚠️ Please upload a valid PDF document.")
        return
        
    try:
        file_info = bot.get_file(message.document.file_id)
        session['temp_pdf'] = bot.download_file(file_info.file_path)
        
        reader = PdfReader(io.BytesIO(session['temp_pdf']))
        total_pages = len(reader.pages)
        
        session['state'] = 'AWAITING_PAGE_NUMBERS'
        
        bot.reply_to(
            message,
            f"📄 Document uploaded! Total Pages: <b>{total_pages}</b>\n\n"
            "Reply with the page numbers you want to <b>DELETE</b> (separated by commas).\n"
            "<i>Example: 1, 3, 5</i>"
        )
    except Exception as e:
        bot.reply_to(message, "❌ Failed to read PDF.")

@bot.message_handler(func=lambda msg: get_user_session(msg.chat.id)['state'] == 'AWAITING_PAGE_NUMBERS')
def execute_page_deletion(message):
    session = get_user_session(message.chat.id)
    
    try:
        pages_to_delete = [int(p.strip()) for p in message.text.split(',') if p.strip().isdigit()]
        
        reader = PdfReader(io.BytesIO(session['temp_pdf']))
        writer = PdfWriter()
        total_pages = len(reader.pages)
        
        deleted_count = 0
        for idx in range(total_pages):
            page_num = idx + 1
            if page_num not in pages_to_delete:
                writer.add_page(reader.pages[idx])
            else:
                deleted_count += 1
                
        if deleted_count == 0:
            bot.reply_to(message, "⚠️ None of the specified page numbers were valid.")
            return
            
        output_buffer = io.BytesIO()
        writer.write(output_buffer)
        output_buffer.seek(0)
        
        bot.send_document(
            message.chat.id,
            document=("modified_document.pdf", output_buffer.getvalue()),
            caption=f"✅ Deleted <b>{deleted_count}</b> page(s) successfully!"
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Error processing request: {str(e)}")
    finally:
        reset_user_session(message.chat.id)

# --- 5. COMPRESS PDF FLOW ---
@bot.message_handler(func=lambda msg: msg.text == "🗜️ Compress PDF")
def compress_start(message):
    session = get_user_session(message.chat.id)
    reset_user_session(message.chat.id)
    session['state'] = 'AWAITING_COMPRESS_PDF'
    
    bot.send_message(
        message.chat.id,
        "🗜️ <b>Compress PDF File</b>\n\nSend me the PDF file you want to compress."
    )

@bot.message_handler(content_types=['document'], func=lambda msg: get_user_session(msg.chat.id)['state'] == 'AWAITING_COMPRESS_PDF')
def compress_pdf_process(message):
    if not message.document.file_name.endswith('.pdf'):
        bot.reply_to(message, "⚠️ Please send a PDF file.")
        return
        
    bot.reply_to(message, "⏳ <i>Compressing PDF content... Please wait.</i>")
    
    try:
        file_info = bot.get_file(message.document.file_id)
        pdf_bytes = bot.download_file(file_info.file_path)
        
        reader = PdfReader(io.BytesIO(pdf_bytes))
        writer = PdfWriter()
        
        for page in reader.pages:
            page.compress_content_streams()
            writer.add_page(page)
            
        output_buffer = io.BytesIO()
        writer.write(output_buffer)
        output_buffer.seek(0)
        
        bot.send_document(
            message.chat.id,
            document=(f"compressed_{message.document.file_name}", output_buffer.getvalue()),
            caption="✅ <b>PDF compressed successfully!</b>"
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Failed to compress PDF: {str(e)}")
    finally:
        reset_user_session(message.chat.id)

# --- 6. PROTECT / UNLOCK PDF ---
@bot.message_handler(func=lambda msg: msg.text == "🔒 Protect / Unlock PDF")
def protect_unlock_start(message):
    session = get_user_session(message.chat.id)
    reset_user_session(message.chat.id)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔒 Add Password", callback_data="mode_encrypt"),
        types.InlineKeyboardButton("🔓 Remove Password", callback_data="mode_decrypt")
    )
    
    bot.send_message(message.chat.id, "Choose an option:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["mode_encrypt", "mode_decrypt"])
def pass_mode_select(call):
    session = get_user_session(call.message.chat.id)
    session['state'] = call.data
    bot.edit_message_text(
        "📄 Send the PDF file now.",
        call.message.chat.id,
        call.message.message_id
    )

@bot.message_handler(content_types=['document'], func=lambda msg: get_user_session(msg.chat.id)['state'] in ['mode_encrypt', 'mode_decrypt'])
def pass_pdf_receive(message):
    session = get_user_session(message.chat.id)
    
    try:
        file_info = bot.get_file(message.document.file_id)
        session['temp_pdf'] = bot.download_file(file_info.file_path)
        
        if session['state'] == 'mode_encrypt':
            session['state'] = 'AWAITING_ENCRYPT_PASS'
            bot.reply_to(message, "🔑 Send the password you want to set on this PDF:")
        else:
            session['state'] = 'AWAITING_DECRYPT_PASS'
            bot.reply_to(message, "🔑 Send the password to unlock this PDF:")
    except Exception as e:
        bot.reply_to(message, "❌ Error loading PDF.")

@bot.message_handler(func=lambda msg: get_user_session(msg.chat.id)['state'] in ['AWAITING_ENCRYPT_PASS', 'AWAITING_DECRYPT_PASS'])
def pass_process_exec(message):
    session = get_user_session(message.chat.id)
    password = message.text.strip()
    
    try:
        reader = PdfReader(io.BytesIO(session['temp_pdf']))
        writer = PdfWriter()
        
        if session['state'] == 'AWAITING_ENCRYPT_PASS':
            for page in reader.pages:
                writer.add_page(page)
            writer.encrypt(password)
            
            output_buffer = io.BytesIO()
            writer.write(output_buffer)
            output_buffer.seek(0)
            
            bot.send_document(
                message.chat.id,
                document=("protected_document.pdf", output_buffer.getvalue()),
                caption="🔒 <b>Password Protection Added!</b>"
            )
        else:
            if reader.is_encrypted:
                reader.decrypt(password)
            for page in reader.pages:
                writer.add_page(page)
                
            output_buffer = io.BytesIO()
            writer.write(output_buffer)
            output_buffer.seek(0)
            
            bot.send_document(
                message.chat.id,
                document=("unlocked_document.pdf", output_buffer.getvalue()),
                caption="🔓 <b>PDF Unlocked Successfully!</b>"
            )
    except Exception as e:
        bot.reply_to(message, f"❌ Failed: Check if password is correct. ({str(e)})")
    finally:
        reset_user_session(message.chat.id)

# --- 7. EXTRACT TEXT FROM PDF ---
@bot.message_handler(func=lambda msg: msg.text == "📝 Extract Text")
def extract_text_start(message):
    session = get_user_session(message.chat.id)
    reset_user_session(message.chat.id)
    session['state'] = 'AWAITING_TEXT_PDF'
    bot.send_message(message.chat.id, "📝 Send me a PDF file to extract text from.")

@bot.message_handler(content_types=['document'], func=lambda msg: get_user_session(msg.chat.id)['state'] == 'AWAITING_TEXT_PDF')
def extract_text_exec(message):
    try:
        file_info = bot.get_file(message.document.file_id)
        pdf_bytes = bot.download_file(file_info.file_path)
        
        reader = PdfReader(io.BytesIO(pdf_bytes))
        extracted = ""
        
        for idx, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                extracted += f"--- Page {idx+1} ---\n{text}\n\n"
                
        if not extracted.strip():
            bot.reply_to(message, "⚠️ Could not extract text. The PDF might contain scanned images without OCR text layer.")
        else:
            if len(extracted) > 4000:
                txt_buffer = io.BytesIO(extracted.encode('utf-8'))
                bot.send_document(message.chat.id, document=("extracted_text.txt", txt_buffer.getvalue()))
            else:
                bot.reply_to(message, f"<b>Extracted Text:</b>\n\n<pre>{extracted[:3900]}</pre>")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")
    finally:
        reset_user_session(message.chat.id)

# Start Polling Bot
if __name__ == "__main__":
    logging.info("PDF Telegram Bot is running...")
    bot.infinity_polling(skip_pending=True)
