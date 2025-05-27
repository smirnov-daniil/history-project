import os
import json
import logging


def get_user_endings_path(user_id: int) -> str:
    os.makedirs("endings", exist_ok=True)
    return f'endings/{user_id}.json'


def load_user_endings(user_id: int) -> list:
    path = get_user_endings_path(user_id)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Не удалось прочитать файл концовок {path}: {e}")
    return []


def save_user_ending(user_id: int, ending_node_id: str):
    endings = load_user_endings(user_id)
    if ending_node_id not in endings:
        endings.append(ending_node_id)
        path = get_user_endings_path(user_id)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(endings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning(f"Не удалось сохранить концовку {ending_node_id} для пользователя {user_id}: {e}")


def get_all_possible_endings(story: dict) -> list:
    return list({
        node_id for node_id, node in story.items()
        if not node.get('choices') or any(c.get('next') == 'END' for c in node.get('choices', []))
    })