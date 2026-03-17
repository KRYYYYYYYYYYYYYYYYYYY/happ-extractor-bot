import os
import telebot
import requests
import re
from urllib.parse import unquote

# Берем токен из секретов GitHub (или Environment Variables на сервере)
TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)

def extract_happ_raw(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        # Получаем содержимое страницы
        response = requests.get(url, headers=headers, timeout=10)
        
        # Если это прямая ссылка в параметрах редиректа
        if 'to=happ://' in response.url:
            return unquote(response.url.split('to=')[1])

        html = response.text
        # Ищем паттерн happ://crypt...
        raw_match = re.search(r'happ://crypt\d/[^"\'\s<>]+', html)
        
        if raw_match:
            return raw_match.group(0)

        return None
    except Exception as e:
        return f"Ошибка при запросе: {e}"

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Привет! Пришли мне ссылку от Happ (atlanta-subs и др.), а я вытащу из неё RAW-код для дешифратора.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.strip()
    
    # 1. Если пользователь прислал уже готовую ссылку happ://
    if text.startswith('happ://'):
        bot.reply_to(message, f"Это уже извлеченная ссылка. Кидай её в дешифратор:\n\n`{text}`", parse_mode='Markdown')
        return

    # 2. Проверка, что прислали именно ссылку http
    if not text.startswith('http'):
        bot.reply_to(message, "Это не похоже на ссылку. Пришли URL, начинающийся с http или https.")
        return

    bot.send_chat_action(message.chat.id, 'typing')
    
    # Извлекаем RAW ссылку
    result = extract_happ_raw(text)

    if result and result.startswith('happ://'):
        # Успешно нашли
        bot.reply_to(message, f"✅ Ссылка извлечена:\n\n`{result}`", parse_mode='Markdown')
    elif result and "Ошибка" in result:
        # Выводим ошибку запроса, если она была
        bot.reply_to(message, f"❌ {result}")
    else:
        # Если ничего не нашли
        bot.reply_to(message, "❌ Не удалось найти зашифрованную ссылку. Возможно, страница изменилась или ссылка протухла.")

print("Бот запущен...")
bot.polling()
