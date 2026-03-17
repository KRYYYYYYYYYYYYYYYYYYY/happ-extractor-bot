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

# Максимально "живая" маскировка
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

def extract_happ_anywhere(text_or_url):
    """Глубокий поиск happ:// ссылки"""
    # Если это редирект-ссылка, декодируем её сразу
    decoded_raw = unquote(text_or_url)
    
    # Ищем паттерн happ://
    match = re.search(r'happ://crypt\d/[^\s"\'<>]+', decoded_raw)
    if match: return match.group(0)
    
    # Если это просто URL сайта, пробуем зайти
    if text_or_url.startswith('http'):
        try:
            h = {'User-Agent': random.choice(USER_AGENTS)}
            r = requests.get(text_or_url, headers=h, timeout=10)
            match = re.search(r'happ://crypt\d/[^\s"\'<>]+', r.text)
            if match: return match.group(0)
        except: pass
    return None

@bot.message_handler(func=lambda m: True)
def handle_message(m):
    text = m.text.strip()
    happ_link = extract_happ_anywhere(text)
    
    if not happ_link:
        bot.reply_to(m, "❌ Не удалось найти happ:// ссылку.")
        return

    status_msg = bot.reply_to(m, "⏳ *Стучусь в сервер...*", parse_mode='Markdown')
    
    # Первичная проверка через API
    decrypted = decrypt_via_api(happ_link)
    final_url = decrypted if decrypted else happ_link
    
    fetch_and_report(m.chat.id, final_url, status_msg.message_id)

def fetch_and_report(chat_id, sub_url, message_id):
    content = ""
    error_code = None
    
    try:
        # Улучшенные заголовки для обхода 500 ошибки
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        time.sleep(random.uniform(1, 2))
        res = requests.get(sub_url, headers=headers, timeout=15)
        error_code = res.status_code
        
        if res.status_code == 200:
            raw = res.text.strip()
            # Проверка на Base64
            try:
                clean_raw = re.sub(r'[^a-zA-Z0-9+/=]', '', raw)
                content = base64.b64decode(clean_raw).decode('utf-8', errors='ignore')
                if '://' not in content and '{' not in content: # Если расшифровалось в мусор
                    content = raw
            except:
                content = raw
    except Exception as e:
        error_code = str(e)[:20]

    if not content or (isinstance(error_code, int) and error_code >= 400):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔑 Принудительно через API", callback_data="force_api"))
        bot.edit_message_text(f"❌ Ошибка получения (Код: {error_code})\nПопробуйте расшифровать ссылку через API кнопку ниже.", 
                              chat_id, message_id, reply_markup=kb)
        return

    user_storage[chat_id] = content
    
    # Анализ содержимого
    links = [l.strip() for l in content.split('\n') if '://' in l and not l.strip().startswith('{')]
    has_json = '{' in content and '}' in content
    
    json_note = "✅ Обнаружен JSON конфиг" if has_json else "ℹ️ Прямые ссылки"
    
    report = (
        f"✅ **Готово!**\n\n"
        f"🌐 **Тип:** `{json_note}`\n"
        f"🔗 **Найдено ссылок:** `{len(links)}` шт.\n\n"
        f"🔗 **Линк:**\n`{sub_url}`\n\n"
        f"⚠️ **P.S.** Сложные JSON-структуры бот не парсит. Используйте [конвертер]({CONVERTER_URL}) или скачайте файл(При перенаправлении на страницу с таким содержимым 'Данная информация удалена или недоступна' используйте впн.)."
    )
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📥 Скачать контент", callback_data="get_all"))
    kb.add(types.InlineKeyboardButton("🔄 Повторить через API", callback_data="force_api"))
    
    bot.edit_message_text(report, chat_id, message_id, parse_mode='Markdown', reply_markup=kb, disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: c.data == "force_api")
def force_api_callback(call):
    # Извлекаем URL из сообщения
    urls = re.findall(r'https?://[^\s`]+', call.message.text)
    if urls:
        target = urls[-1] # Берем последнюю ссылку (обычно это ссылка подписки)
        bot.answer_callback_query(call.id, "Отправляю в Sayori API...")
        dec = decrypt_via_api(target)
        if dec:
            fetch_and_report(call.message.chat.id, dec, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "API не смогло расшифровать.", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "Ссылка не найдена.")

@bot.callback_query_handler(func=lambda c: c.data == "get_all")
def get_all(call):
    content = user_storage.get(call.message.chat.id)
    if not content: return
    
    ext = "json" if "{" in content else "txt"
    file_path = f"config_{call.message.chat.id}.{ext}"
    with open(file_path, "w", encoding="utf-8") as f: f.write(content)
    with open(file_path, "rb") as f:
        bot.send_document(call.message.chat.id, f, caption="Содержимое подписки")
    os.remove(file_path)
    bot.answer_callback_query(call.id)

bot.polling()
