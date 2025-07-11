import os
import json
import logging
from pathlib import Path
from threading import Thread
from queue import Queue
from functools import wraps
import asyncio
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ErrorHandler
)

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
FERNET_KEY = os.getenv('FERNET_KEY')
OWNER_ID = int(os.getenv('OWNER_ID'))
WEBHOOK_URL = os.getenv('WEBHOOK_URL') + '/webhook'

# Setup Fernet encryption
fernet = Fernet(FERNET_KEY.encode())

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Data file path
DATA_FILE = 'data.json'

# Initialize Flask app
app = Flask(__name__)

def owner_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("🚫 Unauthorized access. This incident will be reported.")
            logger.warning(f"Unauthorized access attempt by user {update.effective_user.id}")
            return
        return await func(update, context)
    return wrapper

def load_data():
    try:
        if Path(DATA_FILE).exists():
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading data: {e}")
    return {"keys": {}, "notes": {}, "next_note_id": 1}

def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        logger.error(f"Error saving data: {e}")

def encrypt_data(data: str) -> str:
    return fernet.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data: str) -> str:
    return fernet.decrypt(encrypted_data.encode()).decode()

@owner_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔐 Secure Key Manager Bot\n\n"
        "Available commands:\n"
        "/addkey <name> <value> - Add encrypted API key\n"
        "/getkey <name> - Retrieve decrypted API key\n"
        "/deletekey <name> - Delete stored key\n"
        "/listkeys - List all key names\n"
        "/addnote <text> - Add encrypted note\n"
        "/getnotes - Retrieve all decrypted notes\n"
        "/deletenote <id> - Delete note by ID"
    )

@owner_only
async def add_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addkey <name> <value>")
        return
    key_name = context.args[0]
    key_value = ' '.join(context.args[1:])
    data = load_data()
    encrypted_value = encrypt_data(key_value)
    data["keys"][key_name] = encrypted_value
    save_data(data)
    logger.info(f"Key '{key_name}' added/updated")
    await update.message.reply_text(f"✅ Key '{key_name}' stored successfully")

@owner_only
async def get_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /getkey <name>")
        return
    key_name = context.args[0]
    data = load_data()
    if key_name not in data["keys"]:
        await update.message.reply_text(f"🔍 Key '{key_name}' not found")
        return
    try:
        decrypted_value = decrypt_data(data["keys"][key_name])
        await update.message.reply_text(f"🔑 {key_name}: {decrypted_value}", parse_mode='MarkdownV2')
    except InvalidToken:
        await update.message.reply_text("⚠️ Error decrypting key. Invalid token.")
        logger.error(f"Decryption failed for key: {key_name}")

@owner_only
async def list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    keys = data["keys"].keys()
    if not keys:
        await update.message.reply_text("No keys stored")
        return
    key_list = "\n".join([f"• {key}" for key in keys])
    await update.message.reply_text(f"🔑 Stored Keys:\n{key_list}")

@owner_only
async def delete_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /deletekey <name>")
        return
    key_name = context.args[0]
    data = load_data()
    if key_name not in data["keys"]:
        await update.message.reply_text(f"🔍 Key '{key_name}' not found")
        return
    del data["keys"][key_name]
    save_data(data)
    logger.info(f"Key '{key_name}' deleted")
    await update.message.reply_text(f"🗑️ Key '{key_name}' deleted successfully")

@owner_only
async def add_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addnote <text>")
        return
    note_text = ' '.join(context.args)
    data = load_data()
    note_id = data["next_note_id"]
    encrypted_text = encrypt_data(note_text)
    data["notes"][str(note_id)] = encrypted_text
    data["next_note_id"] = note_id + 1
    save_data(data)
    logger.info(f"Note added with ID {note_id}")
    await update.message.reply_text(f"📝 Note added successfully (ID: {note_id})")

@owner_only
async def get_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    notes = data["notes"]
    if not notes:
        await update.message.reply_text("No notes stored")
        return
    keyboard = []
    message_text = "📝 Saved Notes:\n\n"
    for note_id, encrypted_text in notes.items():
        try:
            decrypted_text = decrypt_data(encrypted_text)
            message_text += f"ID {note_id}: {decrypted_text}\n\n"
            keyboard.append([InlineKeyboardButton(f"Delete Note {note_id}", callback_data=f"delete_note_{note_id}")])
        except InvalidToken:
            logger.error(f"Decryption failed for note ID: {note_id}")
            message_text += f"ID {note_id}: [Decryption Error]\n\n"
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message_text, reply_markup=reply_markup)

@owner_only
async def delete_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /deletenote <id>")
        return
    note_id = context.args[0]
    data = load_data()
    if note_id not in data["notes"]:
        await update.message.reply_text(f"🔍 Note ID '{note_id}' not found")
        return
    del data["notes"][note_id]
    save_data(data)
    logger.info(f"Note {note_id} deleted")
    await update.message.reply_text(f"🗑️ Note {note_id} deleted successfully")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("delete_note_"):
        note_id = query.data.split("_")[-1]
        data = load_data()
        if note_id in data["notes"]:
            del data["notes"][note_id]
            save_data(data)
            logger.info(f"Note {note_id} deleted via inline button")
            await query.edit_message_text(f"🗑️ Note {note_id} deleted successfully")
        else:
            await query.edit_message_text(f"🔍 Note ID '{note_id}' not found")

async def handle_error(update, context):
    logger.exception(f"Exception while handling update: {context.error}")

application = Application.builder()\
    .token(BOT_TOKEN)\
    .con_pool_size(10)\
    .get_updates_http_version("1.1")\
    .concurrent_updates(True)\
    .build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("addkey", add_key))
application.add_handler(CommandHandler("getkey", get_key))
application.add_handler(CommandHandler("listkeys", list_keys))
application.add_handler(CommandHandler("deletekey", delete_key))
application.add_handler(CommandHandler("addnote", add_note))
application.add_handler(CommandHandler("getnotes", get_notes))
application.add_handler(CommandHandler("deletenote", delete_note))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_error_handler(ErrorHandler(handle_error))

update_queue = Queue()
application.update_queue = update_queue

async def run_bot():
    await application.initialize()
    await application.bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook set to: {WEBHOOK_URL}")

def run_bot_sync():
    asyncio.run(run_bot())

Thread(target=run_bot_sync, daemon=True).start()

@app.route("/health")
def health_check():
    return "OK", 200

@app.post('/webhook')
def webhook():
    try:
        json_data = request.get_json()
        update = Update.de_json(json_data, application.bot)
        if update.message:
            user = update.message.from_user
            logger.info(f"Received message from user ID: {user.id} ({user.first_name})")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def process():
            if not application._initialized:
                await application.initialize()
            await application.process_update(update)

        loop.run_until_complete(process())
        loop.close()

        return '', 200

    except Exception as e:
        logger.exception(f"Webhook error: {e}")
        return '', 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
