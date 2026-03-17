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
    except:
        return None

def extract_happ_raw(url):
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
        bot.reply_to(m, "❌ Ссылка не найдена в сообщении.")
        return

    # 1. Отправляем сообщение о начале работы
    status_msg = bot.reply_to(m, "⏳ *Расшифровываю...*", parse_mode='Markdown')
    
    decrypted_data = decrypt_via_api(happ_link)
    
    if decrypted_data and '://' in decrypted_data:
        # Чистим данные
        configs = [line.strip() for line in decrypted_data.split('\n') if '://' in line]
        # Сохраняем для кнопки (двойной перенос для удобства копирования)
        user_storage[m.chat.id] = "\n\n".join(configs)
        
        # Считаем статистику
        stats = {}
        for c in configs:
            proto = c.split('://')[0].upper()
            stats[proto] = stats.get(proto, 0) + 1
        
        stats_info = "\n".join([f"🔹 {k}: `{v}`" for k, v in stats.items()])
        report = (
            f"✅ **Успешно расшифровано!**\n\n"
            f"📊 Всего найдено: `{len(configs)}` конфигов\n"
            f"{stats_info}\n\n"
            f"Нажми кнопку ниже, чтобы получить готовый список."
        )
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📋 Показать конфиги", callback_data="get_data"))
        
        # 2. РЕДАКТИРУЕМ то же самое сообщение, заменяя "Расшифровываю" на результат
        bot.edit_message_text(report, m.chat.id, status_msg.message_id, parse_mode='Markdown', reply_markup=kb)
    else:
        bot.edit_message_text("❌ Ошибка: Не удалось расшифровать данные через API.", m.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "get_data")
def send_data(call):
    data = user_storage.get(call.message.chat.id)
    if data:
        # Если текста не слишком много для одного сообщения ТГ
        if len(data) < 3900:
            bot.send_message(call.message.chat.id, f"```\n{data}\n```", parse_mode='Markdown')
        else:
            # Если конфигов очень много — отправляем файлом
            with open("configs.txt", "w", encoding="utf-8") as f: f.write(data)
            bot.send_document(call.message.chat.id, open("configs.txt", "rb"), caption="🔥 Твой список конфигов")
        bot.answer_callback_query(call.id, "Список отправлен!")
    else:
        bot.answer_callback_query(call.id, "Данные не найдены, отправь ссылку заново.", show_alert=True)

bot.polling()
