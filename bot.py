import os
import telebot
import requests
import re
from urllib.parse import unquote
from telebot import types

TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)

user_storage = {}

def decrypt_via_api(happ_link):
    """Отправляет ссылку на API Sayori для дешифровки"""
    api_url = "https://happ.sayori.cc/api/key"
    try:
        # Отправляем POST запрос с ссылкой
        response = requests.post(api_url, data={'key': happ_link}, timeout=15)
        if response.status_code == 200:
            return response.text.strip()
        else:
            return f"Ошибка API: Код {response.status_code}. Возможно, ссылка невалидна."
    except Exception as e:
        return f"Ошибка подключения к API: {e}"

def extract_happ_raw(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        url = unquote(url)
        if 'happ://' in url:
            return re.split(r'["\'\s<>]', url[url.find('happ://'):])[0]
        
        res = requests.get(url, headers=headers, timeout=10)
        raw_match = re.search(r'happ://crypt\d/[^"\'\s<>]+', res.text)
        return raw_match.group(0) if raw_match else None
    except:
        return None

def analyze_configs(raw_text):
    lines = [l.strip() for l in raw_text.split('\n') if '://' in l]
    stats = {}
    for line in lines:
        protocol = line.split('://')[0].upper()
        stats[protocol] = stats.get(protocol, 0) + 1
    return len(lines), stats, raw_text

@bot.message_handler(func=lambda m: True)
def handle_message(m):
    text = m.text.strip()
    happ_link = text if text.startswith('happ://') else extract_happ_raw(text)
    
    if not happ_link:
        bot.reply_to(m, "❌ Ссылка не найдена в сообщении.")
        return

    bot.send_chat_action(m.chat.id, 'typing')
    
    # Используем API вместо локального дешифратора
    decrypted_data = decrypt_via_api(happ_link)
    
    if '://' in decrypted_data:
        total, stats, content = analyze_configs(decrypted_data)
        user_storage[m.chat.id] = content
        
        # Красивый вывод типов
        stats_info = "\n".join([f"🔹 {k}: `{v}`" for k, v in stats.items()])
        report = (
            f"✅ **Успешно расшифровано через API!**\n\n"
            f"📊 Всего конфигов: `{total}`\n"
            f"{stats_info}"
        )
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📥 Получить все конфиги", callback_data="get_data"))
        bot.send_message(m.chat.id, report, parse_mode='Markdown', reply_markup=kb)
    else:
        bot.reply_to(m, f"❌ API не смогло расшифровать это:\n`{decrypted_data}`", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data == "get_data")
def send_data(call):
    data = user_storage.get(call.message.chat.id)
    if data:
        if len(data) < 3500:
            bot.send_message(call.message.chat.id, f"```\n{data}\n```", parse_mode='Markdown')
        else:
            with open("out.txt", "w", encoding="utf-8") as f: f.write(data)
            bot.send_document(call.message.chat.id, open("out.txt", "rb"), caption="Твои конфиги")
    else:
        bot.answer_callback_query(call.id, "Данные устарели.")

bot.polling()
