import math
import html
import asyncio
import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import ContextTypes
from config import DB_PATH
from plugins.game.db import ensure_columns_exist, get_daily_leaderboard
from plugins.utils.thumbnail import generate_card, download_user_photo_by_id

logger = logging.getLogger(__name__)

PER_PAGE = 5

# ---------------- DB ----------------
def get_all_users_sorted(limit: int = 100):
    try:
        ensure_columns_exist()
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 
                user_id, 
                IFNULL(username, '') AS username, 
                IFNULL(first_name, '') AS first_name, 
                IFNULL(games_played, 0) AS games_played, 
                IFNULL(wins, 0) AS wins, 
                IFNULL(losses, 0) AS losses, 
                IFNULL(rounds_played, 0) AS rounds_played, 
                IFNULL(eliminations, 0) AS eliminations, 
                IFNULL(total_score, 0) AS total_score, 
                IFNULL(penalties, 0) AS penalties
            FROM users
            ORDER BY wins DESC, total_score DESC
            LIMIT ?
            """,
            (limit,),
        )
        result = cursor.fetchall()
        conn.close()
        return result
    except Exception:
        logger.exception("Error in get_all_users_sorted")
        return []

def get_user_rank(user_id):
    try:
        all_users = get_all_users_sorted()
        for idx, row in enumerate(all_users, start=1):
            if row['user_id'] == user_id:
                gp = row['games_played'] or 0
                win_percent = round((row['wins'] or 0) / gp * 100, 1) if gp > 0 else 0
                return {
                    "username": (row['username'] or row['first_name'] or "Unknown"),
                    "rank": idx,
                    "total_users": len(all_users),
                    "total_played": gp,
                    "wins": row['wins'] or 0,
                    "losses": row['losses'] or 0,
                    "win_percent": win_percent,
                    "rounds_played": row['rounds_played'] or 0,
                    "eliminations": row['eliminations'] or 0,
                    "total_score": row['total_score'] or 0,
                    "penalties": row['penalties'] or 0
                }
        # Not in list
        return {
            "username": "Unknown",
            "rank": len(all_users) + 1,
            "total_users": len(all_users),
            "total_played": 0,
            "wins": 0,
            "losses": 0,
            "win_percent": 0,
            "rounds_played": 0,
            "eliminations": 0,
            "total_score": 0,
            "penalties": 0
        }
    except Exception:
        logger.exception("Error in get_user_rank")
        return {
            "username": "Unknown", "rank": 1, "total_users": 0, "total_played": 0,
            "wins": 0, "losses": 0, "win_percent": 0, "rounds_played": 0,
            "eliminations": 0, "total_score": 0, "penalties": 0
        }

# ---------------- UI helpers ----------------
def _medal_for_rank(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "")
    
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def _build_pager_old(page: int, total_pages: int, prefix: str) -> InlineKeyboardMarkup | None:
    """
    Build an inline keyboard pager for leaderboard navigation.

    Args:
        page (int): Current page number (1-based).
        total_pages (int): Total number of pages.
        prefix (str): Callback data prefix (e.g., "leaderboard" or "daily_leaderboard").

    Returns:
        InlineKeyboardMarkup | None: Telegram inline keyboard markup or None if single page.
    """
    if total_pages <= 1:
        return None  # No pager needed if only one page

    buttons = []

    # Navigation row
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("◄ Previous", callback_data=f"{prefix}_{page-1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("Next ►", callback_data=f"{prefix}_{page+1}"))
    if nav_row:
        buttons.append(nav_row)

    # Page indicator row (non-clickable)
    page_row = [InlineKeyboardButton(f"Page {page}/{total_pages}", callback_data=f"{prefix}:nop")]
    buttons.append(page_row)

    return InlineKeyboardMarkup(buttons)

def _build_leaderboard_text(all_users, page: int, per_page: int, viewer_id: int, daily: bool = False):
    total = len(all_users)
    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, total)

    text = "<b>──✦ Player Spotlight ✦──</b>\n\n"
    user_in_page = False

    for i, row in enumerate(all_users[start_idx:end_idx], start=start_idx + 1):
        rank = i
        medal = _medal_for_rank(rank)
        gp = row['games_played'] or 0
        wins = row['wins'] or 0
        losses = row['losses'] or 0
        total_score = row['total_score'] or 0
        penalties = row['penalties'] or 0
        win_percent = round(wins / gp * 100, 1) if gp > 0 else 0
        display_name = html.escape(row['first_name'] or row['username'] or "Unknown")
        highlight = "⭐ " if row['user_id'] == viewer_id else ""

        text += f"{rank}. {medal} {highlight}<b>{display_name}</b> (ID: {row['user_id']})\n"
        text += f"   🎮 Games: {gp} | ⧉ Win%: {win_percent}\n"
        text += f"   🏆 Wins: {wins} | Lost: {losses}\n"
        text += f"   ⭐ Score: {total_score} | ⛔ Pen: {penalties}\n"
        text += "<b>────⊱◈◈◈⊰────</b>\n\n"

        if row['user_id'] == viewer_id:
            user_in_page = True

    if not user_in_page:
        me_row = next((row for row in all_users if row['user_id'] == viewer_id), None)
        if me_row:
            rank = next((idx for idx, r in enumerate(all_users, 1) if r['user_id'] == viewer_id), total + 1)
            me = {
                "username": me_row['username'] or me_row['first_name'] or "Unknown",
                "rank": rank,
                "games_played": me_row['games_played'] or 0,
                "wins": me_row['wins'] or 0,
                "losses": me_row['losses'] or 0,
                "total_score": me_row['total_score'] or 0,
                "penalties": me_row['penalties'] or 0
            }
        else:
            me = {
                "username": "Unknown",
                "rank": total + 1,
                "games_played": 0,
                "wins": 0,
                "losses": 0,
                "total_score": 0,
                "penalties": 0
            }

        text += f"\n\n<b>────⊱◈◈◈⊰────</b>\n"
        text += "📌 <b>Your Rank:</b>\n"
        text += f"{me['rank']}. {html.escape(me['username'])} (ID: {viewer_id})\n"
        text += f"   🎮 Games: {me['games_played']} | ⧉ Win%: {round(me['wins']/me['games_played']*100,1) if me['games_played'] else 0}\n"
        text += f"   🏆 Wins: {me['wins']} | Lost: {me['losses']}\n"
        text += f"   ⭐ Score: {me['total_score']} | ⛔ Pen: {me['penalties']}\n"

    return text, total_pages, page

async def _send_leaderboard_initial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    viewer_id = update.effective_user.id

    # Send loading sticker first
    try:
        mystic = await update.message.reply_sticker(Load_id)
    except Exception:
        mystic = await update.message.reply_text("⏳ Loading leaderboard...")

    all_users = get_all_users_sorted()
    text, total_pages, page = _build_leaderboard_text(
        all_users, page=1, per_page=PER_PAGE, viewer_id=viewer_id
    )

    pager = _build_pager_old(page, total_pages, prefix="leaderboard")

    top_user_id = all_users[0]['user_id'] if all_users else viewer_id
    try:
        usr_pfp_path = await download_user_photo_by_id(top_user_id, context.bot)
    except Exception:
        usr_pfp_path = None

    # Delete the loading sticker/message
    try:
        await mystic.delete()
    except Exception:
        pass

    try:
        card = generate_card("leaderboard", usr_pfp_path)
        await update.message.reply_photo(photo=card, caption=text, reply_markup=pager, parse_mode="HTML")
    except Exception:
        await update.message.reply_text(text=text, reply_markup=pager, parse_mode="HTML")


async def _edit_leaderboard_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    query = update.callback_query
    viewer_id = query.from_user.id
    all_users = get_all_users_sorted()
    text, total_pages, page = _build_leaderboard_text(
        all_users, page=page, per_page=PER_PAGE, viewer_id=viewer_id
    )

    # ⚡ FIX: Provide prefix for pager
    pager = _build_pager_old(page, total_pages, prefix="leaderboard")

    try:
        if query.message.photo:
            await query.message.edit_caption(caption=text, reply_markup=pager, parse_mode="HTML")
        else:
            await query.message.edit_text(text=text, reply_markup=pager, parse_mode="HTML")
        await query.answer()
    except Exception as e:
        if "not modified" in str(e).lower():
            try:
                await query.answer("No changes.")
            except Exception:
                pass
        else:
            logger.exception("Error editing leaderboard caption; fallback to text.")
            try:
                await query.message.edit_text(
                    text=f"⚠️ Failed to update caption, showing text instead.\n\n{text}",
                    reply_markup=pager,
                    parse_mode="HTML",
                )
                await query.answer()
            except Exception:
                logger.exception("Fallback also failed for leaderboard caption update.")


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_leaderboard_initial(update, context)


async def leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = (query.data or "").strip()
    try:
        if not data.startswith("leaderboard_"):
            return await query.answer()
        # ⚡ FIX: Read page number correctly
        page = int(data.split("_", 1)[1])
        await _edit_leaderboard_page(update, context, page)
    except (IndexError, ValueError):
        await query.answer()


# ---------------- DAILY LEADERBOARD ----------------
from plugins.game.db import get_daily_leaderboard  # fetch daily stats

async def _send_daily_leaderboard_initial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    viewer_id = update.effective_user.id

    # Loading sticker
    try:
        mystic = await update.message.reply_sticker(Load_id)
    except Exception:
        mystic = await update.message.reply_text("⏳ Loading daily leaderboard...")

    all_users = get_daily_leaderboard()
    text, total_pages, page = _build_leaderboard_text(
        all_users, page=1, per_page=PER_PAGE, viewer_id=viewer_id, daily=True
    )

    pager = _build_pager_old(page, total_pages, prefix="daily_leaderboard")

    top_user_id = all_users[0]['user_id'] if all_users else viewer_id
    try:
        usr_pfp_path = await download_user_photo_by_id(top_user_id, context.bot)
    except Exception:
        usr_pfp_path = None

    # Delete the loading sticker/message
    try:
        await mystic.delete()
    except Exception:
        pass

    try:
        card = generate_card("daily_leaderboard", usr_pfp_path)
        await update.message.reply_photo(
            photo=card, caption=text, reply_markup=pager, parse_mode="HTML"
        )
    except Exception:
        await update.message.reply_text(
            text=text, reply_markup=pager, parse_mode="HTML"
        )


async def _edit_daily_leaderboard_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    query = update.callback_query
    viewer_id = query.from_user.id
    all_users = get_daily_leaderboard()

    # Build leaderboard text for this page
    text, total_pages, page = _build_leaderboard_text(
        all_users, page=page, per_page=PER_PAGE, viewer_id=viewer_id, daily=True
    )

    # ⚡ Correct prefix for pager
    pager = _build_pager_old(page, total_pages, prefix="daily_leaderboard")

    try:
        if query.message.photo:
            await query.message.edit_caption(caption=text, reply_markup=pager, parse_mode="HTML")
        else:
            await query.message.edit_text(text=text, reply_markup=pager, parse_mode="HTML")
        await query.answer()
    except Exception:
        await query.answer()


# Command handler
async def daily_leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_daily_leaderboard_initial(update, context)


# Callback handler
async def daily_leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = (query.data or "").strip()
    try:
        if not data.startswith("daily_leaderboard_"):
            return await query.answer()

        # Callback format: "daily_leaderboard_{page}"
        page = int(data.split("_", 2)[2])
        await _edit_daily_leaderboard_page(update, context, page)
    except (IndexError, ValueError):
        await query.answer()

async def users_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Determine target user
    if update.message and update.message.reply_to_message:
        user: User = update.message.reply_to_message.from_user
    else:
        user: User = update.effective_user

    user_id = user.id

    # Overall stats
    overall_stats = get_user_rank(user_id)

    # Daily stats
    from plugins.game.db import get_daily_leaderboard
    daily_users = get_daily_leaderboard()
    daily_row = next((row for row in daily_users if row['user_id'] == user_id), None)
    if daily_row:
        daily_games = daily_row['games_played']
        daily_wins = daily_row['wins']
        daily_losses = daily_row['losses']
        daily_score = daily_row['total_score']
        daily_pen = daily_row['penalties']
        daily_win_pct = round(daily_wins/daily_games*100, 1) if daily_games else 0
    else:
        daily_games = daily_wins = daily_losses = daily_score = daily_pen = daily_win_pct = 0

    # Combine into a single message
    text = f"""
