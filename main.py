import asyncio
from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from plugins.connections.logger import setup_logger
from plugins.connections.db import init_db
from plugins.utils.cleanup import clean_temp_job
from datetime import timedelta
import aioschedule

from plugins.game.db import reset_daily_leaderboard  # your reset function

logger = setup_logger("mind-scale-bot")

async def start_scheduler():
    """Runs scheduled background jobs."""
    # Wrap sync function in async-safe thread
    aioschedule.every().day.at("00:00").do(
        lambda: asyncio.create_task(asyncio.to_thread(reset_daily_leaderboard))
    )

    while True:
        await aioschedule.run_pending()
        await asyncio.sleep(30)


if __name__ == "__main__":
    # Init DB
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Load Game module
    try:
        from plugins.game import game_handlers
        game_handlers(app)
    except Exception:
        logger.exception("Failed to load Game module")

    # Load Helpers module (includes leaderboard + daily leaderboard)
    try:
        from plugins.helpers import helpers_handlers
        helpers_handlers(app)
    except Exception:
        logger.exception("Failed to load Helpers module")

    # Schedule cleanup job for temp files every 12 hours
    app.job_queue.run_repeating(
        clean_temp_job,
        interval=timedelta(hours=12),
        first=300  # 5 minutes
    )

    # Run the async scheduler in background
    loop = asyncio.get_event_loop()
    loop.create_task(start_scheduler())

    print("✅ Bot is running...")
    app.run_polling()
