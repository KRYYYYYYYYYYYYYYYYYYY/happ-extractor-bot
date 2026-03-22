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
import cloudscraper


TOKEN = os.getenv('TELEGRAM_TOKEN')
SAYORI_KEY = os.getenv('SAYORI_KEY')

bot = telebot.TeleBot(TOKEN)
user_storage = {}

USER_AGENTS = [
    'v2rayNG/1.8.5 (com.v2ray.ang; build 100805; Android 13)',
    'ClashforWindows/0.20.39',
    'Clash-verge/1.3.8',
    'Shadowrocket/2.2.38 (iPhone; iOS 17.0.1; Scale/3.00)',
    'Quantumult%20X/1.4.3 (iPhone; iOS 17.0.1; Scale/3.00)',
    'Stash/2.4.5 (iPhone; iOS 17.0.1; Scale/3.00)'
]

NODE_PATTERN = re.compile(r'(?:vless|vmess|ss|trojan|shadowsocks|tuic|hysteria2?)://[^\s\r\n"\'<>]+', re.IGNORECASE)
HTTP_PATTERN = re.compile(r'https?://[^\s\r\n"\'<>]+', re.IGNORECASE)
BASE64_PATTERN = re.compile(r'^[A-Za-z0-9+/=_-]{24,}$')

def decrypt_via_api(happ_link):
    api_url = "https://api.sayori.cc/v1/decrypt"
    headers = {"Content-Type": "application/json", "x-api-key": SAYORI_KEY}
    payload = {"link": happ_link.strip()}
    try:
        res = requests.post(api_url, json=payload, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            if data.get("success"):
                return data.get("result")
    except Exception as e:
        print(f"Decrypt Error: {e}")
    return None

def extract_happ(text):
    decoded = unquote(text)
    match = re.search(r'happ://(crypt\d?)/[^\s"\'<>]+', decoded)
    if match:
        return match.group(0), match.group(1)
    return None, None

def try_decode_base64(value):
    raw = ''.join(value.split())
    if not raw or len(raw) < 24:
        return None

    if raw.startswith(('http://', 'https://', 'happ://')):
        return None

    if not BASE64_PATTERN.fullmatch(raw):
        return None

    # URL-safe base64 тоже поддерживаем
    raw = raw.replace('-', '+').replace('_', '/')
    raw += '=' * ((4 - len(raw) % 4) % 4)

    try:
        decoded = base64.b64decode(raw, validate=False).decode('utf-8', errors='ignore').strip()
        if decoded and decoded != value:
            return decoded
    except Exception:
        return None
    return None


def looks_like_json(text):
    clean = text.strip()
    return (clean.startswith('{') and clean.endswith('}')) or (clean.startswith('[') and clean.endswith(']'))


def json_to_links_candidates(payload):
    links = []

    # Поддержка Clash/Mihomo: proxies[].server + port
    if isinstance(payload, dict) and isinstance(payload.get('proxies'), list):
        for proxy in payload['proxies']:
            if not isinstance(proxy, dict):
                continue
            server = proxy.get('server')
            port = proxy.get('port')
            ptype = str(proxy.get('type', 'proxy')).lower()
            name = proxy.get('name', 'proxy')
            if server and port:
                links.append(f"{ptype}://{server}:{port}#{name}")

    # Поддержка Xray/Sing-box: outbounds[].settings.vnext
    if isinstance(payload, dict) and isinstance(payload.get('outbounds'), list):
        for outbound in payload['outbounds']:
            if not isinstance(outbound, dict):
                continue
            protocol = str(outbound.get('protocol', '')).lower()
            settings = outbound.get('settings', {})
            if not isinstance(settings, dict):
                continue
            vnext = settings.get('vnext')
            if isinstance(vnext, list):
                for item in vnext:
                    if not isinstance(item, dict):
                        continue
                    address = item.get('address')
                    port = item.get('port')
                    users = item.get('users') if isinstance(item.get('users'), list) else []
                    uid = users[0].get('id') if users and isinstance(users[0], dict) else ''
                    if protocol in ('vless', 'vmess') and address and port and uid:
                        links.append(f"{protocol}://{uid}@{address}:{port}")

    return links


def extract_from_json_text(text):
    try:
        data = json.loads(text)
    except Exception:
        return [], []

    discovered_texts = []
    links = []

    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, str):
            s = value.strip()
            if s:
                discovered_texts.append(s)
                links.extend(NODE_PATTERN.findall(s))

    walk(data)
    links.extend(json_to_links_candidates(data))
    return discovered_texts, links


