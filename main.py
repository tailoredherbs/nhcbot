"""SM — NHC Signals Pipeline. One process: Telegram bot + scheduled jobs."""
import datetime, json, logging, zoneinfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

import store, sources, filter_llm, publisher, socials
from config import (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TZ, DIGEST_HOUR,
                    FETCH_EVERY_HOURS, MAX_ITEMS_PER_DIGEST)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")
AWAITING_EDIT: dict[int, int] = {}  # chat_id -> item_id


# ---------- jobs ----------
async def job_fetch_and_filter(context: ContextTypes.DEFAULT_TYPE):
    new_ids = sources.fetch_feeds()
    if not new_ids:
        log.info("Fetch: nothing new")
        return
    venues = sources.load_index_venues()
    accepted = 0
    for item_id in new_ids:
        item = store.get(item_id)
        llm = filter_llm.assess(item, venues)
        if not llm:
            store.set_status(item_id, "rejected")
            continue
        if llm.get("include"):
            store.set_llm(item_id, llm, "pending")
            accepted += 1
        else:
            store.set_llm(item_id, llm, "rejected")
    log.info("Fetch: %d new, %d pending review", len(new_ids), accepted)


def _card_text(item, llm):
    star = "⭐ ON INDEX — " if llm.get("on_index") else ""
    return (f"{star}<b>{llm['title']}</b>\n"
            f"<i>{llm.get('category','')} · {llm.get('location','')} · Ring {llm.get('ring','?')}</i>\n\n"
            f"{llm.get('description','')}\n\n"
            f"Venue: {llm.get('venue','—')}\n"
            f"Tags: {llm.get('tag','—')}\n"
            f"Source: {item['source']}\n{item['url']}")


def _card_kb(item_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Publish", callback_data=f"pub:{item_id}"),
        InlineKeyboardButton("✏️ Edit", callback_data=f"edit:{item_id}"),
        InlineKeyboardButton("❌ Skip", callback_data=f"skip:{item_id}"),
    ]])


async def job_digest(context: ContextTypes.DEFAULT_TYPE):
    pending = store.by_status("pending", MAX_ITEMS_PER_DIGEST)
    if not pending:
        await context.bot.send_message(TELEGRAM_CHAT_ID, "📭 No new signals today.")
        return
    await context.bot.send_message(TELEGRAM_CHAT_ID,
        f"📡 <b>NHC Daily Digest</b> — {len(pending)} candidate signal(s)", parse_mode="HTML")
    for item in pending:
        llm = json.loads(item["llm"])
        await context.bot.send_message(TELEGRAM_CHAT_ID, _card_text(item, llm),
            parse_mode="HTML", reply_markup=_card_kb(item["id"]),
            disable_web_page_preview=True)


