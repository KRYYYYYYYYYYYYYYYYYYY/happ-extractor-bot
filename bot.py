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
    """Разделяет склеенные JSON-объекты и проверяет их валидность."""
    objs = []
    # Ищем потенциальные границы объектов {...}
    # Используем простой счетчик скобок для надежности при склейке
    bracket_count = 0
    start_index = -1
    
    for i, char in enumerate(text):
        if char == '{':
            if bracket_count == 0:
                start_index = i
            bracket_count += 1
        elif char == '}':
            bracket_count -= 1
            if bracket_count == 0 and start_index != -1:
                obj_candidate = text[start_index:i+1]
                try:
                    json.loads(obj_candidate)
                    objs.append(obj_candidate)
                except:
                    pass
                start_index = -1
    return objs

def decrypt_via_api(happ_link):
    api_url = "https://api.sayori.cc/v1/decrypt"
    headers = {"Content-Type": "application/json", "x-api-key": SAYORI_KEY}
    payload = {"link": happ_link}
    try:
        res = requests.post(api_url, json=payload, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data.get("result") if data.get("success") else None
    except: pass
    return None

def extract_happ_raw(url):
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    try:
        url_dec = unquote(url)
        if 'happ://' in url_dec:
            m = re.search(r'happ://crypt\d/[^"\'\s<>]+', url_dec)
            if m: return m.group(0)
        res = requests.get(url, headers=headers, timeout=10)
        final_url = unquote(res.url)
        if 'happ://' in final_url:
            m = re.search(r'happ://crypt\d/[^"\'\s<>]+', final_url)
            if m: return m.group(0)
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

    status_msg = bot.reply_to(m, "⏳ *Обработка подписки...*", parse_mode='Markdown')
    decrypted_url = decrypt_via_api(happ_link)
    
    if decrypted_url:
        sub_link = decrypted_url.strip()
        time.sleep(1)
        
        content = ""
        found_jsons = []
        found_links = []

        try:
            sub_headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': '*/*',
                'Connection': 'keep-alive',
            }
            sub_res = requests.get(sub_link, headers=sub_headers, timeout=15)
            
            if sub_res.status_code == 200 and sub_res.text.strip():
                raw = sub_res.text.strip()
                try:
                    pad = len(raw) % 4
                    if pad: raw += '=' * (4 - pad)
                    content = base64.b64decode(raw).decode('utf-8', errors='ignore')
                except:
                    content = raw
                
                # Поиск JSON-объектов
                found_jsons = split_json_objects(content)
                # Поиск классических ссылок
                found_links = [line.strip() for line in content.split('\n') if '://' in line and not line.strip().startswith('{')]
                
            else:
                content = f"⚠️ Ошибка сервера: {sub_res.status_code}"
        except Exception as e:
            content = f"❌ Ошибка запроса: {str(e)[:50]}"

        user_storage[m.chat.id] = content

        # Формируем статистику
        stats_info = ""
        if found_links:
            stats = {}
            for c in found_links:
                proto = c.split('://')[0].upper()
                stats[proto] = stats.get(proto, 0) + 1
            stats_info = "\n" + "\n".join([f"🔹 {k}: `{v}`" for k, v in stats.items()])
        
        # Плашка обнаружения
        json_status = f"📦 JSON-конфиги: `{len(found_jsons)} шт.`" if found_jsons else "📦 JSON-конфиги: `0`"
        links_status = f"🔗 Ссылки: `{len(found_links)} шт.`"
        
        report = (
            f"✅ **Готово!**\n\n"
            f"🔗 **Ссылка на подписку:**\n"
            f"```\n{sub_link}\n```\n"
            f"{links_status}\n"
            f"{json_status}\n"
            f"{stats_info}"
        )
        
        kb = types.InlineKeyboardMarkup()
        if content:
            kb.add(types.InlineKeyboardButton("📥 Скачать All Config", callback_data="get_all"))
        
        bot.edit_message_text(report, m.chat.id, status_msg.message_id, parse_mode='Markdown', reply_markup=kb)
    else:
        bot.edit_message_text("❌ Ошибка Sayori API.", m.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "get_all")
def get_all(call):
    content = user_storage.get(call.message.chat.id)
    if not content:
        bot.answer_callback_query(call.id, "Данные пусты.")
        return
    
    is_json = content.strip().startswith('{') or content.strip().startswith('[')
    
    if len(content) < 3500:
        bot.send_message(call.message.chat.id, f"```\n{content}\n```", parse_mode='Markdown')
    else:
        ext = "json" if is_json else "txt"
        file_path = f"config_{call.message.chat.id}.{ext}"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        with open(file_path, "rb") as f:
            bot.send_document(call.message.chat.id, f, caption=f"📂 Твой конфиг (.{ext})")
        if os.path.exists(file_path): os.remove(file_path)
    
    bot.answer_callback_query(call.id)

bot.polling()
