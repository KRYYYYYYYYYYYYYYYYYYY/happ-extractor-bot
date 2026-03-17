import os
import telebot
import requests
import re
import base64
from urllib.parse import unquote
from telebot import types

TOKEN = os.getenv('TELEGRAM_TOKEN')
SAYORI_KEY = os.getenv('SAYORI_KEY')

bot = telebot.TeleBot(TOKEN)
user_storage = {}

def decrypt_via_api(happ_link):
    api_url = "https://api.sayori.cc/v1/decrypt"
    headers = {"Content-Type": "application/json", "x-api-key": SAYORI_KEY}
    payload = {"link": happ_link}
    try:
        res = requests.post(api_url, json=payload, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data.get("result") if data.get("success") else None
    except: return None

def extract_happ_raw(url):
    # Здесь браузерный агент уместен, так как мы смотрим страницу-инструкцию
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
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

    status_msg = bot.reply_to(m, "⏳ *Расшифровываю и лезу внутрь подписки...*", parse_mode='Markdown')
    decrypted_url = decrypt_via_api(happ_link)
    
    if decrypted_url:
        subscription_link = decrypted_url.strip()
        configs = []

        # ВОТ ТУТ МЫ ПРИКИДЫВАЕМСЯ ВПН-КЛИЕНТОМ
        try:
            sub_headers = {
                'User-Agent': 'v2rayNG/1.8.5 (com.v2ray.ang; build 100805; Android 13)',
                'Accept': '*/*',
            }
            sub_res = requests.get(subscription_link, headers=sub_headers, timeout=12)
            
            if sub_res.status_code == 200:
                raw_content = sub_res.text.strip()
                # Декодируем Base64
                try:
                    missing_padding = len(raw_content) % 4
                    if missing_padding: raw_content += '=' * (4 - missing_padding)
                    internal_content = base64.b64decode(raw_content).decode('utf-8', errors='ignore')
                except:
                    internal_content = raw_content
                
                configs = [line.strip() for line in internal_content.split('\n') if '://' in line]
        except: pass

        user_storage[m.chat.id] = configs
        stats = {}
        for c in configs:
            proto = c.split('://')[0].upper()
            stats[proto] = stats.get(proto, 0) + 1
        
        stats_info = "\n".join([f"🔹 {k}: `{v}`" for k, v in stats.items()]) if stats else "🔹 Внутри: `Доступ заблокирован сервером`"
        
        report = (
            f"✅ **Готово!**\n\n"
            f"🔗 **Ссылка на подписку:**\n"
            f"```\n{subscription_link}\n```\n"
            f"📊 **Внутри найдено серверов:** `{len(configs)}`\n"
            f"{stats_info}"
        )
        
        kb = types.InlineKeyboardMarkup()
        if configs:
            kb.add(types.InlineKeyboardButton("✂️ По отдельности", callback_data="get_sep"))
            kb.add(types.InlineKeyboardButton("📦 All Configs (.txt)", callback_data="get_all"))
        
        bot.edit_message_text(report, m.chat.id, status_msg.message_id, parse_mode='Markdown', reply_markup=kb)
    else:
        bot.edit_message_text("❌ Ошибка Sayori API.", m.chat.id, status_msg.message_id)

# (Обработчики кнопок get_sep и get_all остаются без изменений)
@bot.callback_query_handler(func=lambda c: c.data == "get_sep")
def get_sep(call):
    configs = user_storage.get(call.message.chat.id, [])
    if not configs: return
    text = "📝 **Конфиги (топ 20):**\n\n"
    for c in configs[:20]: text += f"```\n{c}\n```\n"
    bot.send_message(call.message.chat.id, text, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "get_all")
def get_all(call):
    configs = user_storage.get(call.message.chat.id, [])
    if not configs: return
    full_text = "\n".join(configs)
    file_path = f"sub_{call.message.chat.id}.txt"
    with open(file_path, "w", encoding="utf-8") as f: f.write(full_text)
    with open(file_path, "rb") as f:
        bot.send_document(call.message.chat.id, f, caption="📂 Файл для импорта")
    if os.path.exists(file_path): os.remove(file_path)
    bot.answer_callback_query(call.id)

bot.polling()
