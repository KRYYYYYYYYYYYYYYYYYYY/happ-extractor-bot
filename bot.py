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
    'v2rayNG/1.8.5 (com.v2ray.ang; build 100805; Android 13)'
]

CONVERTER_URL = "https://cs12d7a.4pda.ws/34581412/V2RAY+Converter+fix25fix.html"

# --- БЛОК ЛОГИКИ ПАРСИНГА ---

def decrypt_via_api(happ_link):
    api_url = "https://api.sayori.cc/v1/decrypt"
    headers = {"Content-Type": "application/json", "x-api-key": SAYORI_KEY}
    payload = {"link": happ_link.strip()}
    try:
        res = requests.post(api_url, json=payload, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data.get("result") if data.get("success") else None
    except Exception as e:
        print(f"Decrypt Error: {e}")
    return None

def universal_parser(html_text):
    """Ищет happ://, прокси-ссылки и скрытый Base64/JSON в HTML"""
    found = []
    
    # 1. Прямые ссылки на протоколы
    found.extend(re.findall(r'(?:vless|vmess|ss|trojan|shadowsocks|tuic|hysteria2?)://[^\r\n"\'<>#\s]+', html_text))
    
    # 2. Скрытые happ://
    happ_matches = re.findall(r'happ://crypt\d?/[^\s"\'<>]+', html_text)
    found.extend(happ_matches)

    # 3. Поиск в Base64 (часто для Атланты и JS-скриптов)
    potential_b64 = re.findall(r'data-[a-z]+="([A-Za-z0-9+/=]{50,})"', html_text)
    potential_b64.extend(re.findall(r'["\']([A-Za-z0-9+/=]{100,})["\']', html_text)) # Длинные строки в коде
    
    for b64_str in potential_b64:
        try:
            decoded = base64.b64decode(b64_str).decode('utf-8', errors='ignore')
            # Ищем внутри декодированного
            inner_happ = re.search(r'happ://crypt\d?/[^\s"\'<>]+', decoded)
            if inner_happ: found.append(inner_happ.group(0))
            
            if '"subscriptionUrl"' in decoded:
                data = json.loads(decoded)
                url = data.get("response", {}).get("subscriptionUrl") or data.get("subscriptionUrl")
                if url: found.append(url)
        except: continue

    return list(set(found))

# --- ОСНОВНАЯ ЦЕПОЧКА ОБРАБОТКИ ---

@bot.message_handler(func=lambda m: True)
def handle_message(m):
    text = m.text.strip()
    if text.startswith('/'): return

    # Проверка на happ или http
    match_happ = re.search(r'happ://crypt\d?/[^\s"\'<>]+', unquote(text))
    target = match_happ.group(0) if match_happ else (text if text.startswith('http') else None)

    if not target:
        bot.reply_to(m, "❌ Ссылка не распознана.")
        return

    status_msg = bot.reply_to(m, "⏳ **Глубокий анализ...**", parse_mode='Markdown')
    # Запускаем рекурсивный процесс
    success = deep_process(m.chat.id, target, status_msg.message_id)
    
    if not success:
        bot.edit_message_text("❌ Не удалось извлечь данные. Возможно, ссылка защищена или пуста.", m.chat.id, status_msg.message_id)

def deep_process(chat_id, current_url, message_id, depth=0):
    if depth > 3: return False # Ограничение вложенности
    
    try:
        # 1. Если это happ — дешифруем сразу
        if current_url.startswith('happ://'):
            decrypted = decrypt_via_api(current_url)
            if decrypted:
                return deep_process(chat_id, decrypted, message_id, depth + 1)
            return False

        # 2. Если это HTTP — идем на сайт через прокси Sayori (view-source режим)
        proxy_url = f"https://s.sayori.cc/{current_url}"
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        res = requests.get(proxy_url, headers=headers, timeout=15)
        
        if res.status_code != 200:
            # Пробуем без прокси, если прокси упал
            res = requests.get(current_url, headers=headers, timeout=15)
            
        html = res.text
        links = universal_parser(html)
        
        # Если нашли прямые прокси (vless и т.д.)
        proxy_links = [l for l in links if '://' in l and not l.startswith(('http', 'happ'))]
        if proxy_links:
            report_success(chat_id, current_url, proxy_links, html, message_id)
            return True
            
        # Если нашли новый happ внутри кода — идем глубже
        happ_links = [l for l in links if l.startswith('happ://')]
        if happ_links:
            return deep_process(chat_id, happ_links[0], message_id, depth + 1)

        # Если нашли подписку (другой http) — идем по ней один раз
        http_links = [l for l in links if l.startswith('http') and l != current_url]
        if http_links and depth == 0:
             return deep_process(chat_id, http_links[0], message_id, depth + 1)

    except Exception as e:
        print(f"Error at depth {depth}: {e}")
    return False

def report_success(chat_id, final_url, nodes, raw_content, message_id):
    user_storage[chat_id] = {'content': raw_content, 'last_url': final_url}
    
    proxy_url = f"https://s.sayori.cc/{final_url}"
    
    report = (
        f"✅ **Глубокий анализ завершен**\n\n"
        f"📊 Найдено узлов: `{len(nodes)}` шт.\n"
        f"🌐 **Финальный URL:**\n`{final_url[:60]}...`\n\n"
        f"🚀 **Прокси-ссылка:**\n`{proxy_url}`\n\n"
        f"⚠️ Используйте [конвертер]({CONVERTER_URL})."
    )
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📥 Скачать файл", callback_data="get_all"))
    kb.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="retry_last"))
    
    bot.edit_message_text(report, chat_id, message_id, parse_mode='Markdown', reply_markup=kb, disable_web_page_preview=True)

# --- CALLBACKS ---

@bot.callback_query_handler(func=lambda c: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    if call.data == "get_all":
        data = user_storage.get(chat_id, {}).get('content')
        if not data: return
        
        ext = "json" if '"outbounds"' in data or '"nodes"' in data else "txt"
        file_name = f"config_{chat_id}.{ext}"
        with open(file_name, "w", encoding="utf-8") as f: f.write(data)
        with open(file_name, "rb") as f:
            bot.send_document(chat_id, f, caption="📄 Результат анализа")
        os.remove(file_name)
        
    elif call.data == "retry_last":
        url = user_storage.get(chat_id, {}).get('last_url')
        if url:
            bot.answer_callback_query(call.id, "Обновляю...")
            deep_process(chat_id, url, call.message.message_id)

bot.polling(none_stop=True)
