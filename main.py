import os
import re
import time
import tempfile
import instaloader
import traceback
import logging

from instaloader import Post
from telegram import Update, InputMediaVideo, InputMediaPhoto, BotCommand, BotCommandScopeChat, BotCommandScopeChatMember
from telegram.ext import MessageHandler, CommandHandler, filters, ContextTypes
from dotenv import load_dotenv
from mutagen.mp4 import MP4
from pathlib import Path
from typing import Final, Any

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(name)s %(levelname)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
load_dotenv()

MAINTENANCE = False
LOADER: Final = instaloader.Instaloader(
    filename_pattern="file", post_metadata_txt_pattern="",
    save_metadata=False, download_video_thumbnails=False)
TOKEN: Final = os.environ["FILEIFY_BOT_TOKEN"]
BOT_USERNAME: Final = os.environ["FILEIFY_BOT_USERNAME"]
USER_ADMIN_ID: Final = int(os.environ["FILEIFY_USER_ADMIN"])
USER_IDS: Final = [int(x) for x in os.environ["ALLOWED_USER_IDS"].split(",")]
GROUP_IDS: Final = [int(x) for x in os.environ["ALLOWED_GROUP_IDS"].split(",")]
# Allowed users can use the bot anywhere; in allowed groups, any member can use it
ALLOWED: Final = filters.User(user_id=USER_IDS) | filters.Chat(chat_id=GROUP_IDS)
LAST_REQUEST_TIME: Final = {}
COMMANDS = [
    BotCommand("stop", "Pause the bot for maintenance"),
    BotCommand("resume", "Resume the bot"),
]

async def set_commands(app):
    scopes = [BotCommandScopeChat(USER_ADMIN_ID)] + [BotCommandScopeChatMember(gid, USER_ADMIN_ID) for gid in GROUP_IDS]
    for scope in scopes:
        try:
            await app.bot.set_my_commands(COMMANDS, scope=scope)
        except Exception as error:
            logging.warning("Couldn't set commands for %s: %s", scope, error)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MAINTENANCE
    MAINTENANCE = True
    await update.message.reply_text("Bot paused for maintenance")

async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MAINTENANCE
    MAINTENANCE = False
    await update.message.reply_text("Bot resumed")

async def get_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if MAINTENANCE:
        return
    uid = update.effective_user.id
    if time.time() - LAST_REQUEST_TIME.get(uid, 0) < 10:
        return
    LAST_REQUEST_TIME[uid] = time.time()
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
                media = await media_by_type(files)

            for i in range(0, len(media), 10):
                await update.message.reply_media_group(media=media[i:i + 10], read_timeout=25, write_timeout=25)
        except Exception:
            traceback.print_exc()
            await update.message.reply_text("Couldn't access post")
    else:
        await update.message.reply_text("Invalid URL")


async def media_by_type(files: list[Path]) -> list[Any]:
    media = []
    for file in files:
        if file.suffix == ".mp4":
            media.append(InputMediaVideo(media=file.read_bytes(), duration=int(MP4(file).info.length)))
        else:
            media.append(InputMediaPhoto(media=file.read_bytes()))
    return media


def main():
    from telegram.ext import ApplicationBuilder

    INSTAGRAM = r"instagram\.com/(?:[^/]+/)?(?:p|reels?|tv)/"
    ADMINS = filters.User(user_id=USER_ADMIN_ID)

    app = ApplicationBuilder().token(TOKEN).post_init(set_commands).build()
    app.add_handler(CommandHandler("stop", stop, filters=ADMINS))
    app.add_handler(CommandHandler("resume", resume, filters=ADMINS))
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