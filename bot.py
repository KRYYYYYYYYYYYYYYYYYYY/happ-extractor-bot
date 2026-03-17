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
    links = []
    try:
        data = json.loads(json_text)
        # Ищем везде: в outbounds и просто в корне (на случай если это одиночный конфиг)
        outbounds = data.get("outbounds", [])
        if not outbounds and data.get("protocol"):
            outbounds = [data]

        for out in outbounds:
            protocol = out.get("protocol")
            # Пропускаем технические протоколы, которые не являются серверами
            if protocol not in ["vless", "vmess", "shadowsocks", "trojan"]:
                continue
                
            tag = out.get("tag", "node").replace(" ", "_")
            
            try:
                # Пытаемся достать основные данные сервера
                settings = out.get("settings", {})
                vnext = settings.get("vnext", [])
                
                # Если vnext пуст (как в балансировщиках), пропускаем этот блок
                if not vnext:
                    continue
                
                server_info = vnext[0]
                user = server_info.get("users", [{}])[0]
                addr = server_info.get("address")
                port = server_info.get("port")
                uuid = user.get("id")
                
                if not all([addr, port, uuid]): # Если критических данных нет - в топку
                    continue

                # Сбор параметров транспорта
                ss = out.get("streamSettings", {})
                net = ss.get("network", "tcp")
                sec = ss.get("security", "none")
                
                params = [f"type={net}", f"security={sec}"]
                
                # Добавляем Flow (для Vision)
                if user.get("flow"): params.append(f"flow={user['flow']}")

                # Reality
                if sec == "reality":
                    r = ss.get("realitySettings", {})
                    params.append(f"sni={r.get('serverName', '')}")
                    params.append(f"pbk={r.get('publicKey', '')}")
                    params.append(f"sid={r.get('shortId', '')}")
                    params.append(f"fp={r.get('fingerprint', 'chrome')}")
                
                # TLS/XTLS
                elif sec in ["tls", "xtls"]:
                    t = ss.get("tlsSettings", {}) or ss.get("xtlsSettings", {})
                    params.append(f"sni={t.get('serverName', '')}")

                # WebSocket / gRPC
                if net == "ws":
                    ws = ss.get("wsSettings", {})
                    params.append(f"path={ws.get('path', '/')}")
                    params.append(f"host={ws.get('headers', {}).get('Host', '')}")
                elif net == "grpc":
                    params.append(f"serviceName={ss.get('grpcSettings', {}).get('serviceName', '')}")

                query = "&".join(params)
                links.append(f"{protocol}://{uuid}@{addr}:{port}?{query}#{tag}")
                
            except Exception as e:
                print(f"Ошибка парсинга блока: {e}")
                continue
                
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
            # Имитируем запрос от v2rayNG максимально точно
            sub_headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': '*/*',
                'Connection': 'keep-alive',
                'Accept-Language': 'en-US,en;q=0.9',
            }
            
            # Небольшая пауза, чтобы сервер не принял нас за спам-бота
            time.sleep(random.uniform(1.0, 2.5)) 
            
            # Делаем запрос
            sub_res = requests.get(sub_link, headers=sub_headers, timeout=20, verify=True)
            
            if sub_res.status_code == 200:
                raw = sub_res.text.strip()
                # Пытаемся понять, это Base64 или чистый текст/JSON
                try:
                    # Убираем возможные невидимые символы, которые мешают Base64
                    clean_raw = re.sub(r'[^a-zA-Z0-9+/=]', '', raw)
                    pad = len(clean_raw) % 4
                    if pad: clean_raw += '=' * (4 - pad)
                    content = base64.b64decode(clean_raw).decode('utf-8', errors='ignore')
                except:
                    content = raw
            elif sub_res.status_code == 500:
                bot.edit_message_text("⚠️ Сервер подписки выдал ошибку 500. Возможно, стоит попробовать позже или сменить IP бота.", m.chat.id, status_msg.message_id)
                return
            else:
                bot.edit_message_text(f"❌ Ошибка сервера: {sub_res.status_code}", m.chat.id, status_msg.message_id)
                return
        except Exception as e:
            bot.edit_message_text(f"❌ Сетевая ошибка: {str(e)[:40]}", m.chat.id, status_msg.message_id)
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
