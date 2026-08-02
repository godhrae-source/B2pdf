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
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7)
    return markup

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    reset_user_session(message.chat.id)
    welcome_text = (
        "<b>✨ Welcome to your PDF Organizer Bot!</b>\n\n"
        "Select an option below to get started:\n\n"
        "• <b>📸 Photos to PDF:</b> Converts photos to full HD A4 PDF.\n"
        "• <b>📰 Newspaper HD Scanner:</b> Converts clips/screenshots into sharp HD study PDFs.\n"
        "• <b>📑 Merge PDFs:</b> Combine multiple PDF files into one.\n"
        "• <b>✂️ Delete Pages:</b> Easily remove unwanted pages.\n"
        "• <b>🗜️ Compress PDF:</b> Save storage space while preserving readable text."
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard())

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

@bot.message_handler(func=lambda msg: msg.text == "📰 Newspaper HD Scanner")
def newspaper_start(message):
    session = get_user_session(message.chat.id)
    reset_user_session(message.chat.id)
    session['state'] = 'COLLECTING_IMAGES'
    session['layout_mode'] = 'newspaper'
    
    bot.send_message(
        message.chat.id,
        "📰 <b>Newspaper HD Scanner Activated!</b>\n\n"
        "Please send your newspaper screenshot or image clip now."
    )

@bot.message_handler(content_types=['photo', 'document'])
def receive_image(message):
    session = get_user_session(message.chat.id)
    
    # Auto-activate collection mode if image is sent directly
    if session['state'] != 'COLLECTING_IMAGES':
        session['state'] = 'COLLECTING_IMAGES'
    
    try:
        if message.content_type == 'photo':
            file_id = message.photo[-1].file_id
        else:
            if not message.document.mime_type.startswith("image/"):
                return
            file_id = message.document.file_id
            
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        session['images'].append(downloaded_file)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(f"⚙️ Generate PDF ({len(session['images'])} Photo)", callback_data="build_image_pdf"),
            types.InlineKeyboardButton("❌ Clear", callback_data="clear_images")
        )
        
        bot.reply_to(
            message,
            f"✅ Photo #{len(session['images'])} received!\nTap below to build your HD PDF:",
            reply_markup=markup
        )
    except Exception as e:
        logging.error(f"Error downloading photo: {e}")

@bot.callback_query_handler(func=lambda call: call.data in ["build_image_pdf", "clear_images"])
def handle_image_pdf_actions(call):
    session = get_user_session(call.message.chat.id)
    
    if call.data == "clear_images":
        session['images'] = []
        bot.answer_callback_query(call.id, "Queue cleared!")
        bot.send_message(call.message.chat.id, "🗑️ All queued photos cleared.")
        return

    if call.data == "build_image_pdf":
        if not session['images']:
            bot.answer_callback_query(call.id, "No photos added yet!")
            return
            
        bot.answer_callback_query(call.id, "Generating HD PDF...")
        bot.send_message(call.message.chat.id, "⏳ <i>Processing HD PDF... Please wait.</i>")
        
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
            bot.send_message(call.message.chat.id, f"❌ Failed to build PDF: {str(e)}")
        finally:
            reset_user_session(call.message.chat.id)

if __name__ == "__main__":
    logging.info("PDF Telegram Bot is running...")
    bot.infinity_polling(skip_pending=True)
