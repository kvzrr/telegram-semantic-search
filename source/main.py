import json
import pandas as pd
from pathlib import Path
import torch

# --- ИСПРАВЛЕНИЕ ПУТЕЙ ---
BASE_DIR = Path(__file__).resolve().parent.parent


def extract_text(text_obj):
    if isinstance(text_obj, str):
        return text_obj
    elif isinstance(text_obj, list):
        extracted = []
        for item in text_obj:
            if isinstance(item, str):
                extracted.append(item)
            elif isinstance(item, dict) and 'text' in item:
                extracted.append(item['text'])
        return "".join(extracted)
    return ""


def load_chat_history(json_path: str) -> pd.DataFrame:
    print(f"Читаем файл: {json_path}...")
    # json_path уже абсолютный (приходит из tg_downloader), но на всякий случай:
    base_dir = Path(json_path).parent

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    messages = data.get('messages', [])
    parsed_data = []

    for msg in messages:
        if msg.get('type') != 'message':
            continue

        msg_date = msg.get('date')
        sender = msg.get('from', 'Unknown')
        text = extract_text(msg.get('text', ''))

        media_path = msg.get('file') or msg.get('photo') or None
        media_type = msg.get('media_type')

        if media_path:
            full_path = base_dir / media_path
            media_path = str(full_path)

        parsed_data.append({
            'date': msg_date,
            'sender': sender,
            'text': text,
            'media_type': media_type,
            'media_path': media_path
        })

    df = pd.DataFrame(parsed_data)
    df['date'] = pd.to_datetime(df['date'])
    return df


def transcribe_media(df: pd.DataFrame, model) -> pd.DataFrame:
    media_types_to_transcribe = ['voice_message', 'video_file', 'video_message']
    needs_transcription = df['media_type'].isin(media_types_to_transcribe)

    if not needs_transcription.any():
        return df

    print("Начинаем распознавание медиафайлов...")
    total_files = len(df[needs_transcription])
    current_file = 1

    for index, row in df[needs_transcription].iterrows():
        media_path = row['media_path']
        media_type = row['media_type']

        if pd.notna(media_path) and Path(media_path).exists():
            print(f"[{current_file}/{total_files}] Распознаем: {Path(media_path).name}...")
            try:
                result = model.transcribe(
                    media_path,
                    language="ru",
                    fp16=False,
                    initial_prompt="Переписка в мессенджере. Разговорный русский язык."
                )
                transcribed_text = result['text'].strip()
                prefix = "[Голосовое]" if media_type == 'voice_message' else "[Видео]"

                original_text = row['text']
                if original_text:
                    df.at[index, 'text'] = f"{original_text}\n{prefix}: {transcribed_text}"
                else:
                    df.at[index, 'text'] = f"{prefix}: {transcribed_text}"
            except Exception as e:
                print(f"Ошибка с файлом {Path(media_path).name}: {e}")

        current_file += 1
    return df


def clean_and_chunk(df: pd.DataFrame, time_window_minutes: int = 5) -> pd.DataFrame:
    print("\nОчистка и объединение сообщений (чанкинг)...")
    df = df[df['text'].str.strip() != ''].copy()
    df = df.sort_values('date').reset_index(drop=True)

    if df.empty:
        return df

    chunks = []
    current_chunk_text = [df.iloc[0]['text']]
    current_sender = df.iloc[0]['sender']
    current_date = df.iloc[0]['date']
    last_msg_date = df.iloc[0]['date']

    for i in range(1, len(df)):
        row = df.iloc[i]
        time_diff = (row['date'] - last_msg_date).total_seconds() / 60.0

        if row['sender'] == current_sender and time_diff <= time_window_minutes:
            current_chunk_text.append(row['text'])
            last_msg_date = row['date']
        else:
            chunks.append({
                'date': current_date,
                'sender': current_sender,
                'text': "\n".join(current_chunk_text)
            })
            current_chunk_text = [row['text']]
            current_sender = row['sender']
            current_date = row['date']
            last_msg_date = row['date']

    if current_chunk_text:
        chunks.append({
            'date': current_date,
            'sender': current_sender,
            'text': "\n".join(current_chunk_text)
        })

    chunked_df = pd.DataFrame(chunks)
    print(f"Было сообщений: {len(df)}, стало чанков: {len(chunked_df)}")
    return chunked_df


def generate_embeddings(df: pd.DataFrame, model) -> pd.DataFrame:
    print("Генерируем векторы для текстов...")
    texts_for_embedding = ["passage: " + text for text in df['text'].tolist()]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Используем устройство для векторов: {device}")

    embeddings = model.encode(texts_for_embedding, show_progress_bar=True, batch_size=32)
    df['embedding'] = embeddings.tolist()
    return df


def setup_chromadb(df: pd.DataFrame, collection_name: str):
    """
    Сохраняет данные в ChromaDB в корневой папке SST.
    """
    import chromadb

    # Указываем путь к базе в корне проекта
    db_path = str(BASE_DIR / "chroma_db")

    print(f"\nСохраняем в ChromaDB ({db_path}), коллекция: '{collection_name}'...")
    client = chromadb.PersistentClient(path=db_path)

    try:
        client.delete_collection(name=collection_name)
    except Exception:
        pass

    collection = client.create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})

    ids = [str(i) for i in range(len(df))]
    documents = df['text'].tolist()
    embeddings = df['embedding'].tolist()

    metadatas = []
    for _, row in df.iterrows():
        metadatas.append({
            "sender": row['sender'],
            "date": row['date'].strftime("%Y-%m-%d %H:%M:%S")
        })

    batch_size = 5000
    total_docs = len(documents)
    for i in range(0, total_docs, batch_size):
        end = min(i + batch_size, total_docs)
        collection.add(
            ids=ids[i:end],
            embeddings=embeddings[i:end],
            documents=documents[i:end],
            metadatas=metadatas[i:end]
        )

    print("Данные успешно сохранены!")
    return collection