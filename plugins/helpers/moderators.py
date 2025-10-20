# plugins/helpers/mods.py
import sqlite3
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from config import DB_PATH, OWNER_ID, LOG_CHAT_ID
import logging

logger = logging.getLogger(__name__)

# ---------------- Database Initialization for Mods ----------------
def init_mods_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS mods (
            mod_id INTEGER PRIMARY KEY,
            username TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

# ---------------- Helper Functions ----------------
def is_owner(user_id: int) -> bool:
    """Check if the user is the owner."""
    return user_id == OWNER_ID

def is_mod(user_id: int) -> bool:
    """Check if the user is a mod."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT mod_id FROM mods WHERE mod_id = ?", (user_id,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def add_mod(mod_id: int, username: str) -> bool:
    """Add a mod to the DB if not exists. Returns True if added."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT mod_id FROM mods WHERE mod_id = ?", (mod_id,))
    if c.fetchone():
        conn.close()
        return False  # Already exists
    c.execute("INSERT INTO mods (mod_id, username) VALUES (?, ?)", (mod_id, username))
    conn.commit()
    conn.close()
    return True

def remove_mod(mod_id: int) -> bool:
    """Remove a mod from the DB. Returns True if removed."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT mod_id FROM mods WHERE mod_id = ?", (mod_id,))
    if not c.fetchone():
        conn.close()
        return False  # Not exists
    c.execute("DELETE FROM mods WHERE mod_id = ?", (mod_id,))
    conn.commit()
    conn.close()
    return True

def get_all_mods() -> list:
    """Get list of all mods as (mod_id, username)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT mod_id, username FROM mods")
    mods = c.fetchall()
    conn.close()
    return mods

def reset_user_stats(user_id: int) -> bool:
    """Reset a user's stats in the users table. Returns True if user exists and reset."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not c.fetchone():
        conn.close()
        return False
    c.execute(
        """
        UPDATE users
        SET games_played = 0,
            wins = 0,
            losses = 0,
            rounds_played = 0,
            eliminations = 0,
            total_score = 0,
            last_score = 0,
            penalties = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
        """,
        (user_id,)
    )
    conn.commit()
    conn.close()
    return True

# ---------------- Command Handlers ----------------
async def addmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Add a mod by replying to a user."""
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    reply = update.message.reply_to_message
    if not reply or not reply.from_user:
        await update.message.reply_text("❌ Reply to a user's message to add them as mod.")
        return

    mod_user = reply.from_user
    if add_mod(mod_user.id, mod_user.username or mod_user.full_name):
        await update.message.reply_text(f"✅ Added @{mod_user.username or mod_user.full_name} as mod.")
        # Log to LOG_CHAT_ID if exists
        if LOG_CHAT_ID:
            try:
                await context.bot.send_message(LOG_CHAT_ID, f"🆕 New Mod Added: @{mod_user.username or mod_user.full_name} (ID: {mod_user.id}) by Owner.")
            except Exception:
                logger.exception("Failed to log new mod to LOG_CHAT_ID")
    else:
        await update.message.reply_text("⚠️ This user is already a mod.")

async def rmmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Remove a mod by replying or providing userid."""
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    mod_id = None
    if context.args:
        try:
            mod_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Provide a number or reply to a user.")
            return
    elif update.message.reply_to_message and update.message.reply_to_message.from_user:
        mod_id = update.message.reply_to_message.from_user.id

    if not mod_id:
        await update.message.reply_text("❌ Provide a user ID or reply to a user's message to remove mod.")
        return

    if remove_mod(mod_id):
        await update.message.reply_text(f"✅ Removed mod with ID {mod_id}.")
        if LOG_CHAT_ID:
            try:
                await context.bot.send_message(LOG_CHAT_ID, f"❌ Mod Removed: ID {mod_id} by Owner.")
            except Exception:
                logger.exception("Failed to log mod removal to LOG_CHAT_ID")
    else:
        await update.message.reply_text("⚠️ No such mod found.")

async def mods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: List all mods."""
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    mod_list = get_all_mods()
    if not mod_list:
        await update.message.reply_text("❌ No mods added yet.")
        return

    text = "📋 List of Mods:\n\n"
    for i, (mod_id, username) in enumerate(mod_list, 1):
        text += f"{i}. @{username or 'N/A'} (ID: {mod_id})\n"

    await update.message.reply_text(text)

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes
import sqlite3
import logging
from config import DB_PATH, OWNER_ID, LOG_CHAT_ID

logger = logging.getLogger(__name__)

