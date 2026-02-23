import json
import os
from pathlib import Path
from telethon import TelegramClient

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.json"


def get_api_credentials():
    """Получает ключи из файла настроек"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("API_ID"), data.get("API_HASH")
    return None, None


async def get_dialogs(client, limit=15):
    dialogs = []
    async for dialog in client.iter_dialogs(limit=limit):
        if dialog.name:
            dialogs.append({"name": dialog.name, "id": dialog.id})
    return dialogs


async def download_history(client, chat_id, chat_name, limit=50):
    print(f"\nНачинаем скачивание из диалога: {chat_name} ({chat_id})...")

    safe_folder_name = f"chat_{chat_id}"
    export_dir = BASE_DIR / "ChatExport_Auto" / safe_folder_name
    export_dir.mkdir(parents=True, exist_ok=True)

    messages_data = []

    async for msg in client.iter_messages(chat_id, limit=limit):
        if not msg.text and not msg.media:
            continue

        sender = await msg.get_sender()
        sender_name = "Unknown"
        if sender:
            if hasattr(sender, 'first_name') and sender.first_name:
                sender_name = sender.first_name
            elif hasattr(sender, 'title'):
                sender_name = sender.title

        msg_dict = {
            "type": "message",
            "date": msg.date.isoformat() if msg.date else None,
            "from": sender_name,
            "text": msg.text or "",
            "file": None,
            "media_type": None
        }

        if msg.media:
            if getattr(msg, 'voice', False):
                path = await client.download_media(msg, file=str(export_dir / "voice_messages" / ""))
                msg_dict["file"] = os.path.relpath(path, str(export_dir)) if path else None
                msg_dict["media_type"] = "voice_message"

            elif getattr(msg, 'video_note', False):
                path = await client.download_media(msg, file=str(export_dir / "round_video_messages" / ""))
                msg_dict["file"] = os.path.relpath(path, str(export_dir)) if path else None
                msg_dict["media_type"] = "video_message"

            elif getattr(msg, 'video', False):
                path = await client.download_media(msg, file=str(export_dir / "video_files" / ""))
                msg_dict["file"] = os.path.relpath(path, str(export_dir)) if path else None
                msg_dict["media_type"] = "video_file"

        messages_data.append(msg_dict)

    messages_data.reverse()

    result_json = {"messages": messages_data}
    json_path = export_dir / "result.json"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result_json, f, ensure_ascii=False, indent=4)

    print(f"\n✅ Готово! Данные сохранены в: {export_dir}")
    return str(json_path)