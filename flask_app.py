from flask import Flask, request, redirect
import requests as tg_requests
from bs4 import BeautifulSoup
import time
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from pymongo import MongoClient, UpdateOne

app = Flask(__name__)

# ================= НАСТРОЙКИ =================
TOKEN = "8718984140:AAG5A6qMHlzGicaYUdDvgHx0Po5kKNIs55I"
CHAT_IDS = ["617384936", "960647529"]
MY_CHAT_ID = "617384936"

# Твой адрес на Render
HOST_URL = "https://flask-app-pych.onrender.com"

SHAFA_URLS = [
    "https://shafa.ua/uk/clothes?brands=4&price_to=800&search_text=%D0%BE%D0%BB%D1%96%D0%BC%D0%BF%D1%96%D0%B9%D0%BA%D0%B0&sort=4",
]

# Вставь сюда свой реальный адрес кластера и пароль от MongoDB
MONGO_URI = "mongodb+srv://waano2467_db_user:cMrOuT98pswQRhQT@cluster0.kgfz64m.mongodb.net/?appName=Cluster0"

# Вставь сюда свой ключ от ScraperAPI
SCRAPER_API_KEY = "94489c57d7aac6605ef978a93c277b0b"
# =============================================

client = MongoClient(MONGO_URI)
db = client["shafa_db"]
collection = db["seen_ads"]

def load_seen():
    seen = {}
    for doc in collection.find():
        seen[doc["_id"]] = doc["price"]
    return seen

def save_seen_batch(new_data_dict):
    operations = []
    for ad_id, price in new_data_dict.items():
        operations.append(UpdateOne({"_id": ad_id}, {"$set": {"price": price}}, upsert=True))
    
    if operations:
        collection.bulk_write(operations)

def send_telegram_ad(ad):
    is_discount = ad.get('is_discount')
    
    if is_discount:
        caption = f"📉 <b>Зниження ціни на Шафі!</b>\n\n🛍 <b>{ad['title']}</b>\n❌ Стара ціна: <s>{ad['old_price']}</s>\n✅ Нова ціна: {ad['price']}"
    else:
        caption = f"🔥 <b>Нова річ на Шафі!</b>\n\n🛍 <b>{ad['title']}</b>\n💰 {ad['price']}"
        
    short_title = quote(ad['title'][:25])
    safe_url = quote(ad['url'])

    cached_file_id = None
    photo_to_send = ad.get('image')

    for chat_id in CHAT_IDS:
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
                    result_data = response.json()
                    
                    if not cached_file_id and current_photo and 'photo' in result_data.get('result', {}):
                        cached_file_id = result_data['result']['photo'][-1]['file_id']
                    
                    time.sleep(1.5) 
                    
                elif response.status_code == 429:
                    retry_after = response.json().get('parameters', {}).get('retry_after', 3)
                    time.sleep(retry_after)
                else:
                    photo_to_send = None 

            except Exception:
                time.sleep(2)

            attempts += 1

def fetch_single_url(target_url):
    found_items = []
    
    # Запрос идет через прокси-сервер ScraperAPI с включенным рендерингом JS (render=true)
    # Добавлен параметр &premium=true для обхода жесткой защиты
    api_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target_url}&render=true&premium=true"
    
    try:
        # Таймаут увеличен, так как загрузка полноценного браузера занимает больше времени
        response = tg_requests.get(api_url, timeout=60)
        print("===== ОТВЕТ ШАФЫ =====")
        print(response.text[:1000]) # Выведет первые 1000 символов страницы
        print("======================")
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
            img_url = (img_tag.get('data-src') or img_tag.get('src')) if img_tag else None

            if ad_id:
                found_items.append({
                    'id': ad_id, 'url': item_url, 'title': title, 
                    'price': price, 'image': img_url
                })
    except Exception as e:
        print(f"Ошибка при сборе данных: {e}")
        pass
        
    return found_items

@app.route('/go')
def go_link():
    target_url = request.args.get('url')
    user_id = request.args.get('user')
    title = request.args.get('title', 'Товар')
    
    user_name = "Дівчина" if user_id == "960647529" else "Ти"
    
    notify_text = f"✅ <b>{user_name}</b> перейшла на Шафу дивитися:\n<i>{title}...</i>"
    tg_requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": MY_CHAT_ID, "text": notify_text, "parse_mode": "HTML"}
    )
    
    if target_url:
        return redirect(target_url)
    return "Посилання не знайдено", 404

@app.route('/')
def index():
    return "🟢 Бот активен! База MongoDB подключена. ScraperAPI готов."

@app.route('/run_bot')
def run_scraper():
    seen_ads = load_seen()
    is_first_run = len(seen_ads) == 0
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
                
                ad_id_in_seen = ad_id in seen_ads
                price_changed = ad_id_in_seen and seen_ads[ad_id] != current_price

                if not ad_id_in_seen:
                    ad['is_discount'] = False
                elif price_changed:
                    ad['is_discount'] = True
                    ad['old_price'] = seen_ads[ad_id]
                
                if not ad_id_in_seen or price_changed:
                    messages_to_send.append(ad)
                    new_data_to_save[ad_id] = current_price
                    seen_ads[ad_id] = current_price

    if total_parsed_items == 0:
        tg_requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": MY_CHAT_ID, "text": "⚠️ <b>Алярм! Парсер осліп.</b>\nМожливо, закінчилися ліміти ScraperAPI або змінилася верстка сайту.", "parse_mode": "HTML"}
        )
        return "Парсер ослеп", 500

    save_seen_batch(new_data_to_save)

    if is_first_run: 
        return "Первый запуск: база сохранена."

    for ad in messages_to_send:
        send_telegram_ad(ad)
        time.sleep(1)

    return f"✅ Завершено. Собрано: {total_parsed_items}. Уведомлений: {len(messages_to_send)}"
