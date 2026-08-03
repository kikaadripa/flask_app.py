from flask import Flask, request, redirect
import requests as tg_requests
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
import os
import time
import random
import json
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# ================= НАСТРОЙКИ =================
TOKEN = "8718984140:AAG5A6qMHlzGicaYUdDvgHx0Po5kKNIs55I"
CHAT_IDS = ["617384936", "960647529"]
MY_CHAT_ID = "617384936"

# Твой адрес на PythonAnywhere (замени ТВОЙ_ЛОГИН на реальный)
HOST_URL = "https://flask-app-pych.onrender.com"

SHAFA_URLS = [
    "https://shafa.ua/uk/clothes?brands=4&price_to=800&search_text=%D0%BE%D0%BB%D1%96%D0%BC%D0%BF%D1%96%D0%B9%D0%BA%D0%B0&sort=4",
]

DB_FILE = os.path.join(os.path.dirname(__file__), "seen_shafa.json")
# =============================================

def load_seen():
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_seen_batch(new_data_dict):
    if not new_data_dict:
        return
    seen = load_seen()
    seen.update(new_data_dict)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)

def send_telegram_ad(ad):
    if ad.get('is_discount'):
        caption = f"📉 <b>Зниження ціни на Шафі!</b>\n\n🛍 <b>{ad['title']}</b>\n❌ Стара ціна: <s>{ad['old_price']}</s>\n✅ Нова ціна: {ad['price']}"
    else:
        caption = f"🔥 <b>Нова річ на Шафі!</b>\n\n🛍 <b>{ad['title']}</b>\n💰 {ad['price']}"
        
    short_title = quote(ad['title'][:25])
    safe_url = quote(ad['url'])

    cached_file_id = None
    photo_to_send = ad.get('image')

    for chat_id in CHAT_IDS:
        # Генерируем персональную ссылку для каждого пользователя
        redirect_link = f"{HOST_URL}/go?url={safe_url}&user={chat_id}&title={short_title}"
        
        reply_markup = {
            "inline_keyboard": [
                [{"text": "🛒 Перейти на Шафу", "url": redirect_link}]
            ]
        }

        success = False
        attempts = 0

        while not success and attempts < 3:
            try:
                current_photo = cached_file_id if cached_file_id else photo_to_send
                
                payload = {
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup
                }

                if current_photo:
                    payload["photo"] = current_photo
                    response = tg_requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", json=payload, timeout=20)
                else:
                    payload["text"] = caption
                    payload["disable_web_page_preview"] = False
                    response = tg_requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json=payload, timeout=20)

                if response.status_code == 200:
                    success = True
                    if not cached_file_id and current_photo:
                        result_data = response.json()
                        if 'photo' in result_data.get('result', {}):
                            cached_file_id = result_data['result']['photo'][-1]['file_id']
                    
                    time.sleep(1.5) 
                    
                elif response.status_code == 429:
                    retry_after = response.json().get('parameters', {}).get('retry_after', 3)
                    time.sleep(retry_after)
                else:
                    photo_to_send = None 

            except Exception as e:
                time.sleep(2)

            attempts += 1

def fetch_single_url(target_url):
    found_items = []
    try:
        time.sleep(random.uniform(0.1, 1.5)) 
        response = curl_requests.get(target_url, impersonate="chrome110", timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')

        items = soup.find_all('li', class_='catalog-item')

        for item in items:
            link_tag = item.find('a', class_='catalog-item__link')
            price_tag = item.find('div', class_='catalog-item__price')
            img_tag = item.find('img', class_='catalog-item__img')
            
            if not link_tag or not price_tag:
                continue

            item_url = "https://shafa.ua" + link_tag['href']
            ad_id = item_url.split('-')[0].split('/')[-1]
            price = price_tag.text.strip()
            
            title = img_tag.get('alt', 'Річ').strip() if img_tag else "Річ"
            img_url = None
            if img_tag:
                img_url = img_tag.get('data-src') or img_tag.get('src')

            if ad_id:
                found_items.append({
                    'id': ad_id, 'url': item_url, 'title': title, 
                    'price': price, 'image': img_url
                })
    except Exception:
        pass
        
    return found_items

# ================= МАРШРУТ ПЕРЕАДРЕСАЦИИ (ТРЕКИНГ КЛИКОВ) =================
@app.route('/go')
def go_link():
    target_url = request.args.get('url')
    user_id = request.args.get('user')
    title = request.args.get('title', 'Товар')
    
    # Определяем, кто именно нажал на ссылку
    user_name = "Дівчина" if user_id == "960647529" else "Ти"
    
    # Отправляем уведомление тебе
    notify_text = f"✅ <b>{user_name}</b> перейшла на Шафу дивитися:\n<i>{title}...</i>"
    tg_requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": MY_CHAT_ID, "text": notify_text, "parse_mode": "HTML"}
    )
    
    # Моментально перекидываем пользователя на страницу товара
    if target_url:
        return redirect(target_url)
    return "Посилання не знайдено", 404

# =========================================================================

@app.route('/')
def index():
    return "🟢 Бот активен! База данных подключена."

@app.route('/run_bot')
def run_scraper():
    seen_ads = load_seen()
    messages_to_send = []
    new_data_to_save = {}
    total_parsed_items = 0

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_url = {executor.submit(fetch_single_url, url): url for url in SHAFA_URLS}
        
        for future in as_completed(future_to_url):
            items = future.result()
            total_parsed_items += len(items)
            
            for ad in items:
                ad_id = ad['id']
                current_price = ad['price']
                
                if ad_id not in seen_ads:
                    ad['is_discount'] = False
                    messages_to_send.append(ad)
                    new_data_to_save[ad_id] = current_price
                    seen_ads[ad_id] = current_price 
                
                elif seen_ads[ad_id] != current_price:
                    ad['is_discount'] = True
                    ad['old_price'] = seen_ads[ad_id]
                    messages_to_send.append(ad)
                    new_data_to_save[ad_id] = current_price
                    seen_ads[ad_id] = current_price

    if total_parsed_items == 0:
        warning_msg = "⚠️ <b>Алярм! Парсер осліп.</b>\nШафа заблокувала IP або змінилась верстка сайту."
        tg_requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": MY_CHAT_ID, "text": warning_msg, "parse_mode": "HTML"}
        )
        return "Парсер ослеп", 500

    save_seen_batch(new_data_to_save)

    if not load_seen(): 
        return "Первый запуск: база сохранена."

    for ad in messages_to_send:
        send_telegram_ad(ad)
        time.sleep(1)

    return f"✅ Завершено. Собрано: {total_parsed_items}. Уведомлений: {len(messages_to_send)}"
