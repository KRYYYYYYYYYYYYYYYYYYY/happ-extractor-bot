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

def extract_links_from_json(json_text):
    """Парсит JSON и конвертирует outbounds в vless:// или ss:// ссылки."""
    links = []
    try:
        data = json.loads(json_text)
        # Если это конфиг типа "автовыбор", ищем внутри outbounds
        outbounds = data.get("outbounds", [])
        
        # Если outbounds пуст, возможно это просто одиночный объект сервера
        if not outbounds and data.get("protocol"):
            outbounds = [data]

        for out in outbounds:
            protocol = out.get("protocol")
            tag = out.get("tag", "node").replace(" ", "_")
            
            if protocol == "vless":
                try:
                    vnext = out["settings"]["vnext"][0]
                    user = vnext["users"][0]
                    addr = vnext["address"]
                    port = vnext["port"]
                    uuid = user["id"]
                    flow = user.get("flow", "")
                    
                    ss = out.get("streamSettings", {})
                    net = ss.get("network", "tcp")
                    sec = ss.get("security", "none")
                    
                    params = [f"type={net}", f"security={sec}"]
                    if flow: params.append(f"flow={flow}")
                    
                    if sec == "reality":
                        r_settings = ss.get("realitySettings", {})
                        params.append(f"sni={r_settings.get('serverName', '')}")
                        params.append(f"pbk={r_settings.get('publicKey', '')}")
                        params.append(f"sid={r_settings.get('shortId', '')}")
                        params.append(f"fp={r_settings.get('fingerprint', 'chrome')}")
                    
                    if net == "ws":
                        ws_settings = ss.get("wsSettings", {})
                        params.append(f"path={ws_settings.get('path', '/')}")
                        params.append(f"host={ws_settings.get('headers', {}).get('Host', '')}")
                    elif net == "grpc":
                        g_settings = ss.get("grpcSettings", {})
                        params.append(f"serviceName={g_settings.get('serviceName', '')}")

                    query = "&".join(params)
                    links.append(f"vless://{uuid}@{addr}:{port}?{query}#{tag}")
                except: continue

            elif protocol == "shadowsocks":
                try:
                    server = out["settings"]["servers"][0]
                    user_data = base64.b64encode(f"{server['method']}:{server['password']}".encode()).decode()
                    links.append(f"ss://{user_data}@{server['address']}:{server['port']}#{tag}")
                except: continue
                
    except: pass
    return links

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
        try:
            sub_res = requests.get(sub_link, headers={'User-Agent': random.choice(USER_AGENTS)}, timeout=15)
            if sub_res.status_code == 200:
                raw = sub_res.text.strip()
                try:
                    pad = len(raw) % 4
                    if pad: raw += '=' * (4 - pad)
                    content = base64.b64decode(raw).decode('utf-8', errors='ignore')
                except: content = raw
            else:
                bot.edit_message_text(f"❌ Ошибка сервера: {sub_res.status_code}", m.chat.id, status_msg.message_id)
                return
        except Exception as e:
            bot.edit_message_text(f"❌ Ошибка: {str(e)[:30]}", m.chat.id, status_msg.message_id)
            return

        all_links = []
        # 1. Обычные ссылки
        direct_links = [l.strip() for l in content.split('\n') if '://' in l and not l.strip().startswith('{')]
        all_links.extend(direct_links)
        
        # 2. Извлечение из JSON
        jsons = split_json_objects(content)
        for j_obj in jsons:
            all_links.extend(extract_links_from_json(j_obj))
        
        if not all_links:
            bot.edit_message_text("❌ Внутри подписки пусто.", m.chat.id, status_msg.message_id)
            return

        user_storage[m.chat.id] = "\n".join(all_links)
        
        stats = {}
        for l in all_links:
            proto = l.split('://')[0].upper()
            stats[proto] = stats.get(proto, 0) + 1
        stats_info = "\n".join([f"🔹 {k}: `{v}`" for k, v in stats.items()])

        report = (
            f"✅ **Готово!**\n\n"
            f"🚀 Всего серверов: `{len(all_links)} шт.`\n"
            f"📦 Распаковано JSON: `{len(jsons)}` объектов\n"
            f"━━━━━━━━━━━━━━━\n{stats_info}"
        )
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📥 Скачать All Config (.txt)", callback_data="get_all"))
        bot.edit_message_text(report, m.chat.id, status_msg.message_id, parse_mode='Markdown', reply_markup=kb)
    else:
        bot.edit_message_text("❌ Ошибка расшифровки.", m.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "get_all")
def get_all(call):
    content = user_storage.get(call.message.chat.id)
    if not content:
        bot.answer_callback_query(call.id, "Данные не найдены. Попробуй еще раз.")
        return
    
    # Отправляем текстовым файлом
    file_path = f"sub_{call.message.chat.id}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    with open(file_path, "rb") as f:
        bot.send_document(call.message.chat.id, f, caption="Все найденные конфиги (ссылки)")
    
    os.remove(file_path)
    bot.answer_callback_query(call.id)

bot.polling()
