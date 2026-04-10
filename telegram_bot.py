import asyncio
import io
import json
import logging
import time
from typing import List, Tuple

import aiohttp
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, PreCheckoutQueryHandler,
    CallbackQueryHandler
)
from telegram.constants import ChatAction
from PIL import Image

from config import TELEGRAM_TOKEN, MASHA_API_KEY, MASHA_BASE_URL, WEBHOOK_URL, PORT
from database import (
    init_db, save_message, get_history, clear_history,
    get_user_balance, add_balance, deduct_balance,
    get_weekly_image_count, increment_weekly_image_count
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------- Константы -------------------
PAID_IMAGE_PRICE = 2

# Состояния
MAIN_MENU, TEXT_GEN, IMAGE_GEN, VIDEO_GEN, EDIT_GEN, AUDIO_GEN, AVATAR_GEN, DIALOG, AWAIT_PROMPT = range(9)
AWAIT_FACE_SWAP_TARGET = 9
AWAIT_FACE_SWAP_SOURCE = 10
AWAIT_IMAGE_FOR_EDIT = 11
AWAIT_PROMPT_FOR_EDIT = 12
AWAIT_IMAGE_FOR_AVATAR = 13
AWAIT_AUDIO_FOR_AVATAR = 14
AWAIT_VIDEO_FOR_ANIMATE = 15
AWAIT_IMAGE_FOR_ANIMATE = 16

# Цены моделей (такие же, как у вас, оставлены без изменений)
MODEL_PRICES = {
    "gpt-5-nano": 0, "gpt-5-mini": 0, "gpt-4o-mini": 0, "gpt-4.1-nano": 0,
    "deepseek-chat": 0, "deepseek-reasoner": 0, "grok-4-1-fast-reasoning": 0,
    "grok-4-1-fast-non-reasoning": 0, "grok-3-mini": 0, "gemini-2.0-flash": 0,
    "gemini-2.0-flash-lite": 0, "gemini-2.5-flash-lite": 0,
    "gpt-5.4": 15, "gpt-5.1": 10, "gpt-5": 10, "gpt-4.1": 8, "gpt-4o": 10,
    "o3-mini": 4.4, "o3": 40, "o1": 60, "claude-haiku-4-5": 5, "claude-sonnet-4-5": 15,
    "claude-opus-4-5": 25, "gemini-3-flash": 3, "gemini-2.5-pro": 10, "gemini-3-pro": 16,
    "gemini-3-pro-image": 12,
    "z-image": 0, "grok-imagine-text-to-image": 0, "codeplugtech-face-swap": 0,
    "cdlingram-face-swap": 0, "recraft-crisp-upscale": 0, "recraft-remove-background": 0,
    "topaz-image-upscale": 0, "flux-2": 0, "qwen-edit-multiangle": 0, "nano-banana-2": 0,
    "nano-banana-pro": 0, "midjourney": 0, "gpt-image-1-5-text-to-image": 0,
    "gpt-image-1-5-image-to-image": 0, "ideogram-v3-reframe": 0,
    "grok-imagine-text-to-video": 1, "wan-2-6-text-to-video": 3, "wan-2-5-text-to-video": 3,
    "wan-2-6-image-to-video": 3, "wan-2-6-video-to-video": 3, "wan-2-5-image-to-video": 3,
    "sora-2-text-to-video": 3, "sora-2-image-to-video": 3, "veo-3-1": 5,
    "kling-2-6-text-to-video": 6, "kling-v2-5-turbo-pro": 6, "kling-2-6-image-to-video": 6,
    "kling-v2-5-turbo-image-to-video-pro": 5, "sora-2-pro-text-to-video": 5,
    "sora-2-pro-image-to-video": 5, "sora-2-pro-storyboard": 7, "hailuo-2-3": 4,
    "minimax-video-01-director": 4, "seedance-v1-pro-fast": 30, "kling-2-6-motion-control": 6,
    "elevenlabs-tts-multilingual-v2": 0, "elevenlabs-tts-turbo-2-5": 0,
    "elevenlabs-text-to-dialogue-v3": 0, "elevenlabs-sound-effect-v2": 5,
    "kling-v1-avatar-pro": 16, "kling-v1-avatar-standard": 8, "infinitalk-from-audio": 1.1,
    "wan-2-2-animate-move": 0.75, "wan-2-2-animate-replace": 0.75,
}

MODEL_INPUT_TYPE = {
    "codeplugtech-face-swap": ("image", "image"),
    "cdlingram-face-swap": ("image", "image"),
    "gpt-image-1-5-image-to-image": ("image", "text"),
    "qwen-edit-multiangle": ("image", "text"),
    "kling-v1-avatar-pro": ("image", "audio"),
    "kling-v1-avatar-standard": ("image", "audio"),
    "infinitalk-from-audio": ("image", "audio"),
    "wan-2-2-animate-move": ("video", "image"),
    "wan-2-2-animate-replace": ("video", "image"),
}

# ------------------- Клавиатуры (сокращённо, полные версии у вас уже есть) -------------------
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("✏️ Генерация текста")],
        [KeyboardButton("🖼 Генерация изображения")],
        [KeyboardButton("🎬 Генерация видео")],
        [KeyboardButton("✨ Обработка изображений")],
        [KeyboardButton("🎵 Аудио (озвучка, эффекты)")],
        [KeyboardButton("🤖 Аватар / анимация")],
        [KeyboardButton("🧹 Сбросить диалог")],
        [KeyboardButton("💰 Мой баланс")],
        [KeyboardButton("⭐ Пополнить промты")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("🔙 Главное меню")]], resize_keyboard=True, one_time_keyboard=True)

