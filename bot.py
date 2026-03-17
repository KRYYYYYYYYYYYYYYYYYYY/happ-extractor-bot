import os
import telebot
import requests
import re
import base64
import random
from urllib.parse import unquote
from telebot import types

TOKEN = os.getenv('TELEGRAM_TOKEN')
SAYORI_KEY = os.getenv('SAYORI_KEY')

bot = telebot.TeleBot(TOKEN)
user_storage = {}

# Список агентов для разнообразия
USER_AGENTS = [
    'v2rayNG/1.8.5 (com.v2ray.ang; build 100805; Android 13)',
    'NekoBox/1.3.1 (com.matsuri.nekobox; build 10301; Android 12)',
    'Happ/2.1.0 (com.happ.network; build 2100; iOS 16.1)',
    'ClashForAndroid/2.5.12 (com.github.kr328.clash; build 20512; Android 14)'
]

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
        content = ""
        data_type = "Не определено"

        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            sub_res = requests.get(sub_link, headers=headers, timeout=12)
            
            if sub_res.status_code == 200:
                raw = sub_res.text.strip()
                # Пробуем Base64
                try:
                    pad = len(raw) % 4
                    if pad: raw += '=' * (4 - pad)
                    content = base64.b64decode(raw).decode('utf-8', errors='ignore')
                except:
                    content = raw
                
                # Определяем тип данных
                if content.strip().startswith('{') or content.strip().startswith('['):
                    data_type = "📦 JSON-конфигурация"
                    configs = [content] # JSON сохраняем целиком
                else:
                    data_type = "🔗 Список ссылок (vless/vmess/...)"
                    configs = [line.strip() for line in content.split('\n') if '://' in line]
            else:
                configs = []
        except:
            configs = []

        user_storage[m.chat.id] = content # Храним сырой контент для All Config
        
        # Считаем протоколы (только для ссылок)
        stats_info = ""
        if data_type == "🔗 Список ссылок (vless/vmess/...)":
            stats = {}
            for c in configs:
                proto = c.split('://')[0].upper()
                stats[proto] = stats.get(proto, 0) + 1
            stats_info = "\n".join([f"🔹 {k}: `{v}`" for k, v in stats.items()])
            count_info = f"📊 Найдено серверов: `{len(configs)}`"
        else:
            count_info = "📊 Размер конфига: `{:.2f} KB`".format(len(content)/1024)

        report = (
            f"✅ **Готово!**\n\n"
            f"🌐 **Тип контента:** `{data_type}`\n"
            f"🔗 **Ссылка на подписку:**\n"
            f"```\n{sub_link}\n```\n"
            f"{count_info}\n"
            f"{stats_info}"
        )
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📥 Скачать All Config", callback_data="get_all"))
        
        bot.edit_message_text(report, m.chat.id, status_msg.message_id, parse_mode='Markdown', reply_markup=kb)
    else:
        bot.edit_message_text("❌ Ошибка Sayori API.", m.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "get_all")
def get_all(call):
    content = user_storage.get(call.message.chat.id)
    if not content:
        bot.answer_callback_query(call.id, "Данные не найдены.")
        return
    
    # Если контент — ссылки, добавим пустые строки для удобства копирования
    if not (content.strip().startswith('{') or content.strip().startswith('[')):
        content = "\n\n".join([line.strip() for line in content.split('\n') if line.strip()])

    if len(content) < 3800:
        bot.send_message(call.message.chat.id, f"```\n{content}\n```", parse_mode='Markdown')
    else:
        file_path = f"config_{call.message.chat.id}.txt"
        with open(file_path, "w", encoding="utf-8") as f: f.write(content)
        with open(file_path, "rb") as f:
            bot.send_document(call.message.chat.id, f, caption="📂 Твой полный конфиг")
        if os.path.exists(file_path): os.remove(file_path)
    
    bot.answer_callback_query(call.id)

bot.polling()
