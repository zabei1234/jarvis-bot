import requests

url = "https://api.dexscreener.com/latest/dex/pairs"

print("🔄 Тестируем Dex Screener API...")

response = requests.get(url)

if response.status_code == 200:
    data = response.json()

    if "pairs" in data and len(data["pairs"]) > 0:
        print("✅ API работает!\n")
        print("🔥 Трендовые пары на DEX:")
        for pair in data["pairs"][:5]:
            print(f"🔹 Пара: {pair['baseToken']['symbol']}/{pair['quoteToken']['symbol']}")
            print(f"💰 Цена: {pair['priceUsd']} USD")
            print(f"📊 Объём 24ч: {pair['volume']['h24']} USD")
            print(f"🕒 Ликвидность: {pair['liquidity']['usd']} USD")
            print(f"🔗 Dex Screener: {pair['url']}")
            print("-" * 40)
    else:
        print("❌ API вернул пустые данные.")

else:
    print(f"❌ Ошибка {response.status_code}: {response.text}")
