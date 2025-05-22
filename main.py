import os
import json
import logging
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart
from datetime import datetime
# Для работы с нейросетью
import requests

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)

# Environment variables
API_TOKEN = os.getenv('TELEGRAM_TOKEN')  # ваш токен бота
STORY_FILE = os.getenv('STORY_FILE', 'story.json')  # путь к JSON-сюжету
HF_API_URL = os.getenv('HF_API_URL')  # URL модели на Hugging Face Inference API
HF_API_TOKEN = os.getenv('HF_API_TOKEN')  # токен доступа к Hugging Face

# Validate required env vars
if not API_TOKEN:
    logging.error('Нет TELEGRAM_TOKEN в окружении')
    exit(1)
# Проверяем нейросеть
if not HF_API_URL or not HF_API_TOKEN:
    logging.warning('HF_API_URL или HF_API_TOKEN не заданы, функция ИИ будет недоступна')

# Initialize bot and storage
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Load story definition from JSON file
def load_story(path: str) -> dict:
    if not os.path.exists(path):
        logging.error(f'Файл сюжета не найден: {path}')
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

story = load_story(STORY_FILE)

# FSM state for the entire quest
class QuestStates(StatesGroup):
    IN_QUEST = State()

# Build reply keyboard for a node
def build_keyboard(node_id: str) -> types.ReplyKeyboardMarkup:
    buttons = [types.KeyboardButton(text=choice['text']) for choice in story.get(node_id, {}).get('choices', [])]
    return types.ReplyKeyboardMarkup(keyboard=[[b] for b in buttons], resize_keyboard=True)

# Интеграция с Hugging Face Inference API для итогов и контрфактов
async def ai_insights(summary_text: str) -> str:
    if not HF_API_URL or not HF_API_TOKEN:
        return 'ИИ-аналитика недоступна.'
    prompt = (
        f"Подведи итоги следующей истории:\n{summary_text}\n"
        "Затем спрогнозируй, что могло бы произойти иначе при другом развитии событий."
    )
    headers = {
        'Authorization': f'Bearer {HF_API_TOKEN}',
        'Content-Type': 'application/json'
    }
    payload = {'inputs': prompt, 'options': {'wait_for_model': True}}
    response = requests.post(HF_API_URL, headers=headers, json=payload, timeout=30)
    if response.status_code == 200:
        data = response.json()
        return data[0]['generated_text'] if isinstance(data, list) else data.get('generated_text', '')
    else:
        logging.error(f"Ошибка HF API: {response.status_code} {response.text}")
        return 'Не удалось получить ИИ-аналитику.'

# Send a story node to user
async def send_node(user_id: int, node_id: str, state: FSMContext):
    node = story.get(node_id)
    if not node:
        await bot.send_message(user_id, "Ошибка: узел истории не найден. Квест будет перезапущен.", reply_markup=types.ReplyKeyboardRemove())
        from aiogram.types import Message
        mock_message = Message(
            message_id=0,
            date=datetime.now(),
            chat=types.Chat(id=user_id, type='private'),
            from_user=types.User(id=user_id, is_bot=False, first_name="Пользователь"),
            text="Начать сначала"
        )
        await cmd_start(mock_message, state)
        return
    # Send image if specified
    img_path = node.get('image')
    if img_path and os.path.exists(img_path):
        await bot.send_photo(user_id, photo=open(img_path, 'rb'))

    # Send text and keyboard
    reply_markup = build_keyboard(node_id) if node.get('choices') else types.ReplyKeyboardRemove()
    await bot.send_message(
        user_id,
        node.get('text', ''),
        reply_markup=reply_markup
    )
    await state.set_state(QuestStates.IN_QUEST)

# Handler for /start
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await state.update_data(history=[], current_node='start')
    await send_node(message.from_user.id, 'start', state)

# Handler for any choice by text
@dp.message(QuestStates.IN_QUEST)
async def process_choice(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current_node = data.get('current_node')
    node = story.get(current_node, {})
    choices = node.get('choices', [])
    selected = next((i for i, c in enumerate(choices) if c['text'] == message.text), None)
    if selected is None:
        await message.answer("Пожалуйста, выберите вариант из предложенных.")
        return

    choice = choices[selected]
    history = data.get('history', [])
    history.append({'node': current_node, 'choice': choice['text']})
    await state.update_data(history=history)

    next_id = choice.get('next')
    if next_id == 'END':
        await send_summary(message.chat.id, state)
    else:
        await state.update_data(current_node=next_id)
        await send_node(message.chat.id, next_id, state)

# Summary at end
async def send_summary(user_id: int, state: FSMContext):
    data = await state.get_data()
    history = data.get('history', [])
    summary = 'Ваш итог путешествия по квесту:\n'
    for entry in history:
        node_text = story.get(entry['node'], {}).get('text', '')
        summary += f"- {node_text}\n  -> Вы выбрали: {entry['choice']}\n"

    await bot.send_message(user_id, summary, reply_markup=types.ReplyKeyboardRemove())
    insights = await ai_insights(summary)
    await bot.send_message(user_id, insights, reply_markup=types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="Начать сначала")]], resize_keyboard=True
    ))
    await state.clear()

# Fallback for other messages
@dp.message()
async def fallback(message: types.Message, state: FSMContext):
    if message.text.strip().lower() == "начать сначала":
        await cmd_start(message, state)
    else:
        await message.answer("Пожалуйста, используйте кнопки для выбора.")

# Entry point
async def main():
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())