🏆 𝐎𝐕𝐄𝐑𝐀𝐋𝐋 𝐑𝐀𝐍𝐊
Rank: {overall_stats['rank']}. {overall_stats['username']}
🎮 Played: {overall_stats['total_played']} | Wins: {overall_stats['wins']} | Losses: {overall_stats['losses']} | Win %: {overall_stats['win_percent']:.2f}
⭐ Total Score: {overall_stats['total_score']} | ⛔ Penalties: {overall_stats['penalties']}

📊 𝐃𝐀𝐈𝐋𝐘 𝐒𝐓𝐀𝐓𝐒
🎮 Played: {daily_games} | Wins: {daily_wins} | Losses: {daily_losses} | Win %: {daily_win_pct}
⭐ Score: {daily_score} | ⛔ Penalties: {daily_pen}

🆔 User ID: {user_id}
───────────────
"""
    await update.message.reply_text(text, parse_mode="HTML")

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from config import Load_id  # This should be the file_id of your loading sticker
import logging

logger = logging.getLogger(__name__)

async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Send a loading sticker first
    try:
        mystic = await update.message.reply_sticker(Load_id)
    except Exception:
        # Fallback to text if sticker fails
        mystic = await update.message.reply_text("🌸 Loading your stats...")

    # Determine target user
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
    elif context.args:
        arg = context.args[0]
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, arg)
            user = member.user
        except Exception:
            user = update.effective_user
    else:
        user = update.effective_user

    user_id = user.id

    # Fetch overall stats
    overall_stats = get_user_rank(user_id)

    # Fetch daily stats
    from plugins.game.db import get_daily_leaderboard
    daily_users = get_daily_leaderboard()
    daily_row = next((row for row in daily_users if row['user_id'] == user_id), None)
    if daily_row:
        daily_games = daily_row['games_played']
        daily_wins = daily_row['wins']
        daily_losses = daily_row['losses']
        daily_score = daily_row['total_score']
        daily_pen = daily_row['penalties']
        daily_win_pct = round(daily_wins/daily_games*100, 1) if daily_games else 0
    else:
        daily_games = daily_wins = daily_losses = daily_score = daily_pen = daily_win_pct = 0

    # Build message for overall stats
    overall_msg = f"""
