import os
import sys
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    print("❌ TELEGRAM_TOKEN не задан")
    sys.exit(1)

MASHA_API_KEY = os.getenv("MASHA_API_KEY")
if not MASHA_API_KEY:
    print("❌ MASHA_API_KEY не задан")
    sys.exit(1)

MASHA_BASE_URL = "https://api.mashagpt.ru/v1"

DEBUG = os.getenv("DEBUG", "False").lower() == "true"
PORT = int(os.getenv("PORT", 8080))

# Для webhook нужен публичный HTTPS адрес (через ngrok или свой домен)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")   # например https://your-domain.com/webhook