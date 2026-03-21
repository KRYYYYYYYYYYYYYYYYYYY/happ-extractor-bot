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
    payload = {"link": happ_link.strip()}
    
    # Пытаемся 3 раза, если сервер тупит
    for attempt in range(3):
        try:
            res = requests.post(api_url, json=payload, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return data.get("result")
            elif res.status_code == 500:
                # Если 500, ждем чуть дольше с каждой попыткой
                time.sleep(2 * (attempt + 1))
                continue
        except Exception:
            time.sleep(1)
            continue
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
    
    # 1. Если happ:// уже в тексте
    match = re.search(r'happ://crypt\d/[^\s"\'<>]+', decoded_raw)
    if match: return match.group(0)
    
    if text_or_url.startswith('http'):
        try:
            # Небольшая пауза перед запросом к сайту
            time.sleep(random.uniform(0.8, 1.5))
            h = {'User-Agent': random.choice(USER_AGENTS)}
            # allow_redirects=False нужен, чтобы поймать happ:// в заголовках (ecobuy)
            r = requests.get(text_or_url, headers=h, timeout=10, allow_redirects=False)
            
            # Проверяем заголовки редиректа
            loc = r.headers.get('Location', '')
            if 'happ://' in unquote(loc):
                return unquote(loc)

            # Проверка на Атланту в теле страницы
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
        # Увеличиваем паузу, чтобы имитировать чтение страницы человеком
        time.sleep(random.uniform(1.5, 3.0)) 
        
        headers = {
            # Используем только один, максимально похожий на браузер UA
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        # Важно: verify=True (по умолчанию) и таймаут побольше
        res = requests.get(sub_url, headers=headers, timeout=25, allow_redirects=True)
        error_code = res.status_code
        
        if res.status_code == 200:
            # .text автоматически обрабатывает кодировку и сжатие
            content = res.text.strip()
            
            # Если контент пустой или подозрительно короткий (ошибка провайдера)
            if len(content) < 10:
                error_code = "Empty Response"
                content = ""
        else:
            # Если получили 500 или 403, пробуем еще раз с другим UA через рекурсию (опционально)
            pass

    except Exception as e:
        error_code = f"Err: {str(e)[:15]}"

    # Проверка на успешность получения данных
    if not content or (isinstance(error_code, int) and error_code >= 400):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Повторить", callback_data="force_api"))
        bot.edit_message_text(f"❌ Сервер временно недоступен (Код: {error_code})\n"
                              f"Попробуйте нажать «Повторить» через 5-10 секунд.", 
                              chat_id, message_id, reply_markup=kb)
        return

    # Обработка Base64 (если контент зашифрован)
    final_data = content
    try:
        # Проверка: если нет признаков открытого текста, пробуем base64
        if "://" not in content[:100] and "{" not in content[:50]:
            clean_raw = re.sub(r'[^a-zA-Z0-9+/=]', '', content)
            decoded = base64.b64decode(clean_raw).decode('utf-8', errors='ignore')
            if "://" in decoded or "{" in decoded:
                final_data = decoded
    except:
        pass

    user_storage[chat_id] = final_data
    
    # Поиск ссылок (VLESS, VMESS и т.д.)
    links = re.findall(r'(?:vless|vmess|ss|trojan|shadowsocks|tuic|hysteria2?)://[^\r\n"\'<>]+', final_data)
    
    # ПРОВЕРКА ТИПА
    is_atlanta = "atlanta-subs" in sub_url
    has_json_struct = '"outbounds"' in content or '"nodes"' in content
    
    if is_atlanta or has_json_struct:
        status_text = "✅ JSON Конфигурация"
    elif links:
        status_text = "ℹ️ Текстовая подписка"
    else:
        status_text = "📄 Текстовый файл"

    report = (
        f"✅ **Готово!**\n\n"
        f"🌐 **Тип:** `{status_text}`\n"
        f"🔗 **Найдено ссылок:** `{len(links)}` шт.\n\n"
        f"🔗 **Линк:**\n`{sub_url}`\n\n"
        f"⚠️ **P.S.** Используйте [конвертер]({CONVERTER_URL})."
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
