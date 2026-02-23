import streamlit as st
import asyncio
import threading
import chromadb
import whisper
import os
import json
from pathlib import Path
from telethon import TelegramClient, errors
from sentence_transformers import SentenceTransformer, CrossEncoder

from tg_downloader import get_api_credentials, get_dialogs, download_history
from main import load_chat_history, clean_and_chunk, setup_chromadb, transcribe_media, generate_embeddings

BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_FILE_PATH = str(BASE_DIR / 'my_account')
CHATS_REGISTRY_FILE = str(BASE_DIR / "downloaded_chats.json")
DB_PATH = str(BASE_DIR / "chroma_db")
CONFIG_FILE = str(BASE_DIR / "config.json")

st.set_page_config(page_title="Семантический поиск", page_icon="🔍", layout="wide")
st.markdown(
    """<style>[data-testid="stStatusWidget"] {visibility: hidden;} .stDeployButton {display:none;} footer {visibility: hidden;}</style>""",
    unsafe_allow_html=True)


# --- ФОНОВЫЙ ПОТОК ---
@st.cache_resource
def get_background_loop():
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    return loop


bg_loop = get_background_loop()


def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, bg_loop).result()


# --- ЭКРАН ПЕРВОНАЧАЛЬНОЙ НАСТРОЙКИ (ДЛЯ НОВИЧКОВ) ---
def setup_page():
    st.title("⚙️ Первоначальная настройка")
    st.markdown("""
    Добро пожаловать! Для работы приложения необходимо подключить его к Telegram.
    Это делается один раз. Ваши данные хранятся **только на вашем компьютере**.

    ### Как получить ключи:
    1. Перейдите на официальный сайт: [my.telegram.org](https://my.telegram.org)
    2. Авторизуйтесь по своему номеру телефона.
    3. Нажмите на **API development tools**.
    4. Заполните форму (можно написать любые слова на английском в первые два поля, платформу выберите Desktop).
    5. Скопируйте **App api_id** и **App api_hash** и вставьте их ниже.
    """)

    api_id = st.text_input("Введите API ID (только цифры):")
    api_hash = st.text_input("Введите API HASH (строка из букв и цифр):", type="password")

    if st.button("Сохранить и продолжить", type="primary"):
        if api_id.isdigit() and len(api_hash) > 10:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"API_ID": int(api_id), "API_HASH": api_hash.strip()}, f)
            st.success("Настройки сохранены!")
            st.rerun()
        else:
            st.error("Пожалуйста, проверьте правильность введенных данных.")


# Проверяем, есть ли настройки
API_ID, API_HASH = get_api_credentials()

if not API_ID or not API_HASH:
    setup_page()
    st.stop()  # Останавливаем выполнение остального кода, пока нет ключей


# --- ГЛОБАЛЬНЫЙ КЛИЕНТ ---
@st.cache_resource
def get_global_client():
    async def _create_client():
        client = TelegramClient(SESSION_FILE_PATH, API_ID, API_HASH, loop=bg_loop)
        await client.connect()
        return client

    return run_async(_create_client())


tg_client = get_global_client()


# --- ЛОГИКА АВТОРИЗАЦИИ ---
def check_auth():
    try:
        return run_async(tg_client.is_user_authorized())
    except Exception:
        return False


async def send_code_async(phone):
    sent = await tg_client.send_code_request(phone)
    return sent.phone_code_hash


async def sign_in_async(phone, code, phone_hash):
    try:
        await tg_client.sign_in(phone=phone, code=code, phone_code_hash=phone_hash)
        return "success"
    except errors.SessionPasswordNeededError:
        return "password_needed"


async def sign_in_2fa_async(password):
    await tg_client.sign_in(password=password)
    return True


# --- ЭКРАН АВТОРИЗАЦИИ ---
def auth_page():
    st.title("🔐 Вход в Telegram")
    if 'auth_step' not in st.session_state:
        st.session_state.auth_step = 'phone'

    if st.session_state.auth_step == 'phone':
        phone = st.text_input("Введите номер телефона", placeholder="+79991234567")
        if st.button("Получить код"):
            with st.spinner("Отправка запроса..."):
                try:
                    phone_hash = run_async(send_code_async(phone))
                    st.session_state.phone = phone
                    st.session_state.phone_hash = phone_hash
                    st.session_state.auth_step = 'code'
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка: {e}")

    elif st.session_state.auth_step == 'code':
        st.info(f"Код отправлен на {st.session_state.phone}")
        code = st.text_input("Введите код из Telegram", type="password")
        if st.button("Войти"):
            with st.spinner("Проверка..."):
                try:
                    res = run_async(sign_in_async(st.session_state.phone, code, st.session_state.phone_hash))
                    if res == "success":
                        st.rerun()
                    elif res == "password_needed":
                        st.session_state.auth_step = 'password'
                        st.rerun()
                except Exception as e:
                    st.error(f"Ошибка: {e}")

    elif st.session_state.auth_step == 'password':
        st.warning("Введите облачный пароль (2FA)")
        password = st.text_input("Пароль", type="password")
        if st.button("Подтвердить"):
            with st.spinner("Вход..."):
                try:
                    run_async(sign_in_2fa_async(password))
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка: {e}")


