import requests
import os

KEY = os.getenv("SQUARE_API")

def publish(text):

    url = "https://www.binance.com/bapi/composite/v1/public/pgc/openApi/content/add"

    requests.post(url, headers={
        "X-Square-OpenAPI-Key": KEY,
        "clienttype": "binanceSkill",
        "Content-Type": "application/json"
    }, json={
        "bodyTextOnly": text
    })
