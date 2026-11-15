import os
import re
import time
import tempfile
import instaloader

from instaloader import Post
from telegram import Update, InputMediaVideo, InputMediaPhoto
from telegram.ext import MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from mutagen.mp4 import MP4
from pathlib import Path
from typing import Final

load_dotenv()

LOADER = instaloader.Instaloader(
    filename_pattern="file", post_metadata_txt_pattern="",
    save_metadata=False, download_video_thumbnails=False)
TOKEN: Final = os.environ["FILEIFY_BOT_TOKEN"]
BOT_USERNAME: Final = os.environ["FILEIFY_BOT_USERNAME"]
USER_IDS = [int(x) for x in os.environ["ALLOWED_USER_IDS"].split(",")]
GROUP_IDS = [int(x) for x in os.environ["ALLOWED_GROUP_IDS"].split(",")]
ALLOWED = filters.User(user_id=USER_IDS) | filters.Chat(chat_id=GROUP_IDS)
LAST = {}

async def get_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if time.time() - LAST.get(uid, 0) < 10:
        return
    LAST[uid] = time.time()
    user_message = update.message.text or update.message.caption

    match = re.search(r"instagram\.com/(?:[^/]+/)?(?:p|reels?|tv)/([A-Za-z0-9_-]+)", user_message)
    if match:
        shortcode = match.group(1)
        try:
            post = Post.from_shortcode(LOADER.context, shortcode)
            with tempfile.TemporaryDirectory() as tmp:
                LOADER.dirname_pattern = tmp
                LOADER.download_post(post, target=tmp)
                files = sorted(Path(tmp).glob("file*"),
                               key=lambda f: int(f.stem.split("_")[-1]) if "_" in f.stem else 0)
                media = []
                for file in files:
                    if file.suffix == ".mp4":
                        media.append(InputMediaVideo(media=file.read_bytes(), duration=int(MP4(file).info.length)))
                    else:
                        media.append(InputMediaPhoto(media=file.read_bytes()))

            for i in range(0, len(media), 10):
                await update.message.reply_media_group(media=media[i:i + 10], read_timeout=25, write_timeout=25)
        except Exception as error:
            print(error)
            await update.message.reply_text("Couldn't access post")
    else:
        await update.message.reply_text("Invalid URL")

def main():
    from telegram.ext import ApplicationBuilder

    INSTAGRAM = r"instagram\.com/(?:[^/]+/)?(?:p|reels?|tv)/"

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(
        MessageHandler(filters.UpdateType.MESSAGE &
                       (filters.TEXT | filters.CAPTION) & ~filters.COMMAND &
                       filters.ChatType.PRIVATE &
                       ALLOWED, get_media))
    app.add_handler(
        MessageHandler((filters.Regex(INSTAGRAM) | filters.CaptionRegex(INSTAGRAM)) &
                       filters.UpdateType.MESSAGE &
                       filters.ChatType.GROUPS &
                       ALLOWED, get_media))

    print("initialized")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()