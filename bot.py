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
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'v2rayNG/1.8.5 (com.v2ray.ang; build 100805; Android 13)'
]

CONVERTER_URL = "https://cs12d7a.4pda.ws/34581412/V2RAY+Converter+fix25fix.html"

# --- НОВЫЕ ФУНКЦИИ ПАРСИНГА ---

def universal_search(html_text):
    """Ищет happ:// или прямые конфиги в HTML коде (view-source)"""
    # 1. Ищем happ ссылки (включая закодированные в URL)
    decoded_html = unquote(html_text)
    happ_match = re.search(r'happ://(crypt\d?)/[^\s"\'<>]+', decoded_html)
    if happ_match:
        return happ_match.group(0), happ_match.group(1)
    
    # 2. Ищем JSON конфиги Атланты в мета-тегах
    try:
        match = re.search(r'data-panel="([^"]+)"', html_text)
        if match:
            decoded = base64.b64decode(match.group(1)).decode('utf-8')
            data = json.loads(decoded)
            url = data.get("response", {}).get("subscriptionUrl")
            if url: return url, None
    except: pass
    
    return None, None

# --- СТАРЫЕ ФУНКЦИИ (БЕЗ ИЗМЕНЕНИЙ ЛОГИКИ) ---

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
    match = re.search(r'happ://(crypt\d?)/[^\s"\'<>]+', decoded)
    if match:
        return match.group(0), match.group(1)
    return None, None

@bot.message_handler(func=lambda m: True)
def handle_message(m):
    text = m.text.strip()
    if text.startswith('/'): return

    # Проверяем на наличие happ прямо в тексте (старая логика)
    happ_link, crypt_ver = extract_happ(text)
    target_url = happ_link if happ_link else (text if text.startswith('http') else None)

    if not target_url:
        bot.reply_to(m, "❌ Ссылка не распознана.")
        return

    status_msg = bot.reply_to(m, "⏳ **Обработка...**", parse_mode='Markdown')
    process_link(m.chat.id, target_url, status_msg.message_id, crypt_ver)

def process_link(chat_id, target_url, message_id, crypt_ver=None):
    # Если это НЕ happ://, пробуем заглянуть внутрь страницы (view-source)
    if not target_url.startswith('happ://'):
        try:
            # Используем прокси для первичного осмотра страницы
            proxy_view = f"https://s.sayori.cc/{target_url}"
            res = requests.get(proxy_view, headers={'User-Agent': random.choice(USER_AGENTS)}, timeout=10)
            
            # Ищем скрытый happ или прямую ссылку на подписку
            found_url, found_ver = universal_search(res.text)
            if found_url:
                target_url = found_url
                crypt_ver = found_ver
        except:
            pass

    # Далее стандартный чекер
    final_url = target_url
    if target_url.startswith('happ://'):
        decrypted = decrypt_via_api(target_url)
        if not decrypted:
            bot.edit_message_text("❌ Ошибка: Не удалось расшифровать ссылку через API.", chat_id, message_id)
            return
        final_url = decrypted

    proxy_url = f"https://s.sayori.cc/{final_url}" if final_url.startswith('http') else final_url
    
    if chat_id not in user_storage: user_storage[chat_id] = {}
    user_storage[chat_id]['last_url'] = target_url
    user_storage[chat_id]['crypt_ver'] = crypt_ver

    fetch_and_report(chat_id, final_url, proxy_url, message_id)

def fetch_and_report(chat_id, original_url, proxy_url, message_id):
    content = ""
    error_code = None
    
    # Создаем "умный" сеанс, который умеет обходить Cloudflare
    scraper = cloudscraper.create_scraper() 
    
    for url_to_try in [proxy_url, original_url]:
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            # ЗАМЕНА: вместо requests.get используем scraper.get
            res = scraper.get(url_to_try, headers=headers, timeout=15)
            
            if res.status_code == 200 and len(res.text) > 10:
                content = res.text.strip()
                break
            error_code = res.status_code
        except Exception as e:
            error_code = f"Error: {str(e)[:20]}" # Записываем текст ошибки для отладки

    if not content:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Повторить", callback_data="retry_last"))
        bot.edit_message_text(f"❌ Ошибка загрузки (Код: {error_code})\n\nСервер недоступен или защищен. Попробуйте снова.", 
                              chat_id, message_id, reply_markup=kb)
        return

    # --- Улучшенный блок декодирования ---
    final_data = content
    try:
        # Убираем все переносы и пробелы, которые ломают Base64
        clean_b64 = "".join(content.split())
        
        # Пытаемся декодировать
        decoded = base64.b64decode(clean_b64).decode('utf-8', errors='ignore')
        
        # Проверяем, есть ли в декодированном тексте признаки конфигов
        protocols = ['vless://', 'vmess://', 'ss://', 'trojan://', 'hy2://', 'tuic://', '{']
        if any(proto in decoded for proto in protocols):
            final_data = decoded
    except:
        # Если это не Base64, оставляем исходный текст (final_data = content)
        pass

    user_storage[chat_id]['content'] = final_data
    
    # Поиск ссылок с использованием \S+ (до первого пробела)
    links = re.findall(r'(?:vless|vmess|ss|trojan|shadowsocks|tuic|hysteria2?)://\S+', final_data)
    
    # --- Формирование отчета ---
    crypt_info = f"🔑 Ключ: `{user_storage[chat_id].get('crypt_ver', 'auto')}`\n" if user_storage[chat_id].get('crypt_ver') else ""
    
    report = (
        f"✅ **Обработано успешно**\n"
        f"{crypt_info}\n"
        f"🔗 **Результат (исходный):**\n`{original_url}`\n\n"
        f"🌐 **Прокси-ссылка:**\n`{proxy_url}`\n\n"
        f"📊 Найдено узлов: `{len(links)}`"
    )
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📥 Скачать файл", callback_data="get_all"))
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
        crypt_ver = user_storage.get(chat_id, {}).get('crypt_ver')
        if last_url:
            bot.answer_callback_query(call.id, "Обновляю...")
            process_link(chat_id, last_url, call.message.message_id, crypt_ver)

bot.polling(none_stop=True)