╭━━━ ⟢ 𝗢𝘃𝗲𝗿𝗮𝗹𝗹 𝗦𝘁𝗮𝘁𝘀 ⟢ ━━━╮
┃ 👤 <b>{user.first_name}</b>
╰━━━━━━━━━━━━━━━━━━━╯
🏆 𝐑𝐚𝐧𝐤: {overall_stats['rank']}
🎮 Games Played: {overall_stats['total_played']}
🥇 Wins: {overall_stats['wins']} | Losses: {overall_stats['losses']}
📊 Win %: {overall_stats['win_percent']:.2f}%
⭐ Total Score: {overall_stats['total_score']}
⛔ Penalties: {overall_stats['penalties']}
━━━━━━━━━━━━━━━━━━━━━
💡 <i>One match doesn’t define you — the comeback will! 🚀</i>
"""

    # Inline buttons
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Daily Stats", callback_data=f"userinfo_daily_{user_id}"),
            InlineKeyboardButton("🏆 Overall Stats", callback_data=f"userinfo_overall_{user_id}")
        ]
    ])

    # Download profile pic for card
    try:
        usr_pfp_path = await download_user_photo_by_id(user.id, context.bot)
    except Exception:
        logger.exception("Failed to download user photo; using default card background.")
        usr_pfp_path = None

    # Delete the loading sticker or message
    try:
        await mystic.delete()
    except Exception:
        pass

    # Send the final stats
    try:
        card = generate_card("userinfo", usr_pfp_path)
        await update.message.reply_photo(photo=card, caption=overall_msg, parse_mode="HTML", reply_markup=buttons)
    except Exception:
        await update.message.reply_text(overall_msg, parse_mode="HTML", reply_markup=buttons)

async def userinfo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data  # "userinfo_daily_12345" or "userinfo_overall_12345"
    parts = data.split("_")
    if len(parts) != 3:
        return await query.answer()

    _, view_type, user_id = parts  # Correct: ignore first part "userinfo"
    user_id = int(user_id)

    if view_type == "daily":
        from plugins.game.db import get_daily_leaderboard
        daily_users = get_daily_leaderboard()

        # Sort by total_score descending to compute rank
        daily_users_sorted = sorted(daily_users, key=lambda x: x['total_score'], reverse=True)
        row = next((r for r in daily_users_sorted if r['user_id'] == user_id), None)
        if row:
            games, wins, losses, score, pen = row['games_played'], row['wins'], row['losses'], row['total_score'], row['penalties']
            win_pct = round(wins/games*100,1) if games else 0
            # Daily rank
            rank = daily_users_sorted.index(row) + 1
        else:
            games = wins = losses = score = pen = win_pct = rank = 0

        text = f"""