def find_hidden_links(url):
    try:
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return None, None

        html_content = res.text

        happ_link, crypt_ver = extract_happ(html_content)
        if happ_link:
            return happ_link, crypt_ver

        # Пытаемся найти полезные URL напрямую
        url_candidates = HTTP_PATTERN.findall(html_content)
        if url_candidates:
            return url_candidates[0], None

        # Иногда подписка/base64 спрятана в JS строках
        for quoted in re.findall(r'"([A-Za-z0-9+/=_-]{60,})"', html_content):
            decoded = try_decode_base64(quoted)
            if not decoded:
                continue
            happ_link, crypt_ver = extract_happ(decoded)
            if happ_link:
                return happ_link, crypt_ver
            
            found_http = HTTP_PATTERN.findall(decoded)
            if found_http:
                return found_http[0], None
    except Exception:
        pass
    return None, None

def analyze_subscription_content(content, max_depth=5):
    queue = [(content, 0)]
    seen = set()
    links = []
    nested_urls = []
    json_like_found = False

    while queue:
        chunk, depth = queue.pop(0)
        if depth > max_depth:
            continue

        normalized = chunk.strip()
        if not normalized:
            continue

        cache_key = f"{depth}:{hash(normalized)}"
        if cache_key in seen:
            continue
        seen.add(cache_key)

        links.extend(NODE_PATTERN.findall(normalized))

        http_links = HTTP_PATTERN.findall(normalized)
        if http_links:
            nested_urls.extend(http_links)

        if looks_like_json(normalized):
            json_like_found = True
            found_texts, json_links = extract_from_json_text(normalized)
            links.extend(json_links)
            for txt in found_texts:
                if txt not in (normalized,):
                    queue.append((txt, depth + 1))

        decoded = try_decode_base64(normalized)
        if decoded:
            queue.append((decoded, depth + 1))

        # Матрёшка: URL-encoded payload
        if '%' in normalized:
            unquoted = unquote(normalized)
            if unquoted != normalized:
                queue.append((unquoted, depth + 1))

    dedup_links = list(dict.fromkeys(links))
    dedup_nested = list(dict.fromkeys(nested_urls))
    return dedup_links, dedup_nested, json_like_found


