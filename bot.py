import os
import shutil
import asyncio
import logging
import concurrent.futures

from PIL import Image
from typing import List
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

from aiogram import Bot, Dispatcher, types
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

# load environment variable from .env file
load_dotenv(find_dotenv())

# get TOKEN from environment variable
TOKEN = os.getenv('TOKEN')

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)


MEDIA_DIR = Path.cwd() / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

user_dirs = []


class PhotoConvert(StatesGroup):
    """define state(s)"""
    photo = State()


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


@dp.message_handler(MediaGroupFilter(is_media_group=False), content_types=[types.ContentType.PHOTO])
async def handle_photo(message: types.Message, state: FSMContext):
    """Stores received photo and asks if user wants to send another one."""
    user = message.from_user

    # Create dir for user to store photo files in there
    user_dir = MEDIA_DIR / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    # download photo
    photo_file = await message.photo[-1].download(destination_dir=user_dir)

    # add photo`s Path to state
    async with state.proxy() as data:
        photos = data.get("photos", [])
    photos.append(Path(photo_file.name))
    await state.update_data(photos=[Path(photo_file.name)])

    # Create the inline keyboard with the "Convert" and "Cancel" buttons
    convert_button = KeyboardButton("/convert")
    cancel_button = KeyboardButton("/cancel")
    reply_keyboard = ReplyKeyboardMarkup(row_width=2)
    reply_keyboard.add(convert_button, cancel_button)

    await message.answer("I got your first photo.\n", reply_markup=reply_keyboard)

    await PhotoConvert.photo.set()


@dp.message_handler(MediaGroupFilter(is_media_group=True), content_types=types.ContentType.PHOTO, state='*')
@aiogram_media_group.media_group_handler
async def handle_album(messages: List[types.Message]):
    last_message = messages[-1]

    user = last_message.from_user
    user_dir = MEDIA_DIR / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    photo_files = [(await message.photo[-1].download(destination_dir=user_dir)).name for message in messages]

    state = dp.current_state(chat=last_message.chat.id, user=user.id)

    async with state.proxy() as data:
        photos = data.get("photos", [])

    photos.extend(photo_files)
    await state.update_data(photos=photos)

    # Create the inline keyboard with the "Convert" and "Cancel" buttons
    convert_button = KeyboardButton("/convert")
    cancel_button = KeyboardButton("/cancel")
    reply_keyboard = ReplyKeyboardMarkup(row_width=2)
    reply_keyboard.add(convert_button, cancel_button)

    await last_message.answer("Got your photos!", reply_markup=reply_keyboard)
    await PhotoConvert.photo.set()


@dp.message_handler(state=PhotoConvert.photo, commands=['convert', ])
async def make_pdf(message: types.Message, state: FSMContext):
    """Converts photos to pdf, sends it to user and ends conversation."""

    user = message.from_user
    user_dir = MEDIA_DIR / str(user.id)
    logger.info(f"Starting conversion of {user.first_name}'s photos")

    # get photos to convert
    async with state.proxy() as data:
        photos = data.get("photos", [])

    pdf_path = user_dir / f"{user.full_name}.pdf"
    await convert_images_to_pdf(photos, pdf_path)

    logger.info(f"Pdf for {user.first_name} generated")

    with open(pdf_path, 'rb') as pdf_file:
        await message.answer_document(document=pdf_file,
                                      caption="Here is your PDF.\nTo make a new one send another photo.",
                                      reply_markup=ReplyKeyboardRemove())

    shutil.rmtree(user_dir)
    await state.update_data(photos=[])

    await state.finish()


@dp.message_handler(state=PhotoConvert.photo, commands=['cancel', ])
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
