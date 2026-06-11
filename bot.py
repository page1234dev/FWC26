import logging
import os
import re
from datetime import datetime, date, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters, ChatMemberHandler
)
from database import db
from matches import get_todays_matches, get_match_by_id, WC2026_MATCHES, add_custom_match
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set!")
CHANNEL_USERNAME = "@FIFAWCUP_26"
CHANNEL_LINK = "https://t.me/FIFAWCUP_26"
TWITTER_LINK = "https://twitter.com/NGNTOKEN157667"
DEPOSIT_SOL_ADDRESS = "3ertaKWosasxdrvURs2GzWvGAi6HQE9RV8SFjkpyWTgW"
ADMIN_ID = 8710356869

MIN_BET = 50
MAX_BET = 200
MIN_WITHDRAW = 700
WITHDRAW_TOKENS = 100
TOKEN_PRIZE_POOL = 5000
BET_CUTOFF_MINUTES = 30   # betting closes 30 min before match kickoff

# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────
def is_valid_sol_wallet(addr):
    return bool(re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', addr))

async def notify_admin(context, text):
    try:
        await context.bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Admin notify failed: {e}")

def parse_match_time_utc(match):
    """
    Parse match['time'] like '20:00 UTC' or '20:00UTC' on match['date'] (YYYY-MM-DD).
    Returns a UTC-aware datetime, or None if unparseable.
    """
    try:
        time_str = match["time"].replace("UTC", "").strip()
        dt_str = f"{match['date']} {time_str}"
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def is_betting_open(match):
    """
    Returns (bool, str) — (open, reason_if_closed).
    Betting is open until BET_CUTOFF_MINUTES before kickoff.
    """
    # Already settled?
    if db.is_match_settled(match["id"]):
        return False, "This match has already been settled."

    kickoff = parse_match_time_utc(match)
    if kickoff is None:
        return True, ""   # Can't parse time → don't block (fail open)

    now = datetime.now(timezone.utc)
    minutes_to_kickoff = (kickoff - now).total_seconds() / 60

    if minutes_to_kickoff < 0:
        return False, f"Match has already kicked off."
    if minutes_to_kickoff < BET_CUTOFF_MINUTES:
        mins_left = int(minutes_to_kickoff)
        return False, f"Betting closed! Kicks off in ~{mins_left} min (closes {BET_CUTOFF_MINUTES} min before kickoff)."
    return True, ""

# ─────────────────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    referrer_id = int(args[0]) if args and args[0].isdigit() else None

    is_new = db.register_user(user.id, user.first_name, user.username, referrer_id)

    if is_new and referrer_id and referrer_id != user.id:
        ref_count = db.get_referral_count(referrer_id)
        if ref_count <= 20:
            db.add_tokens(referrer_id, 50)
            try:
                cap_note = "" if ref_count < 20 else "\n_(You've reached the 20-referral cap — no more bonus tokens)_"
                await context.bot.send_message(
                    referrer_id,
                    f"🎉 *New Referral!* Someone joined using your link!\n"
                    f"You earned *50 FWC26 tokens!* Keep sharing! 🔥{cap_note}",
                    parse_mode="Markdown"
                )
            except: pass

    keyboard = [
        [InlineKeyboardButton("📋 My Tasks", callback_data="tasks"),
         InlineKeyboardButton("💰 My Wallet", callback_data="balance")],
        [InlineKeyboardButton("⚽ Today's Bets", callback_data="todays_bets"),
         InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("👥 Refer Friends", callback_data="referral"),
         InlineKeyboardButton("💳 Deposit", callback_data="deposit")],
        [InlineKeyboardButton("🏦 Withdraw", callback_data="withdraw")]
    ]

    await update.message.reply_text(
        f"⚽ *Welcome to FWC26 Bot!* ⚽\n\n"
        f"The official FIFA World Cup 2026 prediction game!\n\n"
        f"🪙 *How it works:*\n"
        f"• Complete tasks → earn free FWC26 tokens\n"
        f"• Bet on daily World Cup matches (min {MIN_BET} / max {MAX_BET} tokens)\n"
        f"• Betting closes *{BET_CUTOFF_MINUTES} minutes before kickoff* ⏰\n"
        f"• Win = double your bet 🎉\n"
        f"• Lose = tokens add to liquidity pool 🔥\n"
        f"• Draw = tokens refunded 🤝\n"
        f"• Withdraw 100 tokens = $1 (min balance: 700 tokens)\n"
        f"• Top 10 leaderboard share *{TOKEN_PRIZE_POOL} tokens* at tournament end!\n\n"
        f"👇 *Get started below:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ─────────────────────────────────────────────────────────
# NEW MEMBER WELCOME IN CHANNEL
# ─────────────────────────────────────────────────────────
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result: ChatMemberUpdated = update.chat_member
    if result.new_chat_member.status == "member":
        user = result.new_chat_member.user
        bot_username = (await context.bot.get_me()).username
        await context.bot.send_message(
            result.chat.id,
            f"👋 Welcome *{user.first_name}* to *FWC26 Updates!* ⚽🔥\n\n"
            f"🤖 *Bot* — Bet on matches, earn tokens, refer friends\n"
            f"👉 @{bot_username}\n\n"
            f"📢 *This Channel* — Daily leaderboard, match results\n"
            f"👉 {CHANNEL_LINK}\n\n"
            f"🐦 *Twitter/X* — Announcements\n"
            f"👉 {TWITTER_LINK}\n\n"
            f"🏆 Top 10 share *{TOKEN_PRIZE_POOL} tokens* at launch!\n\n"
            f"Start earning now 👉 @{bot_username}",
            parse_mode="Markdown"
        )

# ─────────────────────────────────────────────────────────
# TASKS
# ─────────────────────────────────────────────────────────
async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = db.get_user(query.from_user.id)

    def s(done): return "✅" if done else "⬜"

    text = (
        f"📋 *Your Tasks*\n\n"
        f"{s(user['task_channel'])} *Task 1* — Join Telegram Channel → *+100 tokens*\n"
        f"{s(user['task_twitter'])} *Task 2* — Follow on Twitter/X → *+100 tokens*\n"
        f"{s(user['task_referral'])} *Task 3* — Refer 1 friend → *+50 tokens per referral*\n\n"
        f"Complete all tasks to unlock full betting access! 🚀"
    )

    kb = []
    if not user["task_channel"]:
        kb += [[InlineKeyboardButton("📢 Join Channel", url=CHANNEL_LINK)],
               [InlineKeyboardButton("✅ Verify Channel Join", callback_data="verify_channel")]]
    if not user["task_twitter"]:
        kb += [[InlineKeyboardButton("🐦 Follow on Twitter/X", url=TWITTER_LINK)],
               [InlineKeyboardButton("✅ I Followed Twitter", callback_data="verify_twitter")]]
    if not user["task_referral"]:
        kb += [[InlineKeyboardButton("👥 Get Referral Link", callback_data="referral")]]
    kb += [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def verify_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        if member.status in ["member", "administrator", "creator"]:
            user = db.get_user(user_id)
            if not user["task_channel"]:
                db.complete_task(user_id, "task_channel")
                db.add_tokens(user_id, 100)
                await query.edit_message_text("✅ *Channel task complete!* +100 tokens! 🎉\n\nUse /start to continue.", parse_mode="Markdown")
            else:
                await query.edit_message_text("Already completed! Use /start to continue.")
        else:
            await query.edit_message_text(f"❌ You haven't joined yet!\n\nJoin: {CHANNEL_LINK}\nThen verify again.")
    except:
        await query.edit_message_text(f"❌ Couldn't verify. Join: {CHANNEL_LINK} then try again.")


async def verify_twitter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = db.get_user(user_id)
    if not user["task_twitter"]:
        db.complete_task(user_id, "task_twitter")
        db.add_tokens(user_id, 100)
        await query.edit_message_text("✅ *Twitter task complete!* +100 tokens! 🎉\n\nUse /start to continue.", parse_mode="Markdown")
    else:
        await query.edit_message_text("Already completed! Use /start to continue.")

# ─────────────────────────────────────────────────────────
# SOL WALLET
# ─────────────────────────────────────────────────────────
async def set_wallet_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "wallet"
    await query.edit_message_text(
        "🔑 *Add Your Solana Wallet*\n\n"
        "Please send your Solana wallet address.\n"
        "_This is required for withdrawals._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="balance")]])
    )

# ─────────────────────────────────────────────────────────
# BALANCE / WALLET
# ─────────────────────────────────────────────────────────
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = db.get_user(user_id)
    wallet = user["sol_wallet"] or "Not set"
    short_wallet = (wallet[:6] + "..." + wallet[-4:]) if user["sol_wallet"] else "❌ Not set"

    text = (
        f"💰 *Your FWC26 Wallet*\n\n"
        f"🪙 Balance: *{user['tokens']} FWC26*\n"
        f"📈 Total Won: *{user['total_won']} tokens*\n"
        f"📉 Total Lost: *{user['total_lost']} tokens*\n"
        f"🔑 SOL Wallet: `{short_wallet}`\n\n"
        f"_Min withdraw: 700 tokens | 100 tokens = $1_"
    )

    kb = [
        [InlineKeyboardButton("💳 Deposit", callback_data="deposit"),
         InlineKeyboardButton("🏦 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("🔑 Set/Update Wallet", callback_data="set_wallet")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# ─────────────────────────────────────────────────────────
# DEPOSIT
# ─────────────────────────────────────────────────────────
async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        f"💳 *Deposit SOL to Get Tokens*\n\n"
        f"Send SOL to this address:\n"
        f"`{DEPOSIT_SOL_ADDRESS}`\n\n"
        f"📌 *Rate:* 1 SOL = 1000 FWC26 tokens\n\n"
        f"After sending:\n"
        f"1. Copy your transaction hash (txn ID)\n"
        f"2. Press the button below and paste it\n"
        f"3. Admin will verify and credit your tokens within 30 mins\n\n"
        f"_Always double-check the address before sending!_ ⚠️"
    )
    kb = [
        [InlineKeyboardButton("📨 Submit Transaction Hash", callback_data="submit_txn")],
        [InlineKeyboardButton("🔙 Back", callback_data="balance")]
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def submit_txn_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting"] = "txn_hash"
    await query.edit_message_text(
        "📨 *Submit Transaction Hash*\n\n"
        "Please paste your Solana transaction hash (txn ID):\n\n"
        "_Example: 5KtP...xQmZ_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="deposit")]])
    )

# ─────────────────────────────────────────────────────────
# WITHDRAW
# ─────────────────────────────────────────────────────────
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id   # FIX: was using undefined 'user_id' variable
    user = db.get_user(user_id)

    if user["tokens"] < MIN_WITHDRAW:
        await query.edit_message_text(
            f"❌ *Insufficient Balance*\n\n"
            f"You need at least *700 tokens* to withdraw.\n"
            f"Your balance: *{user['tokens']} tokens*\n\n"
            f"Keep betting and earning to reach 700! 🚀",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="balance")]])
        )
        return

    if not user["sol_wallet"]:
        await query.edit_message_text(
            f"❌ *No SOL Wallet Set*\n\nPlease add your Solana wallet first.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔑 Set Wallet", callback_data="set_wallet")],
                [InlineKeyboardButton("🔙 Back", callback_data="balance")]
            ])
        )
        return

    already_today = db.get_daily_withdrawn(user_id)
    remaining_today = max(0, 100 - already_today)
    short_wallet = user["sol_wallet"][:6] + "..." + user["sol_wallet"][-4:]

    await query.edit_message_text(
        f"🏦 *Withdraw Tokens*\n\n"
        f"💰 Available: *{user['tokens']} tokens*\n"
        f"📅 Daily limit: *100 tokens/day* | Remaining today: *{remaining_today} tokens*\n"
        f"🔑 Wallet: `{short_wallet}`\n\n"
        f"_100 tokens = $1 | Sent to your SOL wallet_\n\n"
        f"How much do you want to withdraw?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("100 tokens ($1)", callback_data="do_withdraw_100")],
            [InlineKeyboardButton("🔙 Back", callback_data="balance")]
        ])
    )


