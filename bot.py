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
import cloudscraper

TOKEN = os.getenv('TELEGRAM_TOKEN')
SAYORI_KEY = os.getenv('SAYORI_KEY')

bot = telebot.TeleBot(TOKEN)
user_storage = {}

USER_AGENTS = [
    'v2rayNG/1.8.5 (com.v2ray.ang; build 100805; Android 13)',
    'ClashforWindows/0.20.39',
    'Clash-verge/1.3.8',
    'Shadowrocket/2.2.38 (iPhone; iOS 17.0.1; Scale/3.00)',
    'Quantumult%20X/1.4.3 (iPhone; iOS 17.0.1; Scale/3.00)',
    'Stash/2.4.5 (iPhone; iOS 17.0.1; Scale/3.00)'
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
    
    # Создаем скрейпер для обхода Cloudflare
    scraper = cloudscraper.create_scraper()
    
    for url_to_try in [proxy_url, original_url]:
        try:
            # Берем случайный агент из "профильных" (v2ray/clash)
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'text/plain, */*' # Явно просим текстовый формат
            }
            
            res = scraper.get(url_to_try, headers=headers, timeout=15, allow_redirects=True)
            
            if res.status_code == 200:
                # ГЛАВНАЯ ПРОВЕРКА: если это HTML, то это не наши данные
                if "<html" in res.text.lower() or "<!doctype" in res.text.lower():
                    error_code = "HTML_BLOCKED"
                    continue # Пробуем следующую ссылку (например, original после proxy)
                
                if len(res.text) > 10:
                    content = res.text.strip()
                    break
            error_code = res.status_code
        except Exception as e:
            error_code = f"Error: {str(e)[:15]}"

    # Проверка: не скачали ли мы вместо конфигов HTML-страницу?
    if content.startswith("<!DOCTYPE") or "<html" in content[:100].lower():
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Повторить", callback_data="retry_last"))
        bot.edit_message_text(f"⚠️ **Ошибка: Сайт заблокировал бота**\n\nВместо ссылок пришла веб-страница. Возможно, включена защита Cloudflare или ссылка ведет на документацию, а не на файл.", 
                              chat_id, message_id, reply_markup=kb, parse_mode='Markdown')
        return

    # --- ЛОГИКА ОБРАБОТКИ КОНТЕНТА ---
    all_found_links = []
    # Улучшенное регулярное выражение (не ломается на решетке в конце)
    pattern = r'(?:vless|vmess|ss|trojan|shadowsocks|tuic|hysteria2?)://[^\s\r\n"\'<>]+'

    # 1. Ищем ссылки "как есть" в полученном тексте
    direct_links = re.findall(pattern, content)
    all_found_links.extend(direct_links)

    # 2. Пробуем декодировать ВЕСЬ текст (на случай, если это стандартный Base64 подписки)
    try:
        clean_b64 = "".join(content.split())
        # Добавляем padding если нужно, чтобы base64 не ругался
        missing_padding = len(clean_b64) % 4
        if missing_padding:
            clean_b64 += '=' * (4 - missing_padding)
            
        decoded = base64.b64decode(clean_b64).decode('utf-8', errors='ignore')
        
        # Если в декодированном тексте есть протоколы — собираем их
        if any(p in decoded for p in ['vless://', 'vmess://', 'ss://', 'trojan://']):
            b64_links = re.findall(pattern, decoded)
            all_found_links.extend(b64_links)
    except:
        pass # Если это не Base64, просто идем дальше

    # 3. Удаляем дубликаты, сохраняя порядок
    links = list(dict.fromkeys(all_found_links))
    
    # Формируем итоговые данные (список ссылок в столбик)
    if links:
        final_data = "\n".join(links)
    else:
        final_data = content # Если ссылок нет, оставляем как было (может там JSON)

    user_storage[chat_id]['content'] = final_data
    
    # --- ФОРМИРОВАНИЕ ОТЧЕТА ---
    crypt_type = user_storage[chat_id].get('crypt_ver') or "auto/web"
    crypt_info = f"🔑 Тип обработки: `{crypt_type}`\n"
    
    report = (
        f"✅ **Данные получены**\n"
        f"{crypt_info}\n"
        f"🔗 **Источник:**\n`{original_url}`\n\n"
        f"🌐 **Прокси:**\n`{proxy_url}`\n\n"
        f"📊 Найдено узлов: `{len(links)}`"
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
