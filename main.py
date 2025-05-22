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

load_dotenv()

logging.basicConfig(level=logging.INFO)

API_TOKEN = os.getenv('TELEGRAM_TOKEN')
STORY_FILE = os.getenv('STORY_FILE', 'story.json')

if not API_TOKEN:
    logging.error('Нет TELEGRAM_TOKEN в окружении')
    exit(1)

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

def load_story(path: str) -> dict:
    if not os.path.exists(path):
        logging.error(f'Файл сюжета не найден: {path}')
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

story = load_story(STORY_FILE)

class QuestStates(StatesGroup):
    IN_QUEST = State()

def build_keyboard(node_id: str) -> types.InlineKeyboardMarkup:
    buttons = []
    for idx, choice in enumerate(story.get(node_id, {}).get('choices', [])):
        callback_data = f"{node_id}|{idx}"
        buttons.append([types.InlineKeyboardButton(text=choice['text'], callback_data=callback_data)])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

async def send_node(user_id: int, node_id: str, state: FSMContext):
    node = story.get(node_id)
    if not node:
        await bot.send_message(user_id, "Ошибка: узел истории не найден.")
        await state.clear()
        return

    img_path = node.get('image')
    if img_path and os.path.exists(img_path):
        await bot.send_photo(user_id, photo=open(img_path, 'rb'))

    await bot.send_message(
        user_id,
        node.get('text', ''),
        reply_markup=build_keyboard(node_id)
    )
    await state.set_state(QuestStates.IN_QUEST)

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await state.update_data(history=[], current_node='start')
    await send_node(message.from_user.id, 'start', state)

@dp.callback_query(QuestStates.IN_QUEST)
async def process_choice(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    node_id, idx_str = callback.data.split('|')
    idx = int(idx_str)
    node = story.get(node_id, {})
    choice = node.get('choices', [])[idx]

    history = data.get('history', [])
    history.append({'node': node_id, 'choice': choice.get('text')})
    await state.update_data(history=history)
    await callback.answer()

    next_id = choice.get('next')
    if next_id == 'END':
        await send_summary(callback.from_user.id, state)
    else:
        await state.update_data(current_node=next_id)
        await send_node(callback.from_user.id, next_id, state)

async def send_summary(user_id: int, state: FSMContext):
    data = await state.get_data()
    history = data.get('history', [])
    text = 'Ваш итог путешествия по квесту:\n'
    for entry in history:
        node_text = story.get(entry['node'], {}).get('text', '')
        text += f"- {node_text}\n  -> Вы выбрали: {entry['choice']}\n"

    await bot.send_message(user_id, text)
    await state.clear()

@dp.message()
async def fallback(message: types.Message):
    await message.answer("Пожалуйста, используйте кнопки для выбора.")

async def main():
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())