async def do_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    amount = int(query.data.replace("do_withdraw_", ""))
    user = db.get_user(user_id)

    if user["tokens"] < MIN_WITHDRAW or user["tokens"] < amount:
        await query.edit_message_text("❌ Insufficient balance. Use /start to check.", parse_mode="Markdown")
        return

    DAILY_WITHDRAW_LIMIT = 100
    already_withdrawn_today = db.get_daily_withdrawn(user_id)
    if already_withdrawn_today >= DAILY_WITHDRAW_LIMIT:
        await query.edit_message_text(
            f"❌ *Daily Withdrawal Limit Reached*\n\n"
            f"You can only withdraw *100 tokens per day*.\n"
            f"Already withdrawn: *{already_withdrawn_today} tokens* today.\n\n"
            f"Come back tomorrow! ⏳",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="balance")]])
        )
        return

    if amount + already_withdrawn_today > DAILY_WITHDRAW_LIMIT:
        allowed = DAILY_WITHDRAW_LIMIT - already_withdrawn_today
        await query.edit_message_text(
            f"❌ *Over Daily Limit*\n\n"
            f"You can only withdraw *{allowed} more tokens* today.\n"
            f"Already withdrawn: *{already_withdrawn_today} tokens*.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="withdraw")]])
        )
        return

    db.request_withdrawal(user_id, amount, user["sol_wallet"])
    usd = amount / 100

    await query.edit_message_text(
        f"✅ *Withdrawal Requested!*\n\n"
        f"Amount: *{amount} tokens = ${usd:.2f}*\n"
        f"Wallet: `{user['sol_wallet'][:6]}...{user['sol_wallet'][-4:]}`\n\n"
        f"Admin will process within 24 hours. ⏳",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="main_menu")]])
    )

    await notify_admin(
        context,
        f"💸 *Withdrawal Request*\n\n"
        f"User: {user['name']} (@{user['username']})\n"
        f"ID: `{user_id}`\n"
        f"Amount: *{amount} tokens = ${usd:.2f}*\n"
        f"Wallet: `{user['sol_wallet']}`\n\n"
        f"Use `/approvewithdraw <withdrawal_id>` to approve"
    )

