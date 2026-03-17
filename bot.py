import os
import telebot
import requests
import re
from urllib.parse import unquote
from telebot import types

# Берем токены из секретов GitHub
TOKEN = os.getenv('TELEGRAM_TOKEN')
SAYORI_KEY = os.getenv('SAYORI_KEY') # Твой новый API ключ

bot = telebot.TeleBot(TOKEN)
user_storage = {}

def decrypt_via_api(happ_link):
    """Дешифровка через официальное API v1 Sayori по инструкции"""
    # Новый точный адрес из доков
    api_url = "https://api.sayori.cc/v1/decrypt"
    
    # Заголовки: тип контента и твой x-api-key
    headers = {
        "Content-Type": "application/json",
        "x-api-key": SAYORI_KEY
    }
    
    # Тело запроса: ключ должен называться 'link'
    payload = {
        "link": happ_link
    }
    
    try:
        # Отправляем POST с JSON
        response = requests.post(api_url, json=payload, headers=headers, timeout=15)
        
        if response.status_code == 200:
            result_json = response.json()
            # Согласно докам, ответ приходит в поле 'result'
            if result_json.get("success"):
                return result_json.get("result", "Ошибка: Поле result пустое")
            else:
                return f"❌ Ошибка API: success=false. Проверь ссылку."
        
        elif response.status_code == 401:
            return "❌ Ошибка: Неверный x-api-key. Проверь секреты в GitHub."
        else:
            return f"❌ Ошибка API {response.status_code}: {response.text[:100]}"
            
    except Exception as e:
        return f"❌ Ошибка запроса: {e}"

def extract_happ_raw(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        # 1. Проверяем саму входящую ссылку (декодируем %3A и т.д.)
        url_decoded = unquote(url)
        if 'happ://' in url_decoded:
            match = re.search(r'happ://crypt\d/[^"\'\s<>]+', url_decoded)
            if match: return match.group(0)

        # 2. Делаем запрос (allow_redirects=True по умолчанию)
        res = requests.get(url, headers=headers, timeout=10)
        
        # 3. Проверяем финальный URL после всех редиректов (часто ссылка там)
        final_url_decoded = unquote(res.url)
        if 'happ://' in final_url_decoded:
            match = re.search(r'happ://crypt\d/[^"\'\s<>]+', final_url_decoded)
            if match: return match.group(0)

        # 4. Проверяем исходный код страницы (view-source)
        match = re.search(r'happ://crypt\d/[^"\'\s<>]+', res.text)
        if match:
            return match.group(0)
            
        return None
    except Exception as e:
        print(f"Ошибка при извлечении: {e}")
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
        bot.reply_to(m, "❌ Ссылка не найдена. Пришли URL страницы или happ:// ссылку.")
        return

    bot.send_chat_action(m.chat.id, 'typing')
    
    # Отправляем на расшифровку с твоим ключом
    decrypted_data = decrypt_via_api(happ_link)
    
    if '://' in decrypted_data:
        total, stats, content = analyze_configs(decrypted_data)
        user_storage[m.chat.id] = content
        
        stats_info = "\n".join([f"🔹 {k}: `{v}`" for k, v in stats.items()])
        report = (
            f"✅ **Расшифровано через Sayori API!**\n\n"
            f"📊 Всего конфигов: `{total}`\n"
            f"{stats_info}"
        )
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📥 Показать конфиги", callback_data="get_data"))
        bot.send_message(m.chat.id, report, parse_mode='Markdown', reply_markup=kb)
    else:
        bot.reply_to(m, f"❌ Не удалось расшифровать:\n`{decrypted_data}`")

@bot.callback_query_handler(func=lambda c: c.data == "get_data")
def send_data(call):
    data = user_storage.get(call.message.chat.id)
    if data:
        if len(data) < 3800:
            bot.send_message(call.message.chat.id, f"```\n{data}\n```", parse_mode='Markdown')
        else:
            with open("out.txt", "w", encoding="utf-8") as f: f.write(data)
            bot.send_document(call.message.chat.id, open("out.txt", "rb"), caption="Твои конфиги")
    else:
        bot.answer_callback_query(call.id, "Данные устарели, отправь ссылку заново.")

bot.polling()