# --- ОСНОВНОЕ ПРИЛОЖЕНИЕ ---
def main_app():
    with st.sidebar:
        st.write(f"✅ Вы авторизованы")
        if st.button("Выйти из аккаунта"):
            run_async(tg_client.log_out())
            session_file = BASE_DIR / 'my_account.session'
            if session_file.exists(): os.remove(session_file)
            st.rerun()

    @st.cache_resource
    def load_ml_models():
        bi_model = SentenceTransformer('intfloat/multilingual-e5-base')
        cross_model = CrossEncoder('BAAI/bge-reranker-v2-m3')
        whisper_model = whisper.load_model("small")
        return bi_model, cross_model, whisper_model

    @st.cache_resource
    def load_db():
        return chromadb.PersistentClient(path=DB_PATH)

    def load_chats():
        if os.path.exists(CHATS_REGISTRY_FILE):
            with open(CHATS_REGISTRY_FILE, "r", encoding="utf-8") as f: return json.load(f)
        return {}

    def save_chat(chat_id, chat_name):
        chats = load_chats()
        chats[str(chat_id)] = chat_name
        with open(CHATS_REGISTRY_FILE, "w", encoding="utf-8") as f: json.dump(chats, f, ensure_ascii=False, indent=4)

    with st.spinner("Загрузка нейросетей..."):
        bi_model, cross_model, whisper_model = load_ml_models()
        db_client = load_db()

    st.sidebar.title("📥 Загрузка")

    @st.cache_data(ttl=300)
    def fetch_dialogs_cached(_client_dummy, limit):
        return run_async(get_dialogs(tg_client, limit))

    try:
        dialogs = fetch_dialogs_cached("dummy", 100)
        dialog_dict = {d['name']: d['id'] for d in dialogs if d['name']}

        sel_chat = st.sidebar.selectbox("Диалог:", list(dialog_dict.keys()))
        limit = st.sidebar.slider("Лимит сообщений:", 100, 10000, 500)

        if st.sidebar.button("Скачать"):
            chat_id = dialog_dict[sel_chat]
            col_name = f"chat_{chat_id}"

            with st.status(f"Обработка: {sel_chat}", expanded=True) as status:
                st.write("⬇️ Скачивание...")
                json_path = run_async(download_history(tg_client, chat_id, sel_chat, limit))
                st.write("📂 Чтение...")
                df = load_chat_history(json_path)
                st.write("🎙 Whisper...")
                df = transcribe_media(df, whisper_model)
                st.write("🧹 Чанкинг...")
                df = clean_and_chunk(df)
                st.write("🧠 Векторы...")
                df = generate_embeddings(df, bi_model)
                st.write("💾 База...")
                setup_chromadb(df, col_name)

                save_chat(chat_id, sel_chat)
                status.update(label="Готово!", state="complete", expanded=False)
                st.rerun()
    except Exception as e:
        st.sidebar.error(f"Ошибка связи: {e}")

    st.title("🔍 Поиск")
    chats = load_chats()

    if not chats:
        st.info("Скачайте чат в меню слева.")
    else:
        chat_opts = {name: cid for cid, name in chats.items()}
        c1, c2 = st.columns([1, 3])
        with c1:
            target_name = st.selectbox("Где искать?", list(chat_opts.keys()))
        with c2:
            query = st.text_input("Запрос", placeholder="Что ищем?")

        if query and target_name:
            cid = chat_opts[target_name]
            col_name = f"chat_{cid}"
            try:
                coll = db_client.get_collection(col_name)
                count = coll.count()
            except:
                count = 0

            if count > 0:
                with st.spinner("Поиск..."):
                    q_emb = bi_model.encode(["query: " + query]).tolist()
                    res = coll.query(query_embeddings=q_emb, n_results=min(30, count))

                    docs = res['documents'][0]
                    metas = res['metadatas'][0]

                    if docs:
                        cross_inp = [[query, d] for d in docs]
                        scores = cross_model.predict(cross_inp)

                        final = []
                        for i in range(len(docs)):
                            final.append({'txt': docs[i], 'meta': metas[i], 'sc': scores[i]})

                        final.sort(key=lambda x: x['sc'], reverse=True)

                        st.success(f"Найдено: {len(final[:5])}")
                        for item in final[:5]:
                            icon = "🔥" if item['sc'] > 0.5 else "📄"
                            with st.chat_message("user", avatar=icon):
                                st.markdown(f"**{item['meta']['sender']}** • {item['meta']['date']}")
                                st.write(item['txt'])
            else:
                st.warning("Чат пуст.")


if __name__ == "__main__":
    if check_auth():
        main_app()
    else:
        auth_page()