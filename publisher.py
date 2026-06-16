import requests
import os

KEY = os.getenv("SQUARE_API")

def publish(text):

    url = "https://www.binance.com/bapi/composite/v1/public/pgc/openApi/content/add"

    payload = {
        "bodyTextOnly": text
    }

    headers = {
        "X-Square-OpenAPI-Key": KEY,
        "clienttype": "binanceSkill",
        "Content-Type": "application/json"
    }

    r = requests.post(url, headers=headers, json=payload)

    print("STATUS:", r.status_code)
    print("RESPONSE:", r.text)

    return r.text
