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
    
    if decrypted_data and '://' in decrypted_data:
        configs = [line.strip() for line in decrypted_data.split('\n') if '://' in line]
        user_storage[m.chat.id] = configs # Храним как список
        
        stats = {}
        for c in configs:
            proto = c.split('://')[0].upper()
            stats[proto] = stats.get(proto, 0) + 1
        
        stats_info = "\n".join([f"🔹 {k}: `{v}`" for k, v in stats.items()])
        report = f"✅ **Готово!**\n\n📊 Найдено: `{len(configs)}` конфигов\n{stats_info}"
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⚙️ Дополнительно", callback_data="menu_extra"))
        
        bot.edit_message_text(report, m.chat.id, status_msg.message_id, parse_mode='Markdown', reply_markup=kb)
    else:
        bot.edit_message_text("❌ Ошибка дешифровки.", m.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "menu_extra")
def menu_extra(call):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✂️ По отдельности", callback_data="get_sep"))
    kb.add(types.InlineKeyboardButton("📦 All Config (одним файлом/блоком)", callback_data="get_all"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="menu_back"))
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "get_sep")
def get_sep(call):
    configs = user_storage.get(call.message.chat.id)
    if not configs: return
    
    # Выводим первые 10-15 для примера, чтобы не спамить
    text = "📝 **Конфиги по отдельности:**\n\n"
    for c in configs[:20]: # Ограничим 20 штуками в одном сообщении для чистоты
        text += f"```\n{c}\n```\n"
    
    if len(configs) > 20:
        text += f"\n_...и еще {len(configs)-20} конфигов. Для полного списка используй 'All Config'_"
        
    bot.send_message(call.message.chat.id, text, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "get_all")
def get_all(call):
    configs = user_storage.get(call.message.chat.id)
    if not configs: return
    
    full_text = "\n".join(configs)
    
    if len(full_text) < 3800:
        bot.send_message(call.message.chat.id, f"```\n{full_text}\n```", parse_mode='Markdown')
    else:
        # Решаем проблему лимитов через файл
        file_path = f"configs_{call.message.chat.id}.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        
        with open(file_path, "rb") as f:
            bot.send_document(call.message.chat.id, f, caption="📂 Все конфиги в одном файле. Его можно импортировать в V2Ray/Nekobox.")
        os.remove(file_path) # Удаляем временный файл
        
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "menu_back")
def menu_back(call):
    # Тут можно вернуть старую клавиатуру с кнопкой "Дополнительно"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⚙️ Дополнительно", callback_data="menu_extra"))
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=kb)
    bot.answer_callback_query(call.id)

bot.polling()