# ---------- handlers ----------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action, item_id = q.data.split(":")
    item_id = int(item_id)
    item = store.get(item_id)
    if not item:
        await q.edit_message_text("Item not found.")
        return
    llm = json.loads(item["llm"])

    if action == "skip":
        store.set_status(item_id, "skipped")
        await q.edit_message_text(f"❌ Skipped: {llm['title']}")

    elif action == "pub":
        try:
            path = publisher.publish(llm, item["url"])
            store.set_status(item_id, "published")
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📣 Social pack", callback_data=f"social:{item_id}")]])
            await q.edit_message_text(f"✅ Published: {llm['title']}\n→ {path}\nNetlify is deploying.", reply_markup=kb)
        except Exception as ex:
            await q.edit_message_text(f"⚠️ Publish failed: {ex}\nItem kept as pending.")

    elif action == "social":
        await context.bot.send_message(q.message.chat_id, "📣 Building social pack…")
        try:
            ctx = socials.signal_context(llm)
            png = socials.render_card(llm, number=ctx["number"], coords=ctx["coords"])
            caps = socials.captions(llm) or {}
            ig = caps.get("instagram", "")
            li = caps.get("linkedin", "")
            await context.bot.send_photo(q.message.chat_id, photo=png,
                caption=("📸 Instagram\n\n" + ig)[:1024])
            if li:
                await context.bot.send_message(q.message.chat_id, "💼 LinkedIn\n\n" + li)
        except Exception as ex:
            await context.bot.send_message(q.message.chat_id, f"Social pack failed: {ex}")

    elif action == "rescue":
        await q.edit_message_text(f"♻️ Rescuing: {item['title'][:80]}… drafting signal.")
        new_llm = filter_llm.revise(item, "The editor has overridden the rejection. Set include=true and produce the complete signal draft with all fields, based on the source summary.")
        if new_llm and new_llm.get("title"):
            store.set_llm(item_id, new_llm, "pending")
            await context.bot.send_message(q.message.chat_id, _card_text(store.get(item_id), new_llm),
                parse_mode="HTML", reply_markup=_card_kb(item_id), disable_web_page_preview=True)
        else:
            await context.bot.send_message(q.message.chat_id, "Rescue failed — try again or check logs.")

    elif action == "edit":
        AWAITING_EDIT[q.message.chat_id] = item_id
        await q.message.reply_text(
            f"✏️ Editing “{llm['title']}”.\nReply with your instruction "
            "(e.g. 'shorten, lead with the expansion angle') — or type new text directly "
            "prefixed with 'TEXT:' to replace the body.")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id not in AWAITING_EDIT:
        return
    item_id = AWAITING_EDIT.pop(chat_id)
    item = store.get(item_id)
    llm = json.loads(item["llm"])
    instruction = update.message.text.strip()

    if instruction.upper().startswith("TEXT:"):
        llm["body"] = instruction[5:].strip()
        new_llm = llm
    else:
        await update.message.reply_text("Revising…")
        new_llm = filter_llm.revise(item, instruction)
        if not new_llm:
            await update.message.reply_text("Revision failed — item unchanged.")
            return
    store.set_llm(item_id, new_llm, "pending")
    await update.message.reply_text(_card_text(store.get(item_id), new_llm),
        parse_mode="HTML", reply_markup=_card_kb(item_id), disable_web_page_preview=True)


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await job_digest(context)

async def cmd_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fetching feeds…")
    await job_fetch_and_filter(context)
    c = store.counts()
    await update.message.reply_text(f"Done. Pending: {c.get('pending', 0)}")

async def cmd_rejected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = store.rejected_recent(15)
    if not items:
        await update.message.reply_text("No rejected items yet.")
        return
    await update.message.reply_text(f"🗑 Last {len(items)} rejected — tap ♻️ to override:")
    for item in items:
        try:
            llm = json.loads(item["llm"]) if item["llm"] else {}
        except Exception:
            llm = {}
        reason = llm.get("reason", "no reason stored")
        ring = llm.get("ring", "?")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("♻️ Rescue", callback_data=f"rescue:{item['id']}")]])
        await update.message.reply_text(
            f"<b>{item['title'][:120]}</b>\n<i>{item['source']} · Ring {ring}</i>\n{reason}\n{item['url']}",
            parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c = store.counts()
    await update.message.reply_text(
        "📊 " + " · ".join(f"{k}: {v}" for k, v in sorted(c.items())) if c else "Empty.")


def main():
    store.init()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("fetch", cmd_fetch))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("rejected", cmd_rejected))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    tz = zoneinfo.ZoneInfo(TZ)
    app.job_queue.run_repeating(job_fetch_and_filter, interval=FETCH_EVERY_HOURS * 3600, first=20)
    app.job_queue.run_daily(job_digest, time=datetime.time(hour=DIGEST_HOUR, tzinfo=tz))
    log.info("Bot up. Fetch every %dh, digest daily at %02d:00 %s", FETCH_EVERY_HOURS, DIGEST_HOUR, TZ)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
