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
    except Exception as e:
        print(f"Decrypt Error: {e}")
    return None

def extract_happ(text):
    decoded = unquote(text)
    # Ищем happ:// (включая версии crypt, crypt3, crypt5 и т.д.)
    match = re.search(r'happ://(crypt\d?)/[^\s"\'<>]+', decoded)
    if match:
        return match.group(0), match.group(1)
    return None, None

# НОВАЯ ФУНКЦИЯ: Поиск скрытых ссылок в HTML коде (view-source)
def find_hidden_links(url):
    try:
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            html_content = res.text
            
            # 1. Пробуем найти happ:// внутри HTML
            happ_link, crypt_ver = extract_happ(html_content)
            if happ_link:
                return happ_link, crypt_ver
            
            # 2. Пробуем найти прямые ссылки на атланту или подобные (как в твоем примере)
            # Ищем что-то похожее на подписки: vless://, vmess:// или специфичные пути
            patterns = [
                r'https?://[a-zA-Z0-9.-]+\.[a-z]{2,}/[A-Z0-9_]{10,}', # Длинные рандомные пути
                r'https?://[a-zA-Z0-9.-]+\.atlanta-subs\.ru/[^\s"\'<>]+' # Специфично для атланты
            ]
            for pattern in patterns:
                found = re.search(pattern, html_content)
                if found:
                    return found.group(0), None
    except:
        pass
    return None, None

@bot.message_handler(func=lambda m: True)
def handle_message(m):
    text = m.text.strip()
    if text.startswith('/'): return

    # Проверяем, есть ли happ:// сразу в тексте
    happ_link, crypt_ver = extract_happ(text)
    target_url = happ_link if happ_link else (text if text.startswith('http') else None)

    if not target_url:
        bot.reply_to(m, "❌ Ссылка не распознана.")
        return

    status_msg = bot.reply_to(m, "⏳ **Анализ ссылки...**", parse_mode='Markdown')
    
    # Если это обычная ссылка и в ней нет happ://, пробуем заглянуть внутрь (view-source)
    if target_url.startswith('http') and not happ_link:
        hidden_url, hidden_crypt = find_hidden_links(target_url)
        if hidden_url:
            target_url = hidden_url
            crypt_ver = hidden_crypt

    process_link(m.chat.id, target_url, status_msg.message_id, crypt_ver)

def process_link(chat_id, target_url, message_id, crypt_ver=None):
    final_url = target_url
    
    # 1. Если нашли или получили happ:// — дешифруем
    if target_url.startswith('happ://'):
        decrypted = decrypt_via_api(target_url)
        if not decrypted:
            bot.edit_message_text("❌ Ошибка: Не удалось расшифровать happ-ссылку.", chat_id, message_id)
            return
        final_url = decrypted

    # 2. Формируем прокси-ссылку
    proxy_url = f"https://s.sayori.cc/{final_url}" if final_url.startswith('http') else final_url
    
    if chat_id not in user_storage: user_storage[chat_id] = {}
    user_storage[chat_id]['last_url'] = target_url
    user_storage[chat_id]['crypt_ver'] = crypt_ver

    fetch_and_report(chat_id, final_url, proxy_url, message_id)

def fetch_and_report(chat_id, original_url, proxy_url, message_id):
    content = ""
    error_code = None
    
    # 1. ЗАГРУЗКА (берем полные данные)
    for url_to_try in [proxy_url, original_url]:
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            res = requests.get(url_to_try, headers=headers, timeout=15)
            if res.status_code == 200 and len(res.text) > 10:
                content = res.text.strip()
                break
            error_code = res.status_code
        except:
            error_code = "Timeout"

    if not content:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Повторить", callback_data="retry_last"))
        bot.edit_message_text(f"❌ Ошибка загрузки (Код: {error_code})\n\nСервер недоступен.", 
                              chat_id, message_id, reply_markup=kb)
        return

    # 2. ДЕКОДИРОВАНИЕ (превращаем в текст ПЕРЕД подсчетом)
    final_data = content
    is_base64_encoded = False
    
    # Пробуем декодировать Base64, если это не прямой список ссылок и не JSON
    if "://" not in content[:100] and "{" not in content[:50]:
        try:
            # Очищаем только от пробельных символов, сохраняя всю длину
            clean_b64 = "".join(content.split()) 
            decoded = base64.b64decode(clean_b64).decode('utf-8', errors='ignore')
            if "://" in decoded or "{" in decoded:
                final_data = decoded
                is_base64_encoded = True
        except:
            pass

    # Сохраняем ПОЛНЫЕ данные в память
    user_storage[chat_id]['content'] = final_data

    # 3. АНАЛИЗ (считаем узлы в ПОЛНОСТЬЮ готовом тексте)
    links = re.findall(r'(?:vless|vmess|ss|trojan|shadowsocks|tuic|hysteria2?)://[^\r\n"\'<>#\s]+', final_data)
    
    # Определяем формат
    if '"outbounds"' in final_data or '"nodes"' in final_data:
        format_type = "🛠 JSON Config"
    elif is_base64_encoded:
        format_type = "📦 Base64 (Decoded)"
    elif links:
        format_type = "🔗 Plain Text List"
    else:
        format_type = "📄 Raw Data"

    crypt_info = f"🔑 Ключ: `{user_storage[chat_id].get('crypt_ver', 'auto')}`\n" if user_storage[chat_id].get('crypt_ver') else ""
    
    # 4. ФИНАЛЬНЫЙ ОТЧЕТ (сокращаем только визуально в тексте!)
    def short(url): return (url[:45] + "...") if len(url) > 45 else url

    report = (
        f"✅ **Обработано успешно**\n"
        f"{crypt_info}"
        f"📂 **Формат:** `{format_type}`\n"
        f"📊 **Найдено узлов:** `{len(links)}` шт.\n\n"
        f"🔗 **Источник:**\n`{short(original_url)}`\n\n"
        f"🌐 **Прокси:**\n`{short(proxy_url)}`"
    )
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📥 Скачать файл", callback_data="get_all"))
    kb.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="retry_last"))
    
    bot.edit_message_text(report, chat_id, message_id, parse_mode='Markdown', 
                          reply_markup=kb, disable_web_page_preview=True)

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
            bot.send_document(chat_id, f, caption="📄 Расшифрованный конфиг")
        os.remove(file_name)
        
    elif call.data == "retry_last":
        last_url = user_storage.get(chat_id, {}).get('last_url')
        crypt_ver = user_storage.get(chat_id, {}).get('crypt_ver')
        if last_url:
            bot.answer_callback_query(call.id, "Обновляю...")
            process_link(chat_id, last_url, call.message.message_id, crypt_ver)

bot.polling(none_stop=True)