# ---------------- Database Helpers ----------------
def init_mods_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS mods (
            mod_id INTEGER PRIMARY KEY,
            username TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def is_mod(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT mod_id FROM mods WHERE mod_id = ?", (user_id,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def reset_user_stats(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not c.fetchone():
        conn.close()
        return False
    c.execute(
        """
        UPDATE users
        SET games_played = 0,
            wins = 0,
            losses = 0,
            rounds_played = 0,
            eliminations = 0,
            total_score = 0,
            last_score = 0,
            penalties = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
        """,
        (user_id,)
    )
    conn.commit()
    conn.close()
    return True

# ---------------- Command Handlers ----------------
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not (is_owner(user.id) or is_mod(user.id)):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    target_id = None
    if context.args:
        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Provide a number or reply to a user.")
            return
    elif update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id

    if not target_id:
        await update.message.reply_text("❌ Provide a user ID or reply to a user's message to reset stats.")
        return

    # Yes / No buttons
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data=f"confirm_reset:{target_id}:{user.id}"),
            InlineKeyboardButton("❌ No", callback_data=f"cancel_reset:{target_id}:{user.id}")
        ]
    ])

    await update.message.reply_text(
        f"⚠️ Are you sure you want to reset stats for user ID {target_id}?",
        reply_markup=buttons
    )

async def reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data  # e.g., "confirm_reset:12345:67890" or "cancel_reset:12345:67890"

    try:
        action, target_id, initiator_id = data.split(":")
        target_id = int(target_id)
        initiator_id = int(initiator_id)

        if query.from_user.id != initiator_id:
            return await query.answer("❌ You cannot confirm/cancel this reset.", show_alert=True)

        if action == "confirm_reset":
            if reset_user_stats(target_id):
                await query.message.edit_text(f"✅ Stats for user ID {target_id} have been reset.")
                if LOG_CHAT_ID:
                    try:
                        await context.bot.send_message(
                            LOG_CHAT_ID,
                            f"🔄 User Stats Reset: ID {target_id} by @{query.from_user.username or query.from_user.full_name} (ID: {initiator_id})"
                        )
                    except Exception:
                        logger.exception("Failed to log user reset to LOG_CHAT_ID")
            else:
                await query.message.edit_text("⚠️ No such user found.")
        elif action == "cancel_reset":
            await query.message.edit_text(f"❌ Reset for user ID {target_id} was canceled.")

        await query.answer()
    except Exception:
        logger.exception("Error handling reset callback")
        await query.answer("⚠️ Something went wrong.", show_alert=True)
# ---------------- Reset All Users Game Stats ----------------
async def reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Reset all users game stats with confirmation."""
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    # Confirmation buttons
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data=f"confirm_reset_all:{user.id}"),
            InlineKeyboardButton("❌ No", callback_data=f"cancel_reset_all:{user.id}")
        ]
    ])

    await update.message.reply_text(
        "⚠️ Are you sure you want to reset **all users' game stats**? This cannot be undone!",
        reply_markup=buttons,
        parse_mode="Markdown"
    )

async def reset_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Yes/No confirmation for resetting all users game stats."""
    query = update.callback_query
    data = query.data  # e.g., "confirm_reset_all:12345"

    try:
        action, initiator_id = data.split(":")
        initiator_id = int(initiator_id)

        if query.from_user.id != initiator_id:
            return await query.answer("❌ You cannot confirm/cancel this reset.", show_alert=True)

        if action == "confirm_reset_all":
            # Reset only game stats, not user accounts
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute(
                """
                UPDATE users
                SET games_played = 0,
                    wins = 0,
                    losses = 0,
                    rounds_played = 0,
                    eliminations = 0,
                    total_score = 0,
                    last_score = 0,
                    penalties = 0,
                    updated_at = CURRENT_TIMESTAMP
                """
            )
            conn.commit()
            conn.close()

            await query.message.edit_text("✅ All users' game stats have been reset!")

            # Log to admin chat
            if LOG_CHAT_ID:
                try:
                    await context.bot.send_message(
                        LOG_CHAT_ID,
                        f"🔄 All users' game stats have been reset by @{query.from_user.username or query.from_user.full_name} (ID: {initiator_id})"
                    )
                except Exception:
                    logger.exception("Failed to log reset_all to LOG_CHAT_ID")

        elif action == "cancel_reset_all":
            await query.message.edit_text("❌ Reset all users' game stats was canceled.")

        await query.answer()
    except Exception:
        logger.exception("Error handling reset all callback")
        await query.answer("⚠️ Something went wrong.", show_alert=True)


# ---------------- Register Reset All ----------------
def register_mods_handlers(app):
    init_mods_db()
    app.add_handler(CommandHandler("addmod", addmod))
    app.add_handler(CommandHandler("rmmod", rmmod))
    app.add_handler(CommandHandler("mods", mods))
    app.add_handler(CommandHandler("reset", reset))

    # Single-user reset callbacks
    app.add_handler(CallbackQueryHandler(reset_callback, pattern="^(confirm_reset|cancel_reset):"))

    # All-users reset game stats
    app.add_handler(CommandHandler("resetall", reset_all))
    app.add_handler(CallbackQueryHandler(reset_all_callback, pattern="^(confirm_reset_all|cancel_reset_all):"))
