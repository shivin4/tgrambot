# Secure Telegram Bot for API Key Management

This bot allows secure storage and retrieval of encrypted API keys and notes, accessible only by the owner.

## Features
- Encrypted storage using Fernet encryption
- Owner-only access control
- Key management commands
- Note management with delete buttons
- Webhook-based deployment

## Deployment on Render

1. **Create a new Web Service** on Render
2. Set the following environment variables in the dashboard:
   - `BOT_TOKEN`: Your Telegram bot token
   - `FERNET_KEY`: Fernet encryption key (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
   - `OWNER_ID`: Your Telegram user ID
   - `WEBHOOK_URL`: Your Render app URL (e.g., `https://your-app-name.onrender.com`)
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `gunicorn main:app`
5. Deploy!

## Bot Commands
- `/start` - Show welcome message
- `/addkey <name> <value>` - Add encrypted API key
- `/getkey <name>` - Retrieve decrypted API key
- `/listkeys` - List all key names
- `/deletekey <name>` - Delete stored key
- `/addnote <text>` - Add encrypted note
- `/getnotes` - Retrieve all decrypted notes
- `/deletenote <id>` - Delete note by ID

## Security Notes
- All sensitive data is encrypted before storage
- Access restricted to owner via Telegram user ID
- Never logs sensitive information
- Uses industry-standard Fernet encryption