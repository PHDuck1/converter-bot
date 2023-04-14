import os
import shutil
import asyncio
import logging
import concurrent.futures

from PIL import Image
from typing import List
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
from pillow_heif import register_heif_opener

from aiogram import Bot, Dispatcher, types
from aiogram.types import ContentType
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import MediaGroupFilter
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardRemove, KeyboardButton, ReplyKeyboardMarkup

import aiogram_media_group


# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# register pillow support for heif file format
register_heif_opener()

# load environment variable from .env file
load_dotenv(find_dotenv())

# get TOKEN from environment variable
TOKEN = os.getenv('TOKEN')
photo_extensions = ["jpg", "jpeg", "jpe", "jif", "jfif", "jfi", "png", "heic", "heif"]
SUPPORTED_EXTENSIONS = photo_extensions + [ext.upper() for ext in photo_extensions]

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

MEDIA_DIR = Path.cwd() / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


class StateChoice(StatesGroup):
    """define state(s)"""
    pdf = State()
    name = State()


async def convert_images_to_pdf(image_paths: list, pdf_file_path: Path) -> None:
    with concurrent.futures.ThreadPoolExecutor() as pool:
        loop = asyncio.get_running_loop()
        images = await asyncio.gather(
            *[loop.run_in_executor(pool, Image.open, image_path) for image_path in image_paths])
        images[0].save(str(pdf_file_path), save_all=True, append_images=images[1:])


@dp.message_handler(commands=['start', ])
async def start(message: types.Message):
    """Starts the conversation and offers to start sending photos."""

    await message.answer(
        "Hi! I am here to convert your photos into a single PDF file.\n"
        "Send photos in form of album or separate photos.\n"
        "If you want to start conversion type /convert.\n"
        "If you dont want this pdf or want to start over type /cancel."
    )


@dp.message_handler(state=StateChoice.pdf, commands=['name', ])
async def name_start(message: types.Message, state: FSMContext):
    """Answer to /name command, sets name state and asks to input the name"""

    markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    markup.add("/cancel")

    await message.answer("Send desired name for your PDF", reply_markup=markup)
    await StateChoice.name.set()


@dp.message_handler(state=StateChoice.name, commands=['cancel', ])
async def cancel(message: types.Message, state: FSMContext):
    """Deletes user photos and ends the conversation."""

    markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    markup.add('/name', '/convert')
    markup.add('/cancel')

    await message.answer("Name change canceled", reply_markup=markup)

    await StateChoice.pdf.set()


@dp.message_handler(state=StateChoice.name, content_types=ContentType.TEXT)
async def name_set(message: types.Message, state: FSMContext):
    """Sets file name to name provided in the message"""

    filename = message.text
    if not filename.endswith('.pdf'):
        filename = filename + '.pdf'

    async with state.proxy() as data:
        data['filename'] = filename

    markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    markup.add('/name', '/convert')
    markup.add('/cancel')

    await message.answer(f"Set file name to '{filename}'", reply_markup=markup)
    await StateChoice.pdf.set()


@dp.message_handler(MediaGroupFilter(is_media_group=False), content_types=[ContentType.PHOTO, ContentType.DOCUMENT], state='*')
async def handle_photo_or_document(message: types.Message, state: FSMContext):
    """Stores received photo"""
    user = message.from_user

    # Create dir for user to store photo files in there
    user_dir = MEDIA_DIR / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    # download photo
    if message.content_type == 'photo':
        photo_file = await message.photo[-1].download(destination_dir=user_dir)
    elif message.content_type == 'document':
        file_type = message.document.file_name.split('.')[-1]

        if file_type not in SUPPORTED_EXTENSIONS:
            logger.info(f'Document type is not supported {file_type}')
            await message.answer("Format of your file is not supported\nSupported formats: PNG, JPG, HEIC.")
            return

        photo_file = await message.document.download(destination_dir=user_dir)
    else:
        photo_file = None
        logger.info("Error in handle_photo_or_document")

    # add photo`s Path to state
    async with state.proxy() as data:
        photos = data.get("photos", [])
    n = len(photos) + 1
    photos.append(Path(photo_file.name))
    await state.update_data(photos=photos)

    # Create the inline keyboard with the "Convert", "Name" and "Cancel" buttons
    markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    markup.add('/name', '/convert')
    markup.add('/cancel')

    await message.answer(f"Got your {n} photo.\n", reply_markup=markup)

    await StateChoice.pdf.set()


@dp.message_handler(MediaGroupFilter(is_media_group=True), content_types=[ContentType.PHOTO, ContentType.DOCUMENT], state='*')
@aiogram_media_group.media_group_handler
async def handle_album(messages: List[types.Message]):
    last_message = messages[-1]

    user = last_message.from_user
    user_dir = MEDIA_DIR / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    if last_message.content_type == 'photo':
        photo_files = [Path((await message.photo[-1].download(destination_dir=user_dir)).name) for message in messages]
    elif last_message.content_type == 'document':
        photo_files = []
        for message in messages:
            file_type = message.document.file_name.split('.')[-1]

            if file_type not in SUPPORTED_EXTENSIONS:
                logger.info(f'Document type is not supported {file_type}')
                await message.answer(f"Format of your file({file_type}) is not supported\n"
                                     f"Supported formats: PNG, JPG, HEIC.")
                return

            photo_file = Path((await message.document.download(destination_dir=user_dir)).name)
            photo_files.append(photo_file)
    else:
        photo_files = []
        logger.info("Error in handle_photo_or_document")

    state = dp.current_state(chat=last_message.chat.id, user=user.id)

    async with state.proxy() as data:
        photos = data.get("photos", [])

    photos.extend(photo_files)
    await state.update_data(photos=photos)

    # Create the inline keyboard with the "Convert" and "Cancel" buttons
    markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    markup.add('/name', '/convert')
    markup.add('/cancel')

    await last_message.answer("Got your photos!", reply_markup=markup)
    await StateChoice.pdf.set()


@dp.message_handler(state=StateChoice.pdf, commands=['convert', ])
async def make_pdf(message: types.Message, state: FSMContext):
    """Converts photos to pdf, sends it to user and ends conversation."""

    user = message.from_user
    user_dir = MEDIA_DIR / str(user.id)
    logger.info(f"Starting conversion of {user.first_name}'s photos")

    # get photos to convert
    async with state.proxy() as data:
        photos = data.get("photos", [])
        filename = data.get("filename", f"{user.full_name}.pdf")

    pdf_path = user_dir / filename
    await convert_images_to_pdf(photos, pdf_path)

    logger.info(f"Pdf for {user.first_name} generated")

    with open(pdf_path, 'rb') as pdf_file:
        await message.answer_document(document=pdf_file,
                                      caption="Here is your PDF.\nTo make a new one send another photo.",
                                      reply_markup=ReplyKeyboardRemove())

    shutil.rmtree(user_dir)
    await state.update_data(photos=[])

    await state.finish()


@dp.message_handler(state='pdf', commands=['cancel', ])
async def cancel(message: types.Message, state: FSMContext):
    """Deletes user photos and ends the conversation."""

    user = message.from_user
    logger.info(f"{user.first_name} ended pdf creation.")

    user_dir = MEDIA_DIR / str(user.id)
    shutil.rmtree(user_dir)

    await state.update_data(photos=[])

    await message.answer(
        "Bye! If you still want to create pdf file just sent photo(s).",
        reply_markup=types.ReplyKeyboardRemove(),
    )

    await state.finish()


def main():
    """Run the bot."""
    # Run the bot until KeyboardInterrupt
    executor.start_polling(dp, skip_updates=True)


if __name__ == "__main__":
    main()
