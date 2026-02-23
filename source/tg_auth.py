from telethon.sync import TelegramClient

# ВАЖНО: Замени эти значения на свои с сайта my.telegram.org
API_ID = 30929887  # Твой api_id (это должно быть целое число, без кавычек)
API_HASH = 'f9fb136e3edc87faffe94cdac65af924'

print("Подключаемся к Telegram...")

# 'my_account' - это название файла сессии.
# Telethon создаст файл my_account.session, чтобы не просить код при каждом запуске.
with TelegramClient('my_account', API_ID, API_HASH) as client:
    print("✅ Успешная авторизация!")

    print("\nТвои последние 10 диалогов:")
    # Получаем список диалогов (чатов, каналов, личных переписок)
    for dialog in client.iter_dialogs(limit=10):
        # Выводим название чата и его уникальный ID
        print(f"- {dialog.name} (ID: {dialog.id})")