# ─────────────────────────────────────────────────────────
# REFERRAL
# ─────────────────────────────────────────────────────────
async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={user_id}"
    total_refs = db.get_referral_count(user_id)

    await query.edit_message_text(
        f"👥 *Your Referral Link*\n\n"
        f"`{link}`\n\n"
        f"Each referral = *50 FWC26 tokens* (~$0.50)\n"
        f"📊 Total referrals: *{total_refs} / 20*\n"
        f"💰 Earned from referrals: *{total_refs * 50} tokens*\n\n"
        f"{'🔒 *Referral cap reached (20/20)*' if total_refs >= 20 else 'Share everywhere — Twitter, WhatsApp, TikTok! 🚀'}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])
    )

# ─────────────────────────────────────────────────────────
# TODAY'S BETS
# ─────────────────────────────────────────────────────────
async def todays_bets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = db.get_user(user_id)

    if user["task_channel"] + user["task_twitter"] < 1:
        await query.edit_message_text(
            "⚠️ Complete at least *1 task* to unlock betting!\n\nUse /start → My Tasks",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Go to Tasks", callback_data="tasks")]])
        )
        return

    matches = get_todays_matches()
    if not matches:
        await query.edit_message_text(
            "😴 *No matches today!*\n\nCheck back tomorrow! 🔥",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])
        )
        return

    text = (
        f"⚽ *Today's Matches — {date.today().strftime('%b %d, %Y')}*\n\n"
        f"💰 Balance: *{user['tokens']} tokens*\n"
        f"Bet: {MIN_BET}–{MAX_BET} tokens\n"
        f"⏰ Betting closes *{BET_CUTOFF_MINUTES} min before kickoff*\n\n"
    )
    kb = []
    for m in matches:
        existing = db.get_user_bet(user_id, m["id"])
        open_for_bets, _ = is_betting_open(m)
        if existing:
            icon = "✅"
        elif not open_for_bets:
            icon = "🔒"
        else:
            icon = "🎯"
        kb.append([InlineKeyboardButton(
            f"{icon} {m['home']} vs {m['away']} — {m['time']}",
            callback_data=f"bet_match_{m['id']}"
        )])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def bet_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    # FIX: match_id is everything after "bet_match_" — don't split on "_" again
    match_id = query.data[len("bet_match_"):]
    match = get_match_by_id(match_id)
    if not match:
        await query.edit_message_text("❌ Match not found. It may have been removed.")
        return

    # Check if betting is open
    open_for_bets, reason = is_betting_open(match)
    if not open_for_bets:
        await query.edit_message_text(
            f"🔒 *Betting Closed*\n\n{reason}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="todays_bets")]])
        )
        return

    existing = db.get_user_bet(user_id, match_id)
    if existing:
        pred = match["home"] if existing["prediction"] == "home" else match["away"]
        await query.edit_message_text(
            f"✅ *Already Bet!*\n\n{match['home']} vs {match['away']}\nYour pick: *{pred} Wins*\nAmount: *{existing['amount']} tokens*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="todays_bets")]])
        )
        return

    user = db.get_user(user_id)
    kb = [
        [InlineKeyboardButton(f"🏠 {match['home']} — 50t", callback_data=f"place_bet_{match_id}|home|50"),
         InlineKeyboardButton(f"✈️ {match['away']} — 50t", callback_data=f"place_bet_{match_id}|away|50")],
        [InlineKeyboardButton(f"🏠 {match['home']} — 100t", callback_data=f"place_bet_{match_id}|home|100"),
         InlineKeyboardButton(f"✈️ {match['away']} — 100t", callback_data=f"place_bet_{match_id}|away|100")],
        [InlineKeyboardButton(f"🏠 {match['home']} — 200t", callback_data=f"place_bet_{match_id}|home|200"),
         InlineKeyboardButton(f"✈️ {match['away']} — 200t", callback_data=f"place_bet_{match_id}|away|200")],
        [InlineKeyboardButton("🔙 Back", callback_data="todays_bets")]
    ]
    await query.edit_message_text(
        f"⚽ *{match['home']} vs {match['away']}*\n🕐 {match['time']}\n\n"
        f"💰 Your balance: *{user['tokens']} tokens*\n\n"
        f"Pick your team and bet amount:\n_(Draw = tokens refunded)_",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )


