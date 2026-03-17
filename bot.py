import os
import telebot
import requests
import re
from urllib.parse import unquote

# Вставь сюда свой токен от @BotFather
TOKEN = os.getenv('TELEGRAM_TOKEN') # Берем токен из секретов GitHub
bot = telebot.TeleBot(TOKEN)

def extract_happ_raw(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        # 1. Получаем HTML страницы
        response = requests.get(url, headers=headers, timeout=10)
        html = response.text

        # 2. Ищем переменную const RAW в скрипте
        # Она может быть как в коде страницы, так и в URL (если это редирект)
        raw_match = re.search(r'const RAW\s*=\s*"(happ://crypt\d/[^"]+)"', html)
        
        if raw_match:
            return raw_match.group(1)
        
        # 3. Если в HTML нет, проверяем, не перекинуло ли нас в URL с параметром to=
        if 'to=' in response.url:
            encoded_part = response.url.split('to=')[1]
            return unquote(encoded_part)

        return None
    except Exception as e:
        return f"Ошибка: {e}"

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Пришли мне короткую ссылку Happ (например, с сайта atlanta-subs), и я вытащу из неё RAW код!")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()
    
    # Проверка, что это ссылка
    if not url.startswith('http'):
        bot.reply_to(message, "Это не похоже на ссылку. Пришли URL.")
        return

    bot.send_chat_action(message.chat.id, 'typing')
    result = extract_happ_raw(url)

    if result:
        # Отправляем результат в моноширинном шрифте, чтобы удобно было копировать
        bot.reply_to(message, f"✅ Ссылка извлечена:\n\n`{result}`", parse_mode='Markdown')
    else:
        bot.reply_to(message, "❌ Не удалось найти зашифрованную ссылку в этом URL. Возможно, она уже не работает или там другой формат.")

print("Бот запущен...")
bot.polling()
