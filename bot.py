import os
import telebot
import requests
import re
import subprocess
from urllib.parse import unquote
from telebot import types

# Настройки
TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)

# Временное хранилище конфигов (чтобы не гонять дешифратор дважды)
user_storage = {}

def extract_happ_raw(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        # 1. Декодируем саму входящую ссылку (на случай, если happ:// зашито внутри как параметр)
        decoded_url = unquote(url)
        
        # 2. Если в декодированном URL уже есть happ://, забираем его сразу
        if 'happ://' in decoded_url:
            # Ищем начало happ:// и берем всё до конца или до кавычки/пробела
            start_index = decoded_url.find('happ://')
            # Вырезаем кусок, убирая возможный мусор в конце
            raw_from_url = re.split(r'["\'\s<>]', decoded_url[start_index:])[0]
            return raw_from_url

        # 3. Если в URL не нашли, идем на саму страницу
        response = requests.get(url, headers=headers, timeout=10)
        
        # Проверяем финальный URL после всех редиректов (тоже декодируем)
        final_url = unquote(response.url)
        if 'happ://' in final_url:
            start_index = final_url.find('happ://')
            return re.split(r'["\'\s<>]', final_url[start_index:])[0]

        # Ищем в HTML коде страницы
        html = response.text
        raw_match = re.search(r'happ://crypt\d/[^"\'\s<>]+', html)
        if raw_match:
            return raw_match.group(0)
            
        return None
    except Exception as e:
        return f"Ошибка при запросе: {e}"

def decrypt_link(happ_link):
    """Запускает твой Go-дешифратор и возвращает результат"""
    try:
        # Запускаем бинарник. Важно: ./decoder должен быть в корне репозитория
        result = subprocess.run(['./decoder', happ_link], capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return result.stdout.strip()
        return f"Ошибка дешифратора: {result.stderr}"
    except Exception as e:
        return f"Ошибка запуска: {e}"

def analyze_configs(raw_text):
    """Считает количество и все возможные типы конфигов"""
    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
    # Словарь для сбора статистики
    stats = {}
    
    for line in lines:
        # Извлекаем название протокола до символов ://
        protocol_match = re.match(r'^([a-zA-Z0-9]+)://', line.lower())
        if protocol_match:
            proto = protocol_match.group(1).upper() # Получаем например 'VLESS' или 'HY2'
            stats[proto] = stats.get(proto, 0) + 1
        else:
            stats["UNKNOWN"] = stats.get("UNKNOWN", 0) + 1
    
    return len(lines), stats, lines

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Пр!")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.strip()
    
    # Если прислали сразу happ:// или ссылку http://
    happ_link = text if text.startswith('happ://') else extract_happ_raw(text)

    if not happ_link or "Ошибка" in str(happ_link):
        bot.reply_to(message, "❌ Не удалось найти или извлечь ссылку.")
        return

    bot.send_chat_action(message.chat.id, 'typing')
    
    # Дешифруем
    decrypted_data = decrypt_link(happ_link)
    
    if "vless://" in decrypted_data or "vmess://" in decrypted_data or "ss://" in decrypted_data:
        total, stats, configs_list = analyze_configs(decrypted_data)
        
        # Сохраняем в память (ключ - ID сообщения, чтобы не путать пользователей)
        user_storage[message.chat.id] = decrypted_data
        
        # Формируем отчет
        types_str = ", ".join([f"{k}: {v}" for k, v in stats.items() if v > 0])
        report = (
            f"✅ **Данные расшифрованы!**\n\n"
            f"📊 Всего конфигов: `{total}`\n"
            f"⚙️ Типы: `{types_str}`\n"
            f"🔗 Формат: Ссылки"
        )
        
        # Кнопка
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📥 Получить конфиги", callback_data="get_configs"))
        
        bot.send_message(message.chat.id, report, parse_mode='Markdown', reply_markup=markup)
    else:
        bot.reply_to(message, f"❌ Ошибка дешифровки:\n`{decrypted_data[:100]}`", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == "get_configs")
def send_configs(call):
    configs = user_storage.get(call.message.chat.id)
    if configs:
        # Если текста слишком много (лимит ТГ 4096 символов), отправляем файлом
        if len(configs) < 3500:
            bot.send_message(call.message.chat.id, f"```\n{configs}\n```", parse_mode='Markdown')
        else:
            with open("configs.txt", "w", encoding="utf-8") as f:
                f.write(configs)
            bot.send_document(call.message.chat.id, open("configs.txt", "rb"), caption="Твои конфиги")
    else:
        bot.answer_callback_query(call.id, "Конфиги не найдены. Попробуй отправить ссылку заново.")

print("Бот запущен...")
bot.polling()
