import os
import telebot
import requests
import re
import base64
import random
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

def universal_search(html_text):
    """Ищет happ:// или прямые конфиги в HTML"""
    decoded_html = unquote(html_text)
    happ_match = re.search(r'happ://(crypt\d?)/[^\s"\'<>]+', decoded_html)
    if happ_match:
        return happ_match.group(0), happ_match.group(1)
    
    try:
        match = re.search(r'data-panel="([^"]+)"', html_text)
        if match:
            decoded = base64.b64decode(match.group(1)).decode('utf-8')
            data = json.loads(decoded)
            url = data.get("response", {}).get("subscriptionUrl")
            if url: return url, None
    except: pass
    
    return None, None

def decrypt_via_api(happ_link):
    api_url = "https://api.sayori.cc/v1/decrypt"
    headers = {"Content-Type": "application/json", "x-api-key": SAYORI_KEY}
    payload = {"link": happ_link.strip()}
    try:
        res = requests.post(api_url, json=payload, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            if data.get("success"):
                return data.get("result")
    except: pass
    return None

def get_content(url):
    """Пытается загрузить контент напрямую или через прокси"""
    proxy_url = f"https://s.sayori.cc/{url}" if url.startswith('http') else url
    for target in [proxy_url, url]:
        try:
            res = requests.get(target, headers={'User-Agent': random.choice(USER_AGENTS)}, timeout=10)
            if res.status_code == 200 and len(res.text) > 10:
                return res.text.strip(), target
        except: continue
    return None, None

@bot.message_handler(func=lambda m: True)
def handle_message(m):
    text = m.text.strip()
    if text.startswith('/'): return
    
    status_msg = bot.reply_to(m, "⏳ **Анализирую матрешку...**", parse_mode='Markdown')
    process_recursive(m.chat.id, text, status_msg.message_id)

def process_recursive(chat_id, current_url, message_id, depth=0):
    """
    Главная функция: разворачивает ссылки, пока не найдет конфиги.
    depth нужен, чтобы не уйти в бесконечный цикл.
    """
    if depth > 5:
        bot.edit_message_text("❌ Слишком глубокая вложенность ссылок.", chat_id, message_id)
        return

    # 1. Если это happ:// — сразу дешифруем
    if current_url.startswith('happ://'):
        decrypted = decrypt_via_api(current_url)
        if decrypted:
            return process_recursive(chat_id, decrypted, message_id, depth + 1)
        else:
            bot.edit_message_text("❌ Не удалось расшифровать happ ссылку.", chat_id, message_id)
            return

    # 2. Загружаем контент по ссылке
    raw_data, used_url = get_content(current_url)
    if not raw_data:
        bot.edit_message_text("❌ Не удалось получить данные по ссылке.", chat_id, message_id)
        return

    # 3. Пытаемся понять, что внутри: HTML, Base64 или чистые конфиги
    # Проверяем на HTML (поиск новых ссылок внутри)
    found_link, _ = universal_search(raw_data)
    if found_link:
        return process_recursive(chat_id, found_link, message_id, depth + 1)

    # Пробуем декодировать Base64 (часто подписки зашифрованы так)
    final_content = raw_data
    try:
        if "://" not in raw_data[:50] and "{" not in raw_data[:20]:
            decoded = base64.b64decode(raw_data).decode('utf-8', errors='ignore')
            if "://" in decoded or "{" in decoded:
                final_content = decoded
    except: pass

    # 4. И вот ТЕПЕРЬ, когда мы максимально глубоко, считаем узлы
    links = re.findall(r'(?:vless|vmess|ss|trojan|shadowsocks|tuic|hysteria2?)://[^\r\n"\'<>#]+', final_content)
    
    # Сохраняем для кнопки "Скачать"
    if chat_id not in user_storage: user_storage[chat_id] = {}
    user_storage[chat_id]['content'] = final_content
    user_storage[chat_id]['last_url'] = current_url

    # Формируем отчет
    report = (
        f"✅ **Обработка завершена**\n\n"
        f"🌐 **Финальная ссылка:**\n`{current_url}`\n\n"
        f"📊 Найдено узлов: `{len(links)}`"
    )
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📥 Скачать конфиг", callback_data="get_all"))
    kb.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="retry_last"))
    
    bot.edit_message_text(report, chat_id, message_id, parse_mode='Markdown', reply_markup=kb, disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    if call.data == "get_all":
        data = user_storage.get(chat_id, {}).get('content')
        if not data:
            bot.answer_callback_query(call.id, "Данные устарели.")
            return
        
        ext = "json" if '"outbounds"' in data else "txt"
        file_name = f"config_{chat_id}.{ext}"
        with open(file_name, "w", encoding="utf-8") as f: f.write(data)
        with open(file_name, "rb") as f:
            bot.send_document(chat_id, f, caption="📄 Ваш конфиг")
        os.remove(file_name)
    elif call.data == "retry_last":
        last_url = user_storage.get(chat_id, {}).get('last_url')
        if last_url:
            bot.answer_callback_query(call.id, "Обновляю...")
            process_recursive(chat_id, last_url, call.message.message_id)

bot.polling(none_stop=True)