async def place_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # FIX: use "|" as delimiter instead of "_" to avoid match_id parsing issues
    raw = query.data[len("place_bet_"):]
    parts = raw.split("|")
    if len(parts) != 3:
        await query.edit_message_text("❌ Invalid bet data. Please try again.")
        return
    match_id, prediction, amount = parts[0], parts[1], int(parts[2])

    match = get_match_by_id(match_id)
    if not match:
        await query.edit_message_text("❌ Match not found.")
        return

    # Re-check betting window at submission time (anti-cheat)
    open_for_bets, reason = is_betting_open(match)
    if not open_for_bets:
        await query.edit_message_text(
            f"🔒 *Betting Closed*\n\n{reason}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="todays_bets")]])
        )
        return

    user = db.get_user(user_id)

    if user["tokens"] < amount:
        await query.edit_message_text(
            f"❌ Not enough tokens!\nYou have *{user['tokens']}* but need *{amount}*.\n\nDeposit or refer friends to earn more!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="todays_bets")]])
        )
        return

    pred_label = match["home"] if prediction == "home" else match["away"]

    # Atomic: place bet + deduct tokens (DB unique constraint prevents double-bet)
    placed = db.place_bet(user_id, match_id, prediction, amount)
    if not placed:
        await query.edit_message_text(
            "⚠️ *Already bet on this match!*\n\nYou can only place one bet per match.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="todays_bets")]])
        )
        return

    db.deduct_tokens(user_id, amount)

    await query.edit_message_text(
        f"✅ *Bet Placed!*\n\n"
        f"⚽ {match['home']} vs {match['away']}\n"
        f"Your Pick: *{pred_label} Wins*\n"
        f"Amount: *{amount} tokens*\n\n"
        f"Good luck! Results posted after match. 🔥",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚽ More Bets", callback_data="todays_bets"),
             InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
        ])
    )

