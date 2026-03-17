import os
import telebot
import requests
import re
import base64
import random
import time
import json
from urllib.parse import unquote
from telebot import types

TOKEN = os.getenv('TELEGRAM_TOKEN')
SAYORI_KEY = os.getenv('SAYORI_KEY')

bot = telebot.TeleBot(TOKEN)
user_storage = {}

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'v2rayNG/1.8.5 (com.v2ray.ang; build 100805; Android 13)',
    'NekoBox/1.3.1 (com.matsuri.nekobox; build 10301; Android 12)'
]

CONVERTER_URL = "https://cs12d7a.4pda.ws/34581412/V2RAY+Converter+fix25fix.html"

def decrypt_via_api(happ_link):
    api_url = "https://api.sayori.cc/v1/decrypt"
    headers = {"Content-Type": "application/json", "x-api-key": SAYORI_KEY}
    payload = {"link": happ_link}
    try:
        res = requests.post(api_url, json=payload, headers=headers, timeout=15)
        if res.status_code == 200:
            d = res.json()
            return d.get("result") if d.get("success") else None
    except: pass
    return None

def extract_from_atlanta_meta(html_text):
    """Извлекает скрытую ссылку из data-panel (Атланта)"""
    try:
        match = re.search(r'data-panel="([^"]+)"', html_text)
        if match:
            decoded = base64.b64decode(match.group(1)).decode('utf-8')
            data = json.loads(decoded)
            return data.get("response", {}).get("subscriptionUrl")
    except: pass
    return None

def extract_happ_anywhere(text_or_url):
    """Ищет happ:// или вытягивает URL из метаданных страницы"""
    decoded_raw = unquote(text_or_url)
    match = re.search(r'happ://crypt\d/[^\s"\'<>]+', decoded_raw)
    if match: return match.group(0)
    
    if text_or_url.startswith('http'):
        try:
            time.sleep(random.uniform(1.0, 2.0))
            h = {'User-Agent': random.choice(USER_AGENTS)}
            r = requests.get(text_or_url, headers=h, timeout=10)
            
            # Проверка на Атланту
            atlanta_sub = extract_from_atlanta_meta(r.text)
            if atlanta_sub: return atlanta_sub
            
            # Поиск happ:// в коде страницы
            match = re.search(r'happ://crypt\d/[^\s"\'<>]+', r.text)
            if match: return match.group(0)
        except: pass
    return None

@bot.message_handler(func=lambda m: True)
def handle_message(m):
    text = m.text.strip()
    target_link = extract_happ_anywhere(text)
    
    if not target_link:
        # Если это просто прямая ссылка на raw github или файл, пробуем её
        if text.startswith('http'): target_link = text
        else:
            bot.reply_to(m, "❌ Ссылка не распознана.")
            return

    status_msg = bot.reply_to(m, "⏳ *Обработка...*", parse_mode='Markdown')
    
    if target_link.startswith('happ://'):
        decrypted = decrypt_via_api(target_link)
        final_url = decrypted if decrypted else target_link
    else:
        final_url = target_link
    
    fetch_and_report(m.chat.id, final_url, status_msg.message_id)

def fetch_and_report(chat_id, sub_url, message_id):
    content = ""
    error_code = None
    
    try:
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept-Encoding': 'gzip, deflate',  # Явно говорим, что понимаем сжатие
        }
        # Делаем запрос
        res = requests.get(sub_url, headers=headers, timeout=15)
        error_code = res.status_code
        
        if res.status_code == 200:
            # res.text может тупить со сжатием, используем автоматический декодер
            res.encoding = res.apparent_encoding
            raw = res.text.strip()
            
            # Если в начале всё равно "мусор", пробуем принудительно прочитать через content
            if len(raw) > 0 and (ord(raw[0]) < 32 and raw[0] not in '\n\r\t'):
                raw = res.content.decode('utf-8', errors='ignore').strip()

            # Проверка на Base64
            try:
                clean_raw = re.sub(r'[^a-zA-Z0-9+/=]', '', raw)
                if len(clean_raw) > 30:
                    decoded = base64.b64decode(clean_raw).decode('utf-8', errors='ignore')
                    content = decoded if '://' in decoded or '{' in decoded else raw
                else: content = raw
            except: content = raw
    except Exception as e: error_code = str(e)[:20]

    if not content or (isinstance(error_code, int) and error_code >= 400):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔑 API принудительно", callback_data="force_api"))
        bot.edit_message_text(f"❌ Ошибка: {error_code}", chat_id, message_id, reply_markup=kb)
        return

    user_storage[chat_id] = content
    
    # Регулярка для поиска прокси-ссылок
    links = re.findall(r'(vless|vmess|ss|trojan|shadowsocks|tuic|hysteria2?)://[^\s"\'<>]+', content)
    has_json = '"outbounds"' in content or ('{' in content and '"' in content)
    
    if links:
        status_text = "ℹ️ Текстовая подписка" + (" (+ JSON)" if has_json else "")
    elif has_json:
        status_text = "✅ JSON Конфигурация"
    else:
        status_text = "📄 Текстовый файл"

    report = (
        f"✅ **Готово!**\n\n"
        f"🌐 **Тип:** `{status_text}`\n"
        f"🔗 **Найдено ссылок:** `{len(links)}` шт.\n\n"
        f"🔗 **Линк:**\n`{sub_url}`\n\n"
        f"⚠️ **P.S.** Используйте [конвертер]({CONVERTER_URL}), если формат не подошел."
    )
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📥 Скачать файл", callback_data="get_all"))
    kb.add(types.InlineKeyboardButton("🔄 Через API", callback_data="force_api"))
    
    bot.edit_message_text(report, chat_id, message_id, parse_mode='Markdown', reply_markup=kb, disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: c.data == "get_all")
def get_all(call):
    content = user_storage.get(call.message.chat.id)
    if not content: return
    ext = "json" if '"' in content and '{' in content else "txt"
    file_path = f"config_{call.message.chat.id}.{ext}"
    with open(file_path, "w", encoding="utf-8") as f: f.write(content)
    with open(file_path, "rb") as f:
        bot.send_document(call.message.chat.id, f, caption="Файл подписки")
    os.remove(file_path)

bot.polling()
