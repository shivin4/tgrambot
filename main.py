import os
import json
import logging
from pathlib import Path
from threading import Thread, Lock
from functools import wraps
import asyncio

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
from flask import Flask, request

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# --- Load environment variables ---
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
FERNET_KEY = os.getenv('FERNET_KEY')
OWNER_ID = int(os.getenv('OWNER_ID'))
WEBHOOK_URL = os.getenv('WEBHOOK_URL') + '/webhook'

# --- Setup Fernet encryption ---
fernet = Fernet(FERNET_KEY.encode())

# --- Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Flask app ---
app = Flask(__name__)

# --- JSON data file ---
DATA_FILE = 'data.json'

def load_data():
    if Path(DATA_FILE).exists():
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load data: {e}")
    return {"keys": {}, "notes": {}, "next_note_id": 1}

def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save data: {e}")

def encrypt_data(data: str) -> str:
    return fernet.encrypt(data.encode()).decode()

def decrypt_data(encrypted: str) -> str:
    return fernet.decrypt(encrypted.encode()).decode()

def owner_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("🚫 Unauthorized access.")
            logger.warning(f"Unauthorized: {update.effective_user.id}")
            return
        return await func(update, context)
    return wrapper

# --- Bot Commands ---
@owner_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔐 Secure Key Manager Bot\n\n"
        "Commands:\n"
        "/addkey <name> <value>\n"
        "/getkey <name>\n"
        "/deletekey <name>\n"
        "/listkeys\n"
        "/addnote <text>\n"
        "/getnotes\n"
        "/deletenote <id>"
    )

@owner_only
async def add_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addkey <name> <value>")
        return
    key_name = context.args[0]
    key_value = ' '.join(context.args[1:])
    data = load_data()
    data["keys"][key_name] = encrypt_data(key_value)
    save_data(data)
    await update.message.reply_text(f"✅ Key '{key_name}' added.")

@owner_only
async def get_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /getkey <name>")
        return
    key_name = context.args[0]
    data = load_data()
    if key_name not in data["keys"]:
        await update.message.reply_text(f"❌ Key '{key_name}' not found.")
        return
    try:
        decrypted = decrypt_data(data["keys"][key_name])
        await update.message.reply_text(f"🔑 {key_name}: `{decrypted}`", parse_mode='Markdown')
    except InvalidToken:
        await update.message.reply_text("⚠️ Failed to decrypt key.")

@owner_only
async def list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["keys"]:
        await update.message.reply_text("No keys stored.")
        return
    msg = "\n".join([f"• {k}" for k in data["keys"]])
    await update.message.reply_text(f"🔐 Stored keys:\n{msg}")

@owner_only
async def delete_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /deletekey <name>")
        return
    key_name = context.args[0]
    data = load_data()
    if key_name not in data["keys"]:
        await update.message.reply_text("❌ Key not found.")
        return
    del data["keys"][key_name]
    save_data(data)
    await update.message.reply_text(f"🗑️ Deleted '{key_name}'.")

@owner_only
async def add_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addnote <text>")
        return
    note_text = ' '.join(context.args)
    data = load_data()
    note_id = data["next_note_id"]
    data["notes"][str(note_id)] = encrypt_data(note_text)
    data["next_note_id"] += 1
    save_data(data)
    await update.message.reply_text(f"📝 Note saved (ID: {note_id})")

@owner_only
async def get_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["notes"]:
        await update.message.reply_text("No notes stored.")
        return
    msg = "📝 Notes:\n\n"
    keyboard = []
    for note_id, enc_text in data["notes"].items():
        try:
            dec_text = decrypt_data(enc_text)
            # Truncate long notes for display
            display_text = dec_text[:50] + "..." if len(dec_text) > 50 else dec_text
            msg += f"ID {note_id}: {display_text}\n\n"
            keyboard.append([InlineKeyboardButton(f"❌ Delete {note_id}", callback_data=f"delete_note_{note_id}")])
        except InvalidToken:
            msg += f"ID {note_id}: [ERROR decrypting]\n\n"
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

@owner_only
async def delete_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /deletenote <id>")
        return
    note_id = context.args[0]
    data = load_data()
    if note_id not in data["notes"]:
        await update.message.reply_text("❌ Note not found.")
        return
    del data["notes"][note_id]
    save_data(data)
    await update.message.reply_text(f"🗑️ Deleted note {note_id}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("delete_note_"):
        note_id = query.data.split("_")[-1]
        data = load_data()
        if note_id in data["notes"]:
            del data["notes"][note_id]
            save_data(data)
            await query.edit_message_text(f"🗑️ Note {note_id} deleted.")
        else:
            await query.edit_message_text("❌ Note not found.")

# --- Setup Application ---
application = Application.builder().token(BOT_TOKEN).build()

# Register handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("addkey", add_key))
application.add_handler(CommandHandler("getkey", get_key))
application.add_handler(CommandHandler("listkeys", list_keys))
application.add_handler(CommandHandler("deletekey", delete_key))
application.add_handler(CommandHandler("addnote", add_note))
application.add_handler(CommandHandler("getnotes", get_notes))
application.add_handler(CommandHandler("deletenote", delete_note))
application.add_handler(CallbackQueryHandler(button_handler))

# --- Global event loop reference ---
bot_loop = None
loop_lock = Lock()

# --- Application Startup ---
async def main():
    global bot_loop
    with loop_lock:
        bot_loop = asyncio.get_running_loop()
    await application.initialize()
    await application.bot.set_webhook(WEBHOOK_URL)
    await application.start()
    logger.info(f"✅ Bot started with webhook: {WEBHOOK_URL}")

def run_app():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
    loop.run_forever()

# Start in a daemon thread
Thread(target=run_app, daemon=True).start()

# --- Webhook Handler ---
@app.post("/webhook")
def webhook():
    try:
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, application.bot)
        
        with loop_lock:
            if bot_loop is None:
                logger.warning("Bot event loop not ready yet")
                return 'Bot not ready', 503
            
            # Schedule the update processing in the bot's event loop
            asyncio.run_coroutine_threadsafe(
                application.update_queue.put(update),
                bot_loop
            )
        
        return '', 200
    except Exception as e:
        logger.exception(f"⚠️ Webhook error: {e}")
        return '', 500

# --- Health Check ---
@app.route('/')
def health_check():
    return 'Bot is running', 200

# --- Start Flask app ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)