# Остальные клавиатуры (текстовые, видео и т.д.) полностью скопируйте из вашего предыдущего рабочего кода.
# Чтобы не раздувать ответ, я приведу только одну для примера. Вы можете вставить свои функции.
def get_text_models_keyboard():
    models = [("gpt-4o-mini", "GPT-4o mini", 0), ("gpt-5-mini", "GPT-5 mini", 0)]  # и так далее
    keyboard = []
    for model_id, label, price in models:
        btn_text = f"{label} (бесплатно)" if price == 0 else f"{label} ({price} промтов)"
        keyboard.append([KeyboardButton(btn_text)])
    keyboard.append([KeyboardButton("🔙 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

# Аналогично реализуйте get_image_models_keyboard, get_video_models_keyboard и т.д.
# (можно взять из предыдущего сообщения, где был полный код)

# ------------------- Вспомогательные функции -------------------
async def compress_image(image_bytes: bytes, max_size: int = 1280, quality: int = 85) -> bytes:
    # ... (та же функция, что и раньше)
    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb = Image.new('RGB', img.size, (255, 255, 255))
            rgb.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = rgb
        ratio = max_size / max(img.size)
        if ratio < 1:
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        return output.getvalue()

async def send_long_message(update: Update, text: str):
    if not text:
        return
    for i in range(0, len(text), 4096):
        await update.message.reply_text(text[i:i+4096])

async def send_action_loop(update: Update, action: ChatAction, stop_event: asyncio.Event):
    while not stop_event.is_set():
        await update.message.reply_chat_action(action)
        try:
            await asyncio.sleep(4)
        except asyncio.CancelledError:
            break

# ------------------- API MashaGPT с retry -------------------
async def create_task(model: str, payload: dict, retries=3):
    url = f"{MASHA_BASE_URL}/tasks/{model}"
    headers = {"Content-Type": "application/json", "x-api-key": MASHA_API_KEY}
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    return data.get("id")
        except Exception as e:
            logger.error(f"Ошибка создания задачи {model}: {e}")
            if attempt == retries - 1:
                return None
            await asyncio.sleep(2)
    return None

async def get_task_status(task_id: str):
    url = f"{MASHA_BASE_URL}/tasks/{task_id}"
    headers = {"x-api-key": MASHA_API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logger.error(f"Статус {resp.status}, тело: {text[:200]}")
                    return text
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    logger.error(f"Ответ не JSON: {text[:200]}")
                    return text
    except Exception as e:
        logger.error(f"Ошибка получения статуса {task_id}: {e}")
        return None

async def wait_for_task(task_id: str, timeout=300):
    start = asyncio.get_running_loop().time()
    while True:
        data = await get_task_status(task_id)
        if not data:
            await asyncio.sleep(3)
            if asyncio.get_running_loop().time() - start > timeout:
                raise Exception("Таймаут: нет ответа от API")
            continue
        if isinstance(data, str):
            if "429" in data or "500" in data:
                await asyncio.sleep(5)
                continue
            raise Exception(f"Ошибка API: {data[:200]}")
        status = data.get("status")
        if status == "COMPLETED":
            return data
        elif status == "FAILED":
            raise Exception(f"Задача провалилась: {data.get('errorMessage')}")
        await asyncio.sleep(2)
        if asyncio.get_running_loop().time() - start > timeout:
            raise Exception(f"Таймаут {timeout} секунд")

async def masha_text_generate(prompt: str, history: List[Tuple[str, str]], model: str) -> str:
    messages = []
    for role, content in history[-5:]:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": prompt})

    url = f"{MASHA_BASE_URL}/chat/completions"
    headers = {"Content-Type": "application/json", "x-api-key": MASHA_API_KEY}
    payload = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": 1024,
        "temperature": 1.0
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise Exception(f"Masha error {resp.status}: {error_text}")
            data = await resp.json()
            content = None
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0].get("message", {}).get("content")
            if not content:
                content = data.get("result") or data.get("output")
            if not content:
                return ""
            return content

async def masha_media_generate(model: str, payload: dict):
    task_id = await create_task(model, payload)
    if not task_id:
        raise Exception("Не удалось создать задачу")
    result = await wait_for_task(task_id)
    if not result:
        raise Exception("Не удалось получить результат")
    outputs = result.get("output", [])
    if not outputs:
        raise Exception("Нет output в ответе")
    if isinstance(outputs[0], dict):
        media_url = outputs[0].get("url")
    elif isinstance(outputs[0], str):
        media_url = outputs[0]
    else:
        raise Exception(f"Неизвестный тип output: {type(outputs[0])}")
    if not media_url:
        raise Exception("Нет URL в ответе")
    async with aiohttp.ClientSession() as session:
        async with session.get(media_url) as resp:
            if resp.status != 200:
                raise Exception(f"Ошибка скачивания файла: {resp.status}")
            file_bytes = await resp.read()
    return file_bytes, media_url

def build_payload(model: str, prompt: str = None, image_url: str = None) -> dict:
    # Полная версия из вашего предыдущего кода (я не буду повторять 200 строк, вставьте свою)
    # Убедитесь, что она есть.
    pass  # замените на вашу реализацию

# ------------------- Обработчики команд -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await init_db()
    user_id = update.effective_user.id
    await update.message.reply_text(
        "🤖 *Привет! Я бот с поддержью ИИ (MashaGPT).*\n\n"
        "✏️ Текст – бесплатно, без лимита\n"
        "🖼 Изображения – бесплатно, 5 в неделю\n"
        "🎬 Видео, 🎵 Аудио, ✨ Обработка – платно (токены)\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
    return MAIN_MENU

async def clear_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await clear_history(update.effective_user.id)
    await update.message.reply_text("История очищена.", reply_markup=get_main_keyboard())
    return MAIN_MENU

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = await get_user_balance(user_id)
    img_used = await get_weekly_image_count(user_id)
    img_left = max(0, 5 - img_used)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⭐ Пополнить промты", callback_data="topup")]])
    await update.message.reply_text(
        f"💰 Ваш баланс: {bal} промтов\n"
        f"🖼 Бесплатные изображения: {img_used}/5 использовано на этой неделе\n"
        f"   Осталось бесплатных: {img_left}\n"
        f"💎 Платное изображение (после лимита): {PAID_IMAGE_PRICE} промтов",
        reply_markup=keyboard
    )

async def send_topup_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int = None):
    if chat_id is None:
        chat_id = update.effective_chat.id
    title = "Пополнение баланса"
    description = "100 звёзд = 100 промтов"
    payload = "topup_100"
    currency = "XTR"
    prices = [LabeledPrice(label="100 звёзд", amount=100)]

    await context.bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",
        currency=currency,
        prices=prices,
        start_parameter="topup",
        need_name=False,
        need_phone_number=False,
        need_email=False,
        need_shipping_address=False,
        is_flexible=False
    )

# ------------------- Обработчик главного меню -------------------
async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "✏️ Генерация текста":
        context.user_data.clear()
        await update.message.reply_text("Выберите модель текста:", reply_markup=get_text_models_keyboard())
        return TEXT_GEN
    elif text == "🖼 Генерация изображения":
        context.user_data.clear()
        await update.message.reply_text("Выберите модель изображения:", reply_markup=get_image_models_keyboard())
        return IMAGE_GEN
    elif text == "🎬 Генерация видео":
        context.user_data.clear()
        await update.message.reply_text("Выберите модель видео:", reply_markup=get_video_models_keyboard())
        return VIDEO_GEN
    elif text == "✨ Обработка изображений":
        context.user_data.clear()
        await update.message.reply_text("Выберите модель обработки:", reply_markup=get_edit_models_keyboard())
        return EDIT_GEN
    elif text == "🎵 Аудио (озвучка, эффекты)":
        context.user_data.clear()
        await update.message.reply_text("Выберите модель аудио:", reply_markup=get_audio_models_keyboard())
        return AUDIO_GEN
    elif text == "🤖 Аватар / анимация":
        context.user_data.clear()
        await update.message.reply_text("Выберите модель аватара:", reply_markup=get_avatar_models_keyboard())
        return AVATAR_GEN
    elif text == "🧹 Сбросить диалог":
        return await clear_dialog(update, context)
    elif text == "💰 Мой баланс":
        await show_balance(update, context)
        return MAIN_MENU
    elif text == "⭐ Пополнить промты":
        await send_topup_invoice(update, context)
        return MAIN_MENU
    elif text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU
    else:
        return await start_dialog(update, context, text)

# ------------------- Выбор модели (сокращённо) -------------------
async def handle_model_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str) -> int:
    text = update.message.text
    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    # Здесь должен быть полный список моделей для каждой категории (как в вашем коде)
    # Для краткости оставлю заглушку. Вставьте свои списки models.
    models = []  # замените на реальные
    if category == "text":
        models = [("gpt-4o-mini", "GPT-4o mini", 0)]  # и все остальные
    elif category == "image":
        models = [("z-image", "Z-Image", 0)]
    elif category == "video":
        models = [("grok-imagine-text-to-video", "Grok Imagine Video", 1)]

    for model_id, label, price in models:
        btn_text = f"{label} (бесплатно)" if price == 0 else f"{label} ({price} промтов)"
        if text.strip() == btn_text.strip():
            context.user_data['selected_model'] = model_id
            context.user_data['model_price'] = price
            context.user_data['selected_category'] = category
            context.user_data['media_category'] = category
            input_type = MODEL_INPUT_TYPE.get(model_id, ("text",))

            if input_type == ("text",):
                if category == "text":
                    await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите запрос:", reply_markup=get_cancel_keyboard())
                    return DIALOG
                else:
                    await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите запрос:", reply_markup=get_cancel_keyboard())
                    return AWAIT_PROMPT
            # ... остальные типы (face swap, edit и т.д.) аналогично вашему коду
            else:
                await update.message.reply_text(f"Выбрана модель: {label}\n\nВведите запрос:", reply_markup=get_cancel_keyboard())
                return AWAIT_PROMPT

    await update.message.reply_text("Пожалуйста, выберите модель из списка.")
    return MAIN_MENU

# Обработчики для каждой категории (вызывают handle_model_selection)
async def handle_text_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await handle_model_selection(update, context, "text")

async def handle_image_selection(update, context):
    return await handle_model_selection(update, context, "image")

# ... и так для video, edit, audio, avatar

# ------------------- Диалог (генерация текста) -------------------
async def start_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE, user_message: str = None) -> int:
    user_id = update.effective_user.id
    if user_message is None:
        user_message = update.message.text
    if user_message == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    model = context.user_data.get('selected_model', 'gpt-4o-mini')
    price = MODEL_PRICES.get(model, 0)

    await save_message(user_id, "user", user_message)
    history = await get_history(user_id, limit=10)

    if price > 0:
        balance = await get_user_balance(user_id)
        if balance < price:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
        if not await deduct_balance(user_id, price):
            await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, ChatAction.TYPING, stop_action))
    try:
        answer = await masha_text_generate(user_message, history, model)
    finally:
        stop_action.set()
        await action_task

    if answer:
        await send_long_message(update, answer)
        await save_message(user_id, "assistant", answer)
    else:
        await update.message.reply_text("❌ Пустой ответ от сервера.")
        if price > 0:
            await add_balance(user_id, price)
    return DIALOG