# ─────────────────────────────────────────────────────────
# LEADERBOARD
# ─────────────────────────────────────────────────────────
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    top = db.get_leaderboard()
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    text = f"🏆 *FWC26 Leaderboard*\n\n"
    for i, u in enumerate(top):
        text += f"{medals[i]} *{u['name']}* — {u['tokens']} tokens\n"
    text += f"\n🎁 Top 10 share *{TOKEN_PRIZE_POOL} tokens* at tournament end!\n_Updated daily_ 🔥"
    await query.edit_message_text(text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]))

# ─────────────────────────────────────────────────────────
# TEXT MESSAGE HANDLER
# ─────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting")
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if awaiting == "wallet":
        if is_valid_sol_wallet(text):
            db.set_wallet(user_id, text)
            context.user_data.pop("awaiting", None)
            await update.message.reply_text(
                f"✅ *SOL Wallet Saved!*\n\n`{text}`\n\nYou can now deposit and withdraw. Use /start to continue.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Invalid Solana wallet address. Please try again or use /start to cancel.")

    elif awaiting == "txn_hash":
        if len(text) > 20:
            user = db.get_user(user_id)
            success = db.submit_deposit(user_id, text, 0)
            if success:
                context.user_data.pop("awaiting", None)
                await update.message.reply_text(
                    f"✅ *Transaction Submitted!*\n\n`{text}`\n\nAdmin will verify and credit your tokens within 30 mins. ⏳",
                    parse_mode="Markdown"
                )
                await notify_admin(
                    context,
                    f"💳 *Deposit Request*\n\n"
                    f"User: {user['name']} (@{user['username']})\n"
                    f"ID: `{user_id}`\n"
                    f"TXN: `{text}`\n\n"
                    f"Use `/approvedeposit <deposit_id> <tokens>` to approve"
                )
            else:
                await update.message.reply_text("❌ This transaction hash was already submitted. Contact admin if this is an error.")
        else:
            await update.message.reply_text("❌ Invalid transaction hash. Please paste the full hash.")

    elif awaiting == "broadcast":
        if user_id == ADMIN_ID:
            all_users = db.get_all_users()
            sent = 0
            for uid in all_users:
                try:
                    await context.bot.send_message(uid, f"📢 *Announcement*\n\n{text}", parse_mode="Markdown")
                    sent += 1
                except: pass
            context.user_data.pop("awaiting", None)
            await update.message.reply_text(f"✅ Broadcast sent to {sent} users.")

# ─────────────────────────────────────────────────────────
# ADMIN COMMANDS
# ─────────────────────────────────────────────────────────
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    stats = db.get_stats()
    deps = db.get_pending_deposits()
    wds = db.get_pending_withdrawals()
    await update.message.reply_text(
        f"📊 *Admin Dashboard*\n\n"
        f"👥 Users: {stats['users']}\n"
        f"🪙 Tokens in circulation: {stats['tokens']}\n"
        f"🔥 Liquidity Pool: {stats['liquidity']}\n"
        f"🎯 Total Bets: {stats['bets']}\n"
        f"✅ Won: {stats['won']} | ❌ Lost: {stats['lost']}\n"
        f"📅 Today — Bets: {stats['bets_today']} | Won: {stats['won_today']} | Lost: {stats['lost_today']}\n\n"
        f"💳 Pending Deposits: {len(deps)}\n"
        f"🏦 Pending Withdrawals: {len(wds)}\n\n"
        f"Commands:\n"
        f"`/deposits` — view pending deposits\n"
        f"`/withdrawals` — view pending withdrawals\n"
        f"`/settle <id> <home|away|draw>` — settle match\n"
        f"`/sendtokens <user_id> <amount>` — send tokens\n"
        f"`/announce <msg>` — post to channel\n"
        f"`/broadcast` — message all users\n"
        f"`/addmatch <id> <home> <away> <YYYY-MM-DD> <HH:MM>` — add match",
        parse_mode="Markdown"
    )