def fetch_url_content(scraper, url_to_try):
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/plain, application/json, */*'
    }

    last_error = None
    for attempt in range(3):
        try:
            res = scraper.get(url_to_try, headers=headers, timeout=15, allow_redirects=True)
            # Сервис может временно возвращать 5xx
            if res.status_code >= 500:
                last_error = f"HTTP_{res.status_code}"
                time.sleep(0.8 * (attempt + 1))
                continue

            if res.status_code == 200:
                text = res.text.strip()
                if text:
                    return text, None
            last_error = f"HTTP_{res.status_code}"
        except Exception as e:
            last_error = f"Error:{str(e)[:40]}"
            time.sleep(0.8 * (attempt + 1))

    return "", last_error

@bot.message_handler(func=lambda m: True)
def handle_message(m):
    text = m.text.strip()
    if text.startswith('/'):
        return

    happ_link, crypt_ver = extract_happ(text)
    target_url = happ_link if happ_link else (text if text.startswith('http') else None)

    if not target_url:
        bot.reply_to(m, "❌ Ссылка не распознана.")
        return

    status_msg = bot.reply_to(m, "⏳ **Анализ ссылки...**", parse_mode='Markdown')
    
    if target_url.startswith('http') and not happ_link:
        hidden_url, hidden_crypt = find_hidden_links(target_url)
        if hidden_url:
            target_url = hidden_url
            crypt_ver = hidden_crypt

    process_link(m.chat.id, target_url, status_msg.message_id, crypt_ver)

def process_link(chat_id, target_url, message_id, crypt_ver=None):
    final_url = target_url
    
    # Не расшифровываем то, что уже явно декодировано (не happ)
    if target_url.startswith('happ://'):
        decrypted = decrypt_via_api(target_url)
        if not decrypted:
            bot.edit_message_text("❌ Ошибка: Не удалось расшифровать happ-ссылку.", chat_id, message_id)
            return
        final_url = decrypted

    proxy_url = f"https://s.sayori.cc/{final_url}" if final_url.startswith('http') else final_url
    
    if chat_id not in user_storage:
        user_storage[chat_id] = {}
    user_storage[chat_id]['last_url'] = target_url
    user_storage[chat_id]['crypt_ver'] = crypt_ver

    fetch_and_report(chat_id, final_url, proxy_url, message_id)


def fetch_and_report(chat_id, original_url, proxy_url, message_id):
    content = ""
    error_code = None
    
    scraper = cloudscraper.create_scraper()
    
    for url_to_try in [proxy_url, original_url]:
        content, error_code = fetch_url_content(scraper, url_to_try)
        if not content:
            continue

        if "<html" in content.lower() or "<!doctype" in content.lower():
            # Если пришла HTML, пытаемся вытащить оттуда ссылку и сходить ещё раз
            hidden_url, _ = find_hidden_links(url_to_try)
            if hidden_url and hidden_url != url_to_try:
                content, error_code = fetch_url_content(scraper, hidden_url)
                if content and "<html" not in content[:200].lower():
                    break
            continue
        break

    if not content:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Повторить", callback_data="retry_last"))
        bot.edit_message_text(
            f"❌ Не удалось получить данные подписки.\nКод/причина: `{error_code or 'unknown'}`",
            chat_id,
            message_id,
            reply_markup=kb,
            parse_mode='Markdown'
        )
        return

    links, nested_urls, json_like_found = analyze_subscription_content(content)

    if links:
        final_data = "\n".join(links)
        decode_state = "раскрыта"
    else:
        final_data = content
        decode_state = "не раскрыта"

    user_storage[chat_id]['content'] = final_data
    
    user_storage[chat_id]['last_report'] = {
        'nodes': len(links),
        'nested_urls': len(nested_urls),
        'json_mode': json_like_found,
        'decode_state': decode_state
    }
    crypt_type = user_storage[chat_id].get('crypt_ver') or "auto/web"
    cjson_note = "да" if json_like_found else "нет"
    
    report = (
        "✅ **Данные получены**\n"
        f"🔑 Тип обработки: `{crypt_type}`\n"
        f"🧩 JSON обнаружен: `{json_note}`\n"
        f"🔓 Состояние: `{decode_state}`\n\n"
        f"🔗 **Источник:**\n`{original_url}`\n\n"
        f"🌐 **Прокси:**\n`{proxy_url}`\n\n"
        f"📦 Вложенных URL найдено: `{len(nested_urls)}`\n"
        f"📊 Найдено узлов: `{len(links)}`"
    )
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📥 Скачать файл", callback_data="get_all"))
    kb.add(types.InlineKeyboardButton("🔄 Повторить", callback_data="retry_last"))

    bot.edit_message_text(
        report,
        chat_id,
        message_id,
        parse_mode='Markdown',
        reply_markup=kb,
        disable_web_page_preview=True
    )
    
@bot.callback_query_handler(func=lambda c: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    if call.data == "get_all":
        data = user_storage.get(chat_id, {}).get('content')
        if not data:
            bot.answer_callback_query(call.id, "Данные устарели.")
            return
        
        ext = "json" if '"outbounds"' in data else "txt"
        file_name = f"config_{chat_id}.{ext}"
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(data)
        with open(file_name, "rb") as f:
            bot.send_document(chat_id, f, caption="📄 Расшифрованный конфиг")
        os.remove(file_name)
        bot.answer_callback_query(call.id, "Файл отправлен")
        
    elif call.data == "retry_last":
        last_url = user_storage.get(chat_id, {}).get('last_url')
        crypt_ver = user_storage.get(chat_id, {}).get('crypt_ver')
        if last_url:
            bot.answer_callback_query(call.id, "Обновляю...")
            process_link(chat_id, last_url, call.message.message_id, crypt_ver)
        else:
            bot.answer_callback_query(call.id, "Нет ссылки для повтора")


bot.polling(none_stop=True)
