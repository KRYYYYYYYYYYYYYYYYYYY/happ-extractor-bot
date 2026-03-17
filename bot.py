import os
import telebot
import requests
import re
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
        return None
    except: return None

def extract_happ_raw(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
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

    status_msg = bot.reply_to(m, "⏳ *Расшифровываю...*", parse_mode='Markdown')
    decrypted_data = decrypt_via_api(happ_link)
    
    if decrypted_data:
        # 1. Ссылка на подписку (то, что мы получили от API)
        subscription_link = decrypted_data.strip()
        
        # 2. Идем по ссылке подписки, чтобы узнать, что ВНУТРИ (кол-во серверов)
        try:
            # Пытаемся скачать содержимое подписки для анализа
            sub_res = requests.get(subscription_link, timeout=10)
            internal_content = sub_res.text
            # Если там Base64 (часто бывает), пробуем декодировать для статистики
            import base64
            try:
                internal_content = base64.b64decode(internal_content).decode('utf-8')
            except: pass
            
            configs = [line.strip() for line in internal_content.split('\n') if '://' in line]
        except:
            configs = []

        user_storage[m.chat.id] = configs # Сохраняем список серверов
        
        # Считаем протоколы внутри
        stats = {}
        for c in configs:
            proto = c.split('://')[0].upper()
            stats[proto] = stats.get(proto, 0) + 1
        
        stats_info = "\n".join([f"🔹 {k}: `{v}`" for k, v in stats.items()]) if stats else "🔹 Протоколы: `Не удалось определить`"
        
        # ФОРМИРУЕМ СООБЩЕНИЕ
        report = (
            f"✅ **Готово!**\n\n"
            f"🔗 **Ссылка на подписку:**\n"
            f"```\n{subscription_link}\n```\n" # Ссылка, которую удобно скопировать
            f"📊 **Внутри найдено серверов:** `{len(configs)}`\n"
            f"{stats_info}"
        )
        
        kb = types.InlineKeyboardMarkup()
        if configs:
            kb.add(types.InlineKeyboardButton("✂️ Конфиги по отдельности", callback_data="get_sep"))
            kb.add(types.InlineKeyboardButton("📦 All Configs (одним файлом)", callback_data="get_all"))
        
        bot.edit_message_text(report, m.chat.id, status_msg.message_id, parse_mode='Markdown', reply_markup=kb)
    else:
        bot.edit_message_text("❌ Ошибка дешифровки через Sayori API.", m.chat.id, status_msg.message_id)

# Обработчики кнопок (остаются такими же, как в прошлом шаге)
@bot.callback_query_handler(func=lambda c: c.data == "get_sep")
def get_sep(call):
    configs = user_storage.get(call.message.chat.id)
    if not configs: return
    text = "📝 **Конфиги по отдельности (первые 20):**\n\n"
    for c in configs[:20]:
        text += f"```\n{c}\n```\n"
    bot.send_message(call.message.chat.id, text, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "get_all")
def get_all(call):
    configs = user_storage.get(call.message.chat.id)
    if not configs: return
    full_text = "\n".join(configs)
    file_path = f"configs_{call.message.chat.id}.txt"
    with open(file_path, "w", encoding="utf-8") as f: f.write(full_text)
    with open(file_path, "rb") as f:
        bot.send_document(call.message.chat.id, f, caption="📂 Все конфиги одним файлом")
    os.remove(file_path)
    bot.answer_callback_query(call.id)

bot.polling()
