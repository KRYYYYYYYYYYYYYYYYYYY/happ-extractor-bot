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
    'v2rayNG/1.8.5 (com.v2ray.ang; build 100805; Android 13)',
    'NekoBox/1.3.1 (com.matsuri.nekobox; build 10301; Android 12)',
    'Happ/2.1.0 (com.happ.network; build 2100; iOS 16.1)'
]

def split_json_objects(text):
    """Находит JSON объекты в тексте."""
    if not text or '{' not in text: return []
    objs = []
    bracket_count = 0
    start_index = -1
    for i, char in enumerate(text):
        if char == '{':
            if bracket_count == 0: start_index = i
            bracket_count += 1
        elif char == '}':
            bracket_count -= 1
            if bracket_count == 0 and start_index != -1:
                obj_candidate = text[start_index:i+1]
                try:
                    json.loads(obj_candidate)
                    objs.append(obj_candidate)
                except: pass
                start_index = -1
    return objs

def decrypt_via_api(happ_link):
    api_url = "https://api.sayori.cc/v1/decrypt"
    headers = {"Content-Type": "application/json", "x-api-key": SAYORI_KEY}
    payload = {"link": happ_link}
    try:
        res = requests.post(api_url, json=payload, headers=headers, timeout=15)
        return res.json().get("result") if res.status_code == 200 else None
    except: return None

def extract_happ_raw(url):
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    try:
        url_dec = unquote(url)
        if 'happ://' in url_dec:
            m = re.search(r'happ://crypt\d/[^"\'\s<>]+', url_dec)
            if m: return m.group(0)
        res = requests.get(url, headers=headers, timeout=10)
        m = re.search(r'happ://crypt\d/[^"\'\s<>]+', res.text)
        return m.group(0) if m else None
    except: return None

@bot.message_handler(func=lambda m: True)
def handle_message(m):
    text = m.text.strip()
    happ_link = text if text.startswith('happ://') else extract_happ_raw(text)
    
    if not happ_link:
        bot.reply_to(m, "❌ Ссылка не найдена.")
        return

    status_msg = bot.reply_to(m, "⏳ *Стучусь в подписку...*", parse_mode='Markdown')
    decrypted_url = decrypt_via_api(happ_link)
    
    if decrypted_url:
        sub_link = decrypted_url.strip()
        content = ""
        error_info = ""

        try:
            # Упрощенные заголовки, чтобы не ловить 500 ошибку
            sub_headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': '*/*'
            }
            time.sleep(1) 
            sub_res = requests.get(sub_link, headers=sub_headers, timeout=15)
            
            if sub_res.status_code == 200:
                raw = sub_res.text.strip()
                try:
                    # Попытка Base64
                    pad = len(raw) % 4
                    if pad: raw += '=' * (4 - pad)
                    content = base64.b64decode(raw).decode('utf-8', errors='ignore')
                except:
                    content = raw
            else:
                error_info = f"⚠️ Ошибка сервера: {sub_res.status_code}"
        except Exception as e:
            error_info = f"❌ Ошибка: {str(e)[:30]}"

        if error_info:
            bot.edit_message_text(f"❌ Не удалось загрузить данные.\n{error_info}", m.chat.id, status_msg.message_id)
            return

        user_storage[m.chat.id] = content
        
        # Анализ
        jsons = split_json_objects(content)
        links = [l.strip() for l in content.split('\n') if '://' in l and not l.strip().startswith('{')]
        
        stats = {}
        for l in links:
            proto = l.split('://')[0].upper()
            stats[proto] = stats.get(proto, 0) + 1
        stats_info = "\n".join([f"🔹 {k}: `{v}`" for k, v in stats.items()])

        report = (
            f"✅ **Готово!**\n\n"
            f"🔗 **Ссылка:**\n`{sub_link}`\n\n"
            f"🔗 Ссылки: `{len(links)} шт.`\n"
            f"📦 JSON-конфиги: `{len(jsons)} шт.`\n"
            f"{stats_info}"
        )
        
        kb = types.InlineKeyboardMarkup()
        if content:
            kb.add(types.InlineKeyboardButton("📥 Скачать All Config", callback_data="get_all"))
        
        bot.edit_message_text(report, m.chat.id, status_msg.message_id, parse_mode='Markdown', reply_markup=kb)
    else:
        bot.edit_message_text("❌ Ошибка расшифровки.", m.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "get_all")
def get_all(call):
    content = user_storage.get(call.message.chat.id)
    if not content: return
    
    is_json = content.strip().startswith('{')
    if len(content) < 3000:
        bot.send_message(call.message.chat.id, f"```\n{content}\n```", parse_mode='Markdown')
    else:
        file_path = f"sub_{call.message.chat.id}.{'json' if is_json else 'txt'}"
        with open(file_path, "w", encoding="utf-8") as f: f.write(content)
        with open(file_path, "rb") as f:
            bot.send_document(call.message.chat.id, f)
        if os.path.exists(file_path): os.remove(file_path)
    bot.answer_callback_query(call.id)

bot.polling()
