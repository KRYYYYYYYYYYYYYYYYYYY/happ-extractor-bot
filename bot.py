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

# Более реалистичные заголовки для обхода 403/500 ошибок
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
]

CONVERTER_URL = "https://cs12d7a.4pda.ws/34581412/V2RAY+Converter+fix25fix.html"

def decrypt_via_api(happ_link):
    api_url = "https://api.sayori.cc/v1/decrypt"
    headers = {"Content-Type": "application/json", "x-api-key": SAYORI_KEY}
    payload = {"link": happ_link.strip()}
    
    for attempt in range(3):
        try:
            res = requests.post(api_url, json=payload, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return data.get("result")
            elif res.status_code in [500, 502, 503, 504]:
                time.sleep(3 * (attempt + 1))
                continue
        except Exception as e:
            print(f"API Error: {e}")
            time.sleep(1)
    return None

def extract_from_atlanta_meta(html_text):
    try:
        match = re.search(r'data-panel="([^"]+)"', html_text)
        if match:
            decoded = base64.b64decode(match.group(1)).decode('utf-8')
            data = json.loads(decoded)
            return data.get("response", {}).get("subscriptionUrl")
    except: pass
    return None

def extract_happ_anywhere(text_or_url):
    decoded_raw = unquote(text_or_url)
    match = re.search(r'happ://crypt\d/[^\s"\'<>]+', decoded_raw)
    if match: return match.group(0)
    
    if text_or_url.startswith('http'):
        try:
            time.sleep(random.uniform(0.5, 1.0))
            h = {'User-Agent': random.choice(USER_AGENTS)}
            r = requests.get(text_or_url, headers=h, timeout=10, allow_redirects=True)
            
            # Проверяем не только тело, но и мета-данные Атланты
            atlanta_sub = extract_from_atlanta_meta(r.text)
            if atlanta_sub: return atlanta_sub
            
            match = re.search(r'happ://crypt\d/[^\s"\'<>]+', r.text)
            if match: return match.group(0)
        except: pass
    return None

@bot.message_handler(func=lambda m: True)
def handle_message(m):
    text = m.text.strip()
    # Игнорируем команды
    if text.startswith('/'): return

    target_link = extract_happ_anywhere(text)
    
    if not target_link:
        if text.startswith('http'): target_link = text
        else:
            bot.reply_to(m, "❌ Ссылка не распознана.")
            return

    status_msg = bot.reply_to(m, "⏳ *Расшифровка и загрузка...*", parse_mode='Markdown')
    
    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: requests не умеет happ://
    if target_link.startswith('happ://'):
        decrypted = decrypt_via_api(target_link)
        if not decrypted:
            bot.edit_message_text("❌ Ошибка API: Не удалось расшифровать happ-ссылку (возможно, она протухла).", m.chat.id, status_msg.message_id)
            return
        final_url = decrypted
    else:
        final_url = target_link
    
    fetch_and_report(m.chat.id, final_url, status_msg.message_id)

def fetch_and_report(chat_id, sub_url, message_id):
    content = ""
    error_code = None
    
    try:
        time.sleep(random.uniform(1.0, 2.0))
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': '*/*',
            'Accept-Language': 'ru-RU,ru;q=0.9',
            'Referer': 'https://atlanta-subs.ru/', # Важно для обхода проверок
            'Connection': 'keep-alive'
        }
        
        res = requests.get(sub_url, headers=headers, timeout=20, verify=True)
        error_code = res.status_code
        
        if res.status_code == 200:
            content = res.text.strip()
            if len(content) < 5:
                error_code = "Empty Content"
                content = ""
    except Exception as e:
        error_code = f"Exception: {type(e).__name__}"

    if not content:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Повторить", callback_data="retry_last"))
        bot.edit_message_text(f"❌ Ошибка загрузки (Код: {error_code})\n\n"
                              f"Сервер отклонил запрос. Попробуйте снова через 10 секунд.", 
                              chat_id, message_id, reply_markup=kb)
        return

    # Декодирование Base64 если нужно
    final_data = content
    try:
        if "://" not in content[:50] and "{" not in content[:20]:
            decoded = base64.b64decode(content).decode('utf-8', errors='ignore')
            if "://" in decoded or "{" in decoded:
                final_data = decoded
    except: pass

    user_storage[chat_id] = final_data
    links = re.findall(r'(?:vless|vmess|ss|trojan|shadowsocks|tuic|hysteria2?)://[^\r\n"\'<>#]+', final_data)
    
    is_json = '"outbounds"' in final_data or '"nodes"' in final_data or final_data.startswith('{')
    status_text = "✅ JSON Конфиг" if is_json else ("ℹ️ Текстовая подписка" if links else "📄 Текст/Base64")

    report = (
        f"✅ **Готово!**\n\n"
        f"🌐 **Тип:** `{status_text}`\n"
        f"🔗 **Найдено узлов:** `{len(links)}` шт.\n\n"
        f"🔗 **Источник:**\n`{sub_url[:50]}...`\n\n"
        f"⚠️ Используйте [конвертер]({CONVERTER_URL})."
    )
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📥 Скачать файл", callback_data="get_all"))
    
    bot.edit_message_text(report, chat_id, message_id, parse_mode='Markdown', 
                          reply_markup=kb, disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: True)
def callback_handler(call):
    if call.data == "get_all":
        content = user_storage.get(call.message.chat.id)
        if not content:
            bot.answer_callback_query(call.id, "Данные не найдены, отправьте ссылку заново.")
            return
        
        ext = "json" if '"' in content and '{' in content else "txt"
        file_name = f"config_{call.message.chat.id}.{ext}"
        
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(content)
        
        with open(file_name, "rb") as f:
            bot.send_document(call.message.chat.id, f, caption="📄 Ваш конфиг")
        
        os.remove(file_name)
    
    elif call.data == "retry_last":
        bot.answer_callback_query(call.id, "Пробую еще раз...")
        # Здесь можно реализовать повтор последней ссылки, если хранить её в user_storage

bot.polling(none_stop=True)