╭━━━ ⟢ 𝗗𝗮𝗶𝗹𝘆 𝗦𝘁𝗮𝘁𝘀 ⟢ ━━━╮
🏆 Daily Rank: {rank}
🎮 Games: {games}
🥇 Wins: {wins} | Losses: {losses}
📊 Win %: {win_pct}%
⭐ Score: {score} | ⛔ Penalties: {pen}
━━━━━━━━━━━━━━━━━━━━━
💡 Daily stats keep you motivated! 🚀
"""
    else:
        stats = get_user_rank(user_id)
        text = f"""
╭━━━ ⟢ 𝗢𝘃𝗲𝗿𝗮𝗹𝗹 𝗦𝘁𝗮𝘁𝘀 ⟢ ━━━╮
🏆 Rank: {stats['rank']}
🎮 Games Played: {stats['total_played']}
🥇 Wins: {stats['wins']} | Losses: {stats['losses']}
📊 Win %: {stats['win_percent']:.2f}%
⭐ Total Score: {stats['total_score']} | ⛔ Penalties: {stats['penalties']}
━━━━━━━━━━━━━━━━━━━━━
💡 Track your progress over time! 🚀
"""

    # Buttons
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Daily Stats", callback_data=f"userinfo_daily_{user_id}"),
            InlineKeyboardButton("🏆 Overall Stats", callback_data=f"userinfo_overall_{user_id}")
        ]
    ])

    # Always check if message has photo; choose edit method accordingly
    if query.message.photo:
        try:
            await query.message.edit_caption(caption=text, reply_markup=buttons, parse_mode="HTML")
        except Exception:
            await query.message.edit_text(text=text, reply_markup=buttons, parse_mode="HTML")
    else:
        try:
            await query.message.edit_text(text=text, reply_markup=buttons, parse_mode="HTML")
        except Exception:
            await query.message.edit_caption(caption=text, reply_markup=buttons, parse_mode="HTML")

    await query.answer()

