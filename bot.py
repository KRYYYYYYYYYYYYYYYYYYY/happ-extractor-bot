import os
import telebot
import requests
import re
import base64
import random
import time
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
        time.sleep(1) # Небольшая пауза перед запросом к серверу подписки
        
        content = ""
        data_type = "Не удалось получить данные"
        configs = []

        try:
            sub_headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'max-age=0'
            }
            sub_res = requests.get(sub_link, headers=sub_headers, timeout=15)
            
            if sub_res.status_code == 200 and sub_res.text.strip():
                raw = sub_res.text.strip()
                # Декодируем Base64
                try:
                    missing_padding = len(raw) % 4
                    if missing_padding: raw += '=' * (4 - missing_padding)
                    content = base64.b64decode(raw).decode('utf-8', errors='ignore')
                except:
                    content = raw
                
                if content.strip().startswith('{') or content.strip().startswith('['):
                    data_type = "📦 JSON-конфигурация"
                    configs = [content]
                else:
                    data_type = "🔗 Список ссылок (vless/vmess/...)"
                    configs = [line.strip() for line in content.split('\n') if '://' in line]
            else:
                data_type = f"⚠️ Ошибка сервера: {sub_res.status_code}"
        except Exception as e:
            data_type = f"❌ Ошибка запроса: {str(e)[:50]}"

        user_storage[m.chat.id] = content

        stats_info = ""
        if data_type == "🔗 Список ссылок (vless/vmess/...)":
            stats = {}
            for c in configs:
                proto = c.split('://')[0].upper()
                stats[proto] = stats.get(proto, 0) + 1
            stats_info = "\n".join([f"🔹 {k}: `{v}`" for k, v in stats.items()])
            count_info = f"📊 Внутри найдено серверов: `{len(configs)}`"
        else:
            size_kb = len(content.encode('utf-8')) / 1024 if content else 0
            count_info = f"📊 Размер контента: `{size_kb:.2f} KB`"

        report = (
            f"✅ **Готово!**\n\n"
            f"🌐 **Тип контента:** `{data_type}`\n"
            f"🔗 **Ссылка на подписку:**\n"
            f"```\n{sub_link}\n```\n"
            f"{count_info}\n"
            f"{stats_info}"
        )
        
        kb = types.InlineKeyboardMarkup()
        if content:
            kb.add(types.InlineKeyboardButton("📥 Скачать All Config", callback_data="get_all"))
        
        bot.edit_message_text(report, m.chat.id, status_msg.message_id, parse_mode='Markdown', reply_markup=kb)
    else:
        bot.edit_message_text("❌ Ошибка Sayori API (неверная ссылка?).", m.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "get_all")
def get_all(call):
    content = user_storage.get(call.message.chat.id)
    if not content:
        bot.answer_callback_query(call.id, "Данные пусты.")
        return
    
    is_json = content.strip().startswith('{') or content.strip().startswith('[')
    
    if not is_json:
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        content = "\n\n".join(lines)

    if 0 < len(content) < 3500:
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
