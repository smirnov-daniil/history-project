import os
import json
import logging
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart, Command
from datetime import datetime

from endings import load_user_endings, save_user_ending, get_all_possible_endings

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

def build_keyboard(node_id: str) -> types.ReplyKeyboardMarkup:
    buttons = [types.KeyboardButton(text=choice['text']) for choice in story.get(node_id, {}).get('choices', [])]
    return types.ReplyKeyboardMarkup(keyboard=[[b] for b in buttons], resize_keyboard=True)

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
    img_path = node.get('image')
    if img_path and os.path.exists(img_path):
        await bot.send_photo(user_id, photo=open(img_path, 'rb'))

    reply_markup = build_keyboard(node_id) if node.get('choices') else types.ReplyKeyboardRemove()
    await bot.send_message(
        user_id,
        node.get('text', ''),
        reply_markup=reply_markup
    )
    await state.set_state(QuestStates.IN_QUEST)

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await state.update_data(history=[], current_node='start')
    await send_node(message.from_user.id, 'start', state)

@dp.message(Command("choices"))
async def show_current_progress(message: types.Message, state: FSMContext):
    data = await state.get_data()
    history = data.get("history", [])
    if not history:
        await message.answer("Вы пока не сделали ни одного выбора.")
        return

    text = "Ваши текущие выборы:\n"
    for entry in history:
        node_text = story.get(entry["node"], {}).get("text", "")
        text += f"- {node_text}\n  -> Вы выбрали: {entry['choice']}\n"
    await message.answer(text)

@dp.message(Command("undo"))
async def undo_last_choice(message: types.Message, state: FSMContext):
    data = await state.get_data()
    history = data.get("history", [])
    if not history:
        await message.answer("Нет предыдущих шагов для отмены.")
        return

    history.pop()
    await state.update_data(history=history)

    if history:
        previous_node = history[-1]['node']
    else:
        previous_node = 'start'

    await state.update_data(current_node=previous_node)
    await send_node(message.chat.id, previous_node, state)

@dp.message(Command("endings"))
async def show_endings_progress(message: types.Message):
    user_id = message.from_user.id
    endings = load_user_endings(user_id)
    all_ending_ids = get_all_possible_endings(story)

    total = len(all_ending_ids)
    unlocked = len(set(endings))

    text = f"Вы открыли {unlocked} из {total} возможных концовок.\n"
    if endings:
        text += "Открытые концовки:\n" + "\n".join(f"- {story.get(eid, {"title" : eid}).get('title', eid)}" for eid in endings)
    else:
        text += "Вы пока не открыли ни одной."

    await message.answer(text)

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

async def send_summary(user_id: int, state: FSMContext):
    data = await state.get_data()
    history = data.get('history', [])
    summary = 'Ваш итог путешествия по квесту:\n'
    for entry in history:
        node_text = story.get(entry['node'], {}).get('text', '')
        summary += f"- {node_text}\n  -> Вы выбрали: {entry['choice']}\n"

    if history:
        last_node_id = history[-1]['node']
        save_user_ending(user_id, last_node_id)

    await bot.send_message(user_id, summary, reply_markup=types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="Начать сначала")]], resize_keyboard=True
    ))
    await state.clear()


@dp.message()
async def fallback(message: types.Message, state: FSMContext):
    if message.text.strip().lower() == "начать сначала":
        await cmd_start(message, state)
    else:
        await message.answer("Пожалуйста, используйте кнопки для выбора.")

async def main():
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())