async def admin_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    deps = db.get_pending_deposits()
    if not deps:
        await update.message.reply_text("No pending deposits.")
        return
    for d in deps:
        await update.message.reply_text(
            f"💳 *Deposit #{d['id']}*\n"
            f"User: {d['name']} (@{d['username']}) ID:`{d['user_id']}`\n"
            f"TXN: `{d['txn_hash']}`\n"
            f"Submitted: {d['submitted_at']}\n\n"
            f"Approve: `/approvedeposit {d['id']} <tokens>`",
            parse_mode="Markdown"
        )


async def admin_approve_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /approvedeposit <deposit_id> <tokens>")
        return
    dep = db.approve_deposit(int(args[0]), int(args[1]))
    if dep:
        await update.message.reply_text(f"✅ Approved! {args[1]} tokens sent to user {dep['user_id']}")
        try:
            await context.bot.send_message(
                dep["user_id"],
                f"✅ *Deposit Approved!*\n\n*+{args[1]} FWC26 tokens* added to your wallet! 🎉\nUse /start to check your balance.",
                parse_mode="Markdown"
            )
        except: pass
    else:
        await update.message.reply_text("❌ Deposit not found.")


async def admin_withdrawals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    wds = db.get_pending_withdrawals()
    if not wds:
        await update.message.reply_text("No pending withdrawals.")
        return
    for w in wds:
        await update.message.reply_text(
            f"🏦 *Withdrawal #{w['id']}*\n"
            f"User: {w['name']} (@{w['username']}) ID:`{w['user_id']}`\n"
            f"Amount: *{w['tokens']} tokens = ${w['usd_value']:.2f}*\n"
            f"Wallet: `{w['sol_wallet']}`\n"
            f"Requested: {w['requested_at']}\n\n"
            f"Approve: `/approvewithdraw {w['id']}`",
            parse_mode="Markdown"
        )


async def admin_approve_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /approvewithdraw <withdrawal_id>")
        return
    db.approve_withdrawal(int(args[0]))
    await update.message.reply_text(f"✅ Withdrawal #{args[0]} marked as approved. Send SOL manually.")


async def admin_send_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /sendtokens <user_id> <amount>")
        return
    user_id, amount = int(args[0]), int(args[1])
    db.add_tokens(user_id, amount)
    await update.message.reply_text(f"✅ Sent {amount} tokens to user {user_id}")
    try:
        await context.bot.send_message(user_id, f"🎁 *{amount} FWC26 tokens* added to your wallet by admin! Use /start to check.", parse_mode="Markdown")
    except: pass


async def admin_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("Usage: /announce <message>")
        return
    await context.bot.send_message(CHANNEL_USERNAME, f"📢 *ANNOUNCEMENT*\n\n{msg}", parse_mode="Markdown")
    await update.message.reply_text("✅ Sent to channel!")


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    context.user_data["awaiting"] = "broadcast"
    await update.message.reply_text("Type your broadcast message and send it:")


async def admin_settle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /settle <match_id> <home|away|draw>")
        return
    await settle_match_result(context, args[0], args[1])
    await update.message.reply_text(f"✅ Match {args[0]} settled as: {args[1]}")


