import os
import asyncio
import logging
import shutil
from pathlib import Path
from typing import List, Union

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.types import ContentType

from convert import save_as_docx, save_as_pdf
API_TOKEN = f"{os.environ.get('TELEGRAM_API_TOKEN')}"
API_TOKEN = '5318990723:AAHW9D6kxRTe3tC-2rAnvW0vlEnhHjCgGaM'

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)

# For example use simple MemoryStorage for Dispatcher.
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

BASE_DIR = Path(__file__).resolve().parent
MEDIA_FOLDER = BASE_DIR / 'media'
MEDIA_FOLDER.mkdir(exist_ok=True)
DOC_FOLDER = BASE_DIR / 'documents'
DOC_FOLDER.mkdir(exist_ok=True)


class AlbumMiddleware(BaseMiddleware):
    """This middleware is for capturing media groups."""

    album_data: dict = {}

    def __init__(self, latency: Union[int, float] = 0.01):
        """
        You can provide custom latency to make sure
        albums are handled properly in highland.
        """
        self.latency = latency
        super().__init__()

    async def on_process_message(self, message: types.Message, data: dict):
        if not message.media_group_id:
            return

        try:
            self.album_data[message.media_group_id].append(message)
            raise CancelHandler()  # Tell aiogram to cancel handler for this group element
        except KeyError:
            self.album_data[message.media_group_id] = [message]
            await asyncio.sleep(self.latency)

            message.conf["is_last"] = True
            data["album"] = self.album_data[message.media_group_id]

    async def on_post_process_message(self, message: types.Message, *args, **kwargs):
        """Clean up after handling our album."""

        if message.media_group_id and message.conf.get("is_last"):
            del self.album_data[message.media_group_id]


@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    """
    This handler will be called when user sends `/start` or `/help` command
    """
    await message.reply('''
    Привіт, я бот для конвертування фото твого конспекту в ворд.
Надішліть одне або кілька фото одним повідомленням для конвертації.''')


@dp.message_handler(content_types=types.ContentType.PHOTO)
async def handle_photos(message: types.Message, album: List[types.Message] = None):
    """
    Handle multiple photos in album with AlbumMiddleware
    or single photo in message
    """

    # create user directory
    username = message.from_user.full_name
    user_folder = MEDIA_FOLDER / username
    user_folder.mkdir(exist_ok=True)

    if not album:
        album = [message]

    # save files to user directory
    for i, message in enumerate(album):
        photo_filepath = user_folder / (username + str(i) + '.jpg')
        await message.photo[-1].download(destination_file=photo_filepath)

    # Inline buttons to choose format of the output file
    available_types = ['pdf', 'docx']
    keyboard_markup = types.InlineKeyboardMarkup(row_width=2)
    row_buttons = (types.InlineKeyboardButton(text=t.upper(), callback_data=t) for t in available_types)
    keyboard_markup.row(*row_buttons)

    await message.reply('Виберіть формат для збереження файлу:', reply_markup=keyboard_markup)


@dp.callback_query_handler(text='pdf')
@dp.callback_query_handler(text='docx')
async def inline_kb_answer_callback_handler(query: types.CallbackQuery):
    """
    Saves file after user chooses format by clicking button
    """ 
    answer_data = query.data

    # always answer callback queries
    await query.answer(f'Saving as {answer_data!r}')

    username = query.from_user.full_name
    user_folder = MEDIA_FOLDER / username

    if not user_folder.exists():
        await bot.send_message(chat_id=query.from_user.id, text='Your file already saved!')
        return

    photo_paths = sorted(list(user_folder.glob('*.jpg')), key=str)

    if answer_data == 'pdf':
        filepath = DOC_FOLDER / (username + '.pdf')
        save_as_pdf(filepath, photo_paths)

    elif answer_data == 'docx':
        filepath = DOC_FOLDER / (username + '.docx')
        save_as_docx(filepath, photo_paths)

    else:
        print('Unexpected message!')
        return

    await bot.send_document(chat_id=query.from_user.id, document=open(str(filepath), 'rb'))

    shutil.rmtree(user_folder)  # delete user directory recursively
    filepath.unlink()  # remove document


@dp.message_handler(content_types=ContentType.DOCUMENT)
async def wrong_format(message: types.Message):
    """
    This handler will be called when user sends document instead of photo
    """

    await message.reply("Фото повинні бути відправлені зі стисненням.")


@dp.message_handler()
async def echo(message: types.Message):
    await message.reply("Надішліть одне або декілька фото для вставки в docx/pdf file")


if __name__ == '__main__':
    dp.middleware.setup(AlbumMiddleware())
    executor.start_polling(dp, skip_updates=True)
