import requests
import pandas as pd
import time
import random

def get_product_info(product_id):
    url = f"https://catalog.wb.ru/catalog/{product_id}/detail.json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.wildberries.ru/",
        "Origin": "https://www.wildberries.ru",
        "Accept": "*/*",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site"
    }
    
    time.sleep(random.uniform(30, 45))  # Увеличенная задержка для обхода блокировок
    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Статус-код: {response.status_code}")
        if response.status_code != 200:
            return None
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при подключении: {e}")
        return None
    
    data = response.json()
    try:
        title = data["value"]["product"]["name"]
    except KeyError:
        title = "Не найдено"
    
    try:
        price = data["value"]["product"]["price"]
    except KeyError:
        price = "Не найдено"
    
    return {
        "Название": title,
        "Цена": price,
        "ID товара": product_id
    }

def parse_wildberries(product_ids):
    data = []
    for product_id in product_ids:
        info = get_product_info(product_id)
        if info:
            data.append(info)
        time.sleep(random.uniform(30, 45))  # Увеличенная пауза между запросами
    
    df = pd.DataFrame(data)
    print(df)
    return df

product_ids = [
    "63827491",
    "93378992"
]

df = parse_wildberries(product_ids)

