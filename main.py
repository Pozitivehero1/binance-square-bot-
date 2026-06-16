from publisher import publish

print("BOT STARTED")

text = """
Тестовый пост.

Если вы видите этот пост, значит API публикации работает.

#BTC #Crypto
"""

response = publish(text)

print("DONE")
