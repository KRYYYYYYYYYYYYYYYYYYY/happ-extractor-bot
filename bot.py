import os
import telebot
import requests
import re
import base64
import random
import time
from urllib.parse import unquote
from telebot import types

TOKEN = os.getenv('TELEGRAM_TOKEN')
SAYORI_KEY = os.getenv('SAYORI_KEY')

bot = telebot.TeleBot(TOKEN)
user_storage = {}

USER_AGENTS = [
    'v2rayNG/1.8.5 (com.v2ray.ang; build 100805; Android 13)',
    'NekoBox/1.3.1 (com.matsuri.nekobox; build 10301; Android 12)',
    'Happ/2.1.0 (com.happ.network; build 2100; iOS 16.1)'
]

CONVERTER_URL = "https://cs12d7a.4pda.ws/34581412/V2RAY+Converter+fix25fix.html"

def decrypt_via_api(happ_link):
    api_url = "https://api.sayori.cc/v1/decrypt"
    headers = {"Content-Type": "application/json", "x-api-key": SAYORI_KEY}
    payload = {"link": happ_link}
    try:
        res = requests.post(api_url, json=payload, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data.get("result") if data.get("success") else None
    except: pass
    return None

def extract_happ_anywhere(text_or_url):
    """Ищет happ:// в редиректах или в коде страницы (atlanta-subs и т.д.)"""
    # 1. Если это уже прямая ссылка
    if text_or_url.startswith('happ://'): return text_or_url
    
    # 2. Если happ зашит в параметрах (редирект)
    decoded_text = unquote(text_or_url)
    match = re.search(r'happ://crypt\d/[^\s"\'<>]+', decoded_text)
    if match: return match.group(0)
    
    # 3. Если это ссылка на страницу (заходим и ищем в коде)
    if text_or_url.startswith('http'):
        try:
            res = requests.get(text_or_url, headers={'User-Agent': random.choice(USER_AGENTS)}, timeout=10)
            match = re.search(r'happ://crypt\d/[^\s"\'<>]+', res.text)
            if match: return match.group(0)
        except: pass
    return None

@bot.message_handler(func=lambda m: True)
def handle_message(m):
    text = m.text.strip()
    happ_link = extract_happ_anywhere(text)
    
    if not happ_link:
        bot.reply_to(m, "❌ Ссылка не распознана. Пришлите прямую happ:// или ссылку на страницу.")
        return

    status_msg = bot.reply_to(m, "⏳ *Обработка...*", parse_mode='Markdown')
    
    # Пытаемся расшифровать
    decrypted = decrypt_via_api(happ_link)
    final_url = decrypted if decrypted else happ_link
    
    fetch_and_report(m.chat.id, final_url, status_msg.message_id)

def fetch_and_report(chat_id, sub_url, message_id):
    content = ""
    error_info = ""
    
    try:
        headers = {'User-Agent': random.choice(USER_AGENTS), 'Accept': '*/*'}
        # Небольшая пауза для обхода защиты
        time.sleep(1.5)
        res = requests.get(sub_url, headers=headers, timeout=15)
        
        if res.status_code == 200:
            raw = res.text.strip()
            # Пробуем Base64
            try:
                # Очистка от мусора перед декодом
                clean_raw = re.sub(r'[^a-zA-Z0-9+/=]', '', raw)
                pad = len(clean_raw) % 4
                if pad: clean_raw += '=' * (4 - pad)
                content = base64.b64decode(clean_raw).decode('utf-8', errors='ignore')
            except:
                content = raw
        else:
            error_info = f"Ошибка сервера: {res.status_code}"
    except Exception as e:
        error_info = f"Ошибка сети: {str(e)[:30]}"

    if not content and not error_info:
        error_info = "Контент пуст"

    if error_info:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔑 Попробовать API дешифровку", callback_data=f"force_api"))
        bot.edit_message_text(f"❌ {error_info}\n\nПопробуйте принудительную расшифровку:", chat_id, message_id, reply_markup=kb)
        return

    user_storage[chat_id] = content
    
    # Ищем только прямые ссылки
    links = [l.strip() for l in content.split('\n') if '://' in l and not l.strip().startswith('{')]
    
    report = (
        f"✅ **Готово!**\n\n"
        f"🔗 **Линк:** `{sub_url}`\n"
        f"📊 **Найдено ссылок:** `{len(links)}` шт.\n\n"
        f"⚠️ **P.S.** Если в подписке есть сложные JSON-конфигурации (автовыбор), бот может их пропустить. "
        f"В таком случае извлеките их вручную или используйте [этот конвертер]({CONVERTER_URL})."
    )
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📥 Скачать All Config", callback_data="get_all"))
    kb.add(types.InlineKeyboardButton("⚙️ Принудительное API", callback_data="force_api"))
    
    bot.edit_message_text(report, chat_id, message_id, parse_mode='Markdown', reply_markup=kb, disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: c.data == "force_api")
def force_api_callback(call):
    # Достаем последнюю ссылку из сообщения
    msg_text = call.message.text
    match = re.search(r'https?://[^\s]+', msg_text)
    if match:
        url = match.group(0).strip('`')
        bot.answer_callback_query(call.id, "Запрос к Sayori API...")
        decrypted = decrypt_via_api(url)
        if decrypted:
            fetch_and_report(call.message.chat.id, decrypted, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "API не дало результата.", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "Ссылка не найдена.")

@bot.callback_query_handler(func=lambda c: c.data == "get_all")
def get_all(call):
    content = user_storage.get(call.message.chat.id)
    if not content: return
    
    file_path = f"config_{call.message.chat.id}.txt"
    with open(file_path, "w", encoding="utf-8") as f: f.write(content)
    with open(file_path, "rb") as f:
        bot.send_document(call.message.chat.id, f, caption="Полное содержимое подписки")
    os.remove(file_path)
    bot.answer_callback_query(call.id)

bot.polling()