# ------------------- Обработка медиа (изображения, видео) -------------------
async def handle_media_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    model = context.user_data.get('selected_model')
    price = context.user_data.get('model_price', 0)
    category = context.user_data.get('media_category')
    text = update.message.text

    # Защита от повторного нажатия кнопки модели
    if text.endswith("(бесплатно)") or ("(" in text and "промтов)" in text):
        await update.message.reply_text(
            "📝 Пожалуйста, введите текстовый запрос для генерации.\nПример: «кот в космосе»",
            reply_markup=get_cancel_keyboard()
        )
        return AWAIT_PROMPT

    if text == "🔙 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        return MAIN_MENU

    if not category or not model:
        await update.message.reply_text("Ошибка: не выбрана категория или модель.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    if not text or text.isspace():
        await update.message.reply_text("Пожалуйста, введите текст запроса.", reply_markup=get_cancel_keyboard())
        return AWAIT_PROMPT

    payload = build_payload(model, prompt=text)
    if not payload:
        await update.message.reply_text(f"❌ Не удалось сформировать запрос для модели {model}.")
        return MAIN_MENU

    # Обработка платности для изображений
    if category == "image" and price == 0:
        used = await get_weekly_image_count(user_id)
        if used >= 5:
            balance = await get_user_balance(user_id)
            if balance >= PAID_IMAGE_PRICE:
                if not await deduct_balance(user_id, PAID_IMAGE_PRICE):
                    await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
                    return MAIN_MENU
                await update.message.reply_text(f"⚠️ Бесплатный лимит исчерпан. Списано {PAID_IMAGE_PRICE} промтов.")
                context.user_data['paid_image'] = True
            else:
                await update.message.reply_text("❌ Бесплатный лимит исчерпан. Не хватает промтов.", reply_markup=get_main_keyboard())
                return MAIN_MENU
        else:
            context.user_data['paid_image'] = False

    if price > 0 and category != "image":
        balance = await get_user_balance(user_id)
        if balance < price:
            await update.message.reply_text(f"❌ Недостаточно промтов. Нужно: {price}.", reply_markup=get_main_keyboard())
            return MAIN_MENU
        if not await deduct_balance(user_id, price):
            await update.message.reply_text("❌ Ошибка списания.", reply_markup=get_main_keyboard())
            return MAIN_MENU

    # Выбор действия
    action = ChatAction.UPLOAD_PHOTO if category in ("image", "edit") else ChatAction.UPLOAD_VIDEO
    stop_action = asyncio.Event()
    action_task = asyncio.create_task(send_action_loop(update, action, stop_action))
    try:
        result_bytes, media_url = await masha_media_generate(model, payload)
    except Exception as e:
        logger.exception("Ошибка генерации медиа")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        # Возврат токенов
        if category == "image" and price == 0 and context.user_data.get('paid_image'):
            await add_balance(user_id, PAID_IMAGE_PRICE)
        elif price > 0:
            await add_balance(user_id, price)
        return MAIN_MENU
    finally:
        stop_action.set()
        await action_task

    if result_bytes:
        if category == "image":
            compressed = await compress_image(result_bytes)
            await update.message.reply_photo(photo=io.BytesIO(compressed), caption="🖼 Результат (сжатое)")
            await update.message.reply_text(f"📥 Оригинал: {media_url}")
            if price == 0 and not context.user_data.get('paid_image'):
                await increment_weekly_image_count(user_id)
        elif category == "video":
            await update.message.reply_video(video=io.BytesIO(result_bytes), caption="🎬 Результат")
        # ... остальные типы
        await save_message(user_id, "user", f"{category} запрос: {text}")
        await save_message(user_id, "assistant", "Контент сгенерирован")
    else:
        await update.message.reply_text("❌ Не удалось получить результат.")
        if category == "image" and price == 0 and context.user_data.get('paid_image'):
            await add_balance(user_id, PAID_IMAGE_PRICE)
        elif price > 0:
            await add_balance(user_id, price)

    await update.message.reply_text("Что дальше?", reply_markup=get_main_keyboard())
    return MAIN_MENU

# ------------------- Платежи -------------------
async def pre_checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload == "topup_100":
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Неизвестный товар")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    amount = update.message.successful_payment.total_amount
    await add_balance(user_id, amount)
    await update.message.reply_text(
        f"✅ Баланс пополнен на {amount} промтов! Теперь у вас {await get_user_balance(user_id)} промтов.",
        reply_markup=get_main_keyboard()
    )

async def inline_topup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "topup":
        await send_topup_invoice(update, context, chat_id=query.message.chat_id)

# ------------------- Глобальный обработчик ошибок -------------------
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if update and update.effective_message:
        await update.effective_message.reply_text("⚠️ Произошла внутренняя ошибка. Попробуйте позже.")

# ------------------- Запуск через webhook (рекомендуется) -------------------
async def main_async():
    await init_db()
    if not TELEGRAM_TOKEN or not MASHA_API_KEY:
        logger.error("Не заданы TELEGRAM_TOKEN или MASHA_API_KEY")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # ConversationHandler (полный, со всеми состояниями – вставьте свой)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu)],
            TEXT_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_selection)],
            IMAGE_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_image_selection)],
            # ... добавьте остальные состояния
            DIALOG: [MessageHandler(filters.TEXT & ~filters.COMMAND, start_dialog)],
            AWAIT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_media_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("clear", clear_dialog))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(CallbackQueryHandler(inline_topup_callback, pattern="topup"))
    app.add_error_handler(error_handler)

    if WEBHOOK_URL:
        # Режим webhook
        await app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        logger.info(f"Webhook установлен на {WEBHOOK_URL}/webhook")
        # Запускаем aiohttp сервер
        from aiohttp import web
        async def health(request):
            return web.Response(text="OK")
        app_web = web.Application()
        app_web.router.add_post("/webhook", app.process_update)
        app_web.router.add_get("/health", health)
        runner = web.AppRunner(app_web)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", PORT)
        await site.start()
        logger.info(f"Бот запущен на порту {PORT} в режиме webhook")
        await asyncio.Event().wait()
    else:
        # Режим polling (для локальной отладки)
        logger.info("Бот запущен в режиме polling")
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()