async def admin_add_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usage: /addmatch m25 Brazil Germany 2026-06-25 21:00
    Time should be HH:MM (UTC assumed). No spaces in team names — use underscores if needed.
    """
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if len(args) < 5:
        await update.message.reply_text(
            "Usage: /addmatch <id> <home> <away> <YYYY-MM-DD> <HH:MM>\n\n"
            "Example: `/addmatch m25 Brazil Germany 2026-06-25 21:00`",
            parse_mode="Markdown"
        )
        return

    match_id = args[0]
    home = args[1]
    away = args[2]
    match_date = args[3]
    time_utc = args[4] + " UTC"   # Normalise to "HH:MM UTC"

    # Validate date format
    try:
        datetime.strptime(match_date, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("❌ Invalid date format. Use YYYY-MM-DD.")
        return

    # Validate time format
    try:
        datetime.strptime(args[4], "%H:%M")
    except ValueError:
        await update.message.reply_text("❌ Invalid time format. Use HH:MM (e.g. 21:00).")
        return

    # Check for duplicate ID
    if get_match_by_id(match_id):
        await update.message.reply_text(f"❌ Match ID `{match_id}` already exists. Use a different ID.", parse_mode="Markdown")
        return

    # Add to in-memory list AND persist to DB
    add_custom_match(match_id, home, away, match_date, time_utc)
    db.save_custom_match(match_id, home, away, match_date, time_utc)

    await update.message.reply_text(
        f"✅ *Match Added!*\n\n"
        f"🆔 ID: `{match_id}`\n"
        f"⚽ {home} vs {away}\n"
        f"📅 {match_date} at {time_utc}\n\n"
        f"Users will see it under Today's Bets on {match_date}.",
        parse_mode="Markdown"
    )

# ─────────────────────────────────────────────────────────
# SETTLE MATCH
# ─────────────────────────────────────────────────────────
async def settle_match_result(context, match_id, result):
    bets = db.get_bets_for_match(match_id)
    match = get_match_by_id(match_id)
    total_lost = 0

    for bet in bets:
        if result == "draw":
            db.add_tokens(bet["user_id"], bet["amount"])
            try:
                await context.bot.send_message(bet["user_id"],
                    f"🤝 *Draw!* Your {bet['amount']} tokens have been refunded. ⚽", parse_mode="Markdown")
            except: pass
        elif bet["prediction"] == result:
            win = bet["amount"] * 2
            db.add_tokens(bet["user_id"], win)
            db.record_win(bet["user_id"], match_id, bet["amount"])   # FIX: pass match_id
            try:
                await context.bot.send_message(bet["user_id"],
                    f"🎉 *You Won!* +{win} FWC26 tokens added! 🔥\nKeep betting to grow your stack!", parse_mode="Markdown")
            except: pass
        else:
            total_lost += bet["amount"]
            db.record_loss(bet["user_id"], match_id, bet["amount"])  # FIX: pass match_id
            db.add_liquidity(bet["amount"])
            try:
                await context.bot.send_message(bet["user_id"],
                    f"😔 Your {bet['amount']} tokens were lost this time.\n"
                    f"They've been added to the FWC26 liquidity pool 🔥\n"
                    f"The pool grows = token launches higher! Keep betting!", parse_mode="Markdown")
            except: pass

    db.mark_match_settled(match_id, result)
    stats = db.get_stats()
    if match and result != "draw":
        winner = match["home"] if result == "home" else match["away"]
        try:
            await context.bot.send_message(
                CHANNEL_USERNAME,
                f"⚽ *Match Result!*\n\n"
                f"*{match['home']} vs {match['away']}*\n"
                f"🏆 Winner: *{winner}*\n\n"
                f"🔥 *{total_lost} FWC26 tokens* added to liquidity pool!\n"
                f"🏊 Total Pool: *{stats['liquidity']} tokens*\n\n"
                f"_The bigger the pool, the higher the launch price!_ 🚀\n"
                f"Start betting 👉 @NGNTOKENbot",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Channel result post error: {e}")

# ─────────────────────────────────────────────────────────
# DAILY CHANNEL UPDATE
# ─────────────────────────────────────────────────────────
async def daily_channel_update(app):
    try:
        stats = db.get_stats()
        top = db.get_leaderboard(10)
        medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        board = "".join([f"{medals[i]} {u['name']} — {u['tokens']} tokens\n" for i, u in enumerate(top)])
        matches = get_todays_matches()
        match_text = "".join([f"⚽ {m['home']} vs {m['away']} — {m['time']}\n" for m in matches]) or "No matches today\n"

        await app.bot.send_message(
            CHANNEL_USERNAME,
            f"🌅 *Good Morning! FWC26 Daily Update*\n"
            f"📅 {date.today().strftime('%B %d, %Y')}\n\n"
            f"👥 Total Players: *{stats['users']}*\n"
            f"🔥 Liquidity Pool: *{stats['liquidity']} tokens*\n\n"
            f"🏆 *Leaderboard Top 10*\n{board}\n"
            f"🎁 Top 10 share *{TOKEN_PRIZE_POOL} tokens* at launch!\n\n"
            f"📅 *Today's Matches*\n{match_text}\n"
            f"👉 Place your bets now: @NGNTOKENbot",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Morning update error: {e}")


async def daily_engagement_blast(app):
    try:
        stats = db.get_stats()
        bot_username = (await app.bot.get_me()).username
        matches = get_todays_matches()
        match_text = "".join([f"⚽ {m['home']} vs {m['away']} — {m['time']}\n" for m in matches]) or "No matches scheduled today\n"

        await app.bot.send_message(
            CHANNEL_USERNAME,
            f"🔔 *Evening Reminder!* ⚽\n\n"
            f"Don't miss today's matches:\n{match_text}\n"
            f"━━━━━━━━━━━━━━\n"
            f"📋 *Haven't done your tasks yet?*\n"
            f"Join channel + follow Twitter = *200 FREE tokens!*\n\n"
            f"👥 *Refer friends* = *50 tokens each*\n\n"
            f"💳 *Want more tokens?* Deposit SOL:\n"
            f"`{DEPOSIT_SOL_ADDRESS}`\n"
            f"1 SOL = 1000 FWC26 tokens 🔥\n\n"
            f"🏦 *Have 700+ tokens?* You can withdraw!\n"
            f"100 tokens = $1 to your SOL wallet\n\n"
            f"🔥 Liquidity Pool: *{stats['liquidity']} tokens*\n\n"
            f"👉 @{bot_username}",
            parse_mode="Markdown"
        )

        all_users = db.get_all_users()
        for uid in all_users:
            try:
                user = db.get_user(uid)
                if not user: continue
                tasks_left = (1 - user["task_channel"]) + (1 - user["task_twitter"])
                pending_tokens = tasks_left * 100
                lines = [f"🔔 *FWC26 Daily Reminder!* ⚽\n"]
                if tasks_left > 0:
                    lines.append(f"⚠️ You still have *{tasks_left} task(s)* left!\nComplete them for *{pending_tokens} free tokens!*\n")
                if user["tokens"] >= MIN_WITHDRAW:
                    lines.append(f"💸 You have *{user['tokens']} tokens* — you can *withdraw now!*\n100 tokens = $1 🎉\n")
                else:
                    needed = MIN_WITHDRAW - user["tokens"]
                    lines.append(f"🪙 Balance: *{user['tokens']} tokens* — need *{needed} more* to withdraw!\n")
                if matches:
                    lines.append(f"⚽ *Today's matches — place your bets!*\n")
                lines.append(f"\n👉 /start")
                await app.bot.send_message(uid, "".join(lines), parse_mode="Markdown")
            except: pass

    except Exception as e:
        logger.error(f"Engagement blast error: {e}")

# ─────────────────────────────────────────────────────────
# MAIN MENU
# ─────────────────────────────────────────────────────────
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("📋 My Tasks", callback_data="tasks"),
         InlineKeyboardButton("💰 My Wallet", callback_data="balance")],
        [InlineKeyboardButton("⚽ Today's Bets", callback_data="todays_bets"),
         InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("👥 Refer Friends", callback_data="referral"),
         InlineKeyboardButton("💳 Deposit", callback_data="deposit")],
        [InlineKeyboardButton("🏦 Withdraw", callback_data="withdraw")]
    ]
    await query.edit_message_text("⚽ *FWC26 Bot* — Main Menu", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb))

# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────
def main():
    db.init()

    # Load custom matches from DB into in-memory list on startup
    for m in db.load_custom_matches():
        add_custom_match(m["id"], m["home"], m["away"], m["date"], m["time"])

    app = Application.builder().token(BOT_TOKEN).build()

    # User handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(show_tasks, pattern="^tasks$"))
    app.add_handler(CallbackQueryHandler(verify_channel, pattern="^verify_channel$"))
    app.add_handler(CallbackQueryHandler(verify_twitter, pattern="^verify_twitter$"))
    app.add_handler(CallbackQueryHandler(referral, pattern="^referral$"))
    app.add_handler(CallbackQueryHandler(balance, pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(set_wallet_prompt, pattern="^set_wallet$"))
    app.add_handler(CallbackQueryHandler(deposit, pattern="^deposit$"))
    app.add_handler(CallbackQueryHandler(submit_txn_prompt, pattern="^submit_txn$"))
    app.add_handler(CallbackQueryHandler(withdraw, pattern="^withdraw$"))
    app.add_handler(CallbackQueryHandler(do_withdraw, pattern="^do_withdraw_"))
    app.add_handler(CallbackQueryHandler(todays_bets, pattern="^todays_bets$"))
    app.add_handler(CallbackQueryHandler(bet_match, pattern="^bet_match_"))
    app.add_handler(CallbackQueryHandler(place_bet, pattern="^place_bet_"))
    app.add_handler(CallbackQueryHandler(leaderboard, pattern="^leaderboard$"))
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Channel welcome
    app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

    # Admin commands
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("deposits", admin_deposits))
    app.add_handler(CommandHandler("approvedeposit", admin_approve_deposit))
    app.add_handler(CommandHandler("withdrawals", admin_withdrawals))
    app.add_handler(CommandHandler("approvewithdraw", admin_approve_withdrawal))
    app.add_handler(CommandHandler("sendtokens", admin_send_tokens))
    app.add_handler(CommandHandler("announce", admin_announce))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("settle", admin_settle))
    app.add_handler(CommandHandler("addmatch", admin_add_match))

    # Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(daily_channel_update, "cron", hour=9, minute=0, args=[app])
    scheduler.add_job(daily_engagement_blast, "cron", hour=18, minute=0, args=[app])
    scheduler.start()

    logger.info("🚀 FWC26 Bot is live!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
