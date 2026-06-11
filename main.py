"""SM — NHC Signals Pipeline. One process: Telegram bot + scheduled jobs."""
import datetime, json, logging, zoneinfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

import store, sources, filter_llm, publisher, socials, reports_gen, capture, radar
from config import (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TZ, DIGEST_HOUR,
                    FETCH_EVERY_HOURS, MAX_ITEMS_PER_DIGEST)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")
AWAITING_EDIT: dict[int, int] = {}  # chat_id -> item_id
PENDING_REPORT: dict[int, dict] = {}  # chat_id -> drafted report


# ---------- jobs ----------
async def job_fetch_and_filter(context: ContextTypes.DEFAULT_TYPE):
    import asyncio
    new_ids = await asyncio.to_thread(sources.fetch_feeds)
    if not new_ids:
        log.info("Fetch: nothing new")
        return
    venues = await asyncio.to_thread(sources.load_index_venues)
    accepted = 0
    for item_id in new_ids:
        item = store.get(item_id)
        llm = await asyncio.to_thread(filter_llm.assess, item, venues)
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
    if action in ("seedins", "draftins"):
        await q.answer("This flow was replaced — just resend the ramble.", show_alert=True)
        return

    if action in ("saveins", "delins", "usedins"):
        ins = store.get_insight(item_id)
        if not ins:
            await q.edit_message_text("Insight not found.")
            return
        if action == "saveins":
            store.set_insight_status(item_id, "saved")
            for sid in COMPILED_PENDING.pop(item_id, []):
                store.set_insight_status(sid, "used")
            await q.edit_message_text(f"💾 Saved to bank: {ins['title']}\n\n{ins['post']}",
                parse_mode=None)
        elif action == "usedins":
            store.set_insight_status(item_id, "used")
            await q.edit_message_text(f"✔️ Marked used: {ins['title']}")
        else:
            store.set_insight_status(item_id, "discarded")
            await q.edit_message_text(f"🗑 Discarded: {ins['title']}")
        return

    item, llm = None, None
    if action not in ("repub", "redraft", "rediscard"):
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

    elif action in ("repub", "redraft", "rediscard"):
        r = PENDING_REPORT.get(q.message.chat_id)
        if not r:
            await q.edit_message_text("No pending report draft — run /report again.")
            return
        if action == "rediscard":
            PENDING_REPORT.pop(q.message.chat_id, None)
            await q.edit_message_text("❌ Report draft discarded.")
        elif action == "redraft":
            await q.edit_message_text("🔄 Redrafting with a different angle…")
            r2 = reports_gen.draft()
            if r2 and not r2.get("error"):
                PENDING_REPORT[q.message.chat_id] = r2
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Publish report", callback_data="repub:0"),
                    InlineKeyboardButton("🔄 Redraft", callback_data="redraft:0"),
                    InlineKeyboardButton("❌ Discard", callback_data="rediscard:0"),
                ]])
                await context.bot.send_message(q.message.chat_id,
                    f"<b>{r2['title']}</b>\n\n{r2.get('description','')}\n\n{r2.get('body','')[:600]}…",
                    parse_mode="HTML", reply_markup=kb)
            else:
                await context.bot.send_message(q.message.chat_id, "Redraft failed.")
        else:
            try:
                path = reports_gen.publish(r)
                PENDING_REPORT.pop(q.message.chat_id, None)
                await q.edit_message_text(f"✅ Report published: {r['title']}\n→ {path}\n"
                    "Tip: open /admin to add a header image and polish wording.")
            except Exception as ex:
                await q.edit_message_text(f"⚠️ Report publish failed: {ex}")
        return

    elif action == "edit":
        AWAITING_EDIT[q.message.chat_id] = item_id
        await q.message.reply_text(
            f"✏️ Editing “{llm['title']}”.\nReply with your instruction "
            "(e.g. 'shorten, lead with the expansion angle') — or type new text directly "
            "prefixed with 'TEXT:' to replace the body.")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id not in AWAITING_EDIT:
        if len(update.message.text or "") > 300:
            await update.message.reply_text("💡 Treating this as a capture — extracting…")
            await _run_capture(update.message.text, chat_id, context)
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


def _insight_kb(iid):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💾 Save to bank", callback_data=f"saveins:{iid}"),
        InlineKeyboardButton("🗑 Discard", callback_data=f"delins:{iid}"),
    ]])


COMPILED_PENDING: dict[int, list] = {}  # insight_id -> seed ids consumed


async def _run_capture(transcript: str, chat_id, context):
    r = capture.process(transcript)
    if not r or not r.get("mode"):
        await context.bot.send_message(chat_id, "Processing failed — check logs.")
        return
    if r["mode"] == "seed":
        note = (r.get("summary", "") + "\n\nRaw material:\n- "
                + "\n- ".join(r.get("material", [])))
        iid = store.add_insight("🌱 " + r.get("title", ""), note, transcript[:4000])
        store.set_insight_status(iid, "saved")
        await context.bot.send_message(chat_id,
            f"🌱 Saved as seed: <b>{r.get('title','')}</b>\n{r.get('summary','')}\n\n"
            f"Not enough for a post yet — /compile will pick it up once related "
            f"thoughts accumulate.", parse_mode="HTML")
        return
    iid = store.add_insight(r.get("title", ""), r.get("post", ""), transcript[:4000])
    pq = (r.get("pull_quote") or "").strip()
    if pq:
        try:
            await context.bot.send_photo(chat_id, photo=socials.render_note_card(pq))
        except Exception as ex:
            logging.getLogger("main").error("Note card failed: %s", ex)
    await context.bot.send_message(chat_id,
        f"<b>{r.get('title','')}</b>\n\n{r.get('post','')}",
        parse_mode="HTML", reply_markup=_insight_kb(iid))


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    v = msg.voice or msg.audio
    if not v:
        return
    await msg.reply_text("🎙 Transcribing…")
    tg_file = await context.bot.get_file(v.file_id)
    audio = bytes(await tg_file.download_as_bytearray())
    transcript = capture.transcribe(audio)
    if not transcript:
        await msg.reply_text("Transcription failed — is OPENAI_API_KEY set? (Whisper needs it.)")
        return
    await _run_capture(transcript, msg.chat_id, context)


async def cmd_capture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("Usage: /capture <your ramble> — or just send a voice note.")
        return
    await update.message.reply_text("💡 Extracting…")
    await _run_capture(text, update.message.chat_id, context)


async def cmd_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = store.saved_insights()
    if not items:
        await update.message.reply_text("Insight bank is empty. Send a voice note to fill it.")
        return
    await update.message.reply_text(f"🏦 {len(items)} saved insight(s):")
    for it in items:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✔️ Mark used", callback_data=f"usedins:{it['id']}"),
            InlineKeyboardButton("🗑 Remove", callback_data=f"delins:{it['id']}"),
        ]])
        await update.message.reply_text(
            f"<b>#{it['id']} {it['title']}</b>\n\n{it['post']}",
            parse_mode="HTML", reply_markup=kb)


TG_LIMIT = 3800  # headroom under Telegram's 4096-char hard limit


async def _send_radar(chat_id, context):
    items = radar.pending(20)
    if not items:
        await context.bot.send_message(chat_id, "🛰 Radar: nothing new this week.")
        return
    header = (f"🛰 <b>Radar</b> — {len(items)} item(s) worth knowing "
              f"(private, never published):\n\n")
    chunks, current = [], header
    for it in items:
        why = (it.get("why") or "")[:500]
        entry = f"• <b>{it['headline']}</b>\n  <i>{why}</i>\n  {it['url']}\n\n"
        if len(current) + len(entry) > TG_LIMIT:
            chunks.append(current)
            current = ""
        current += entry
    if current.strip():
        chunks.append(current)
    for chunk in chunks:
        await context.bot.send_message(chat_id, chunk.rstrip(),
            parse_mode="HTML", disable_web_page_preview=True)
    radar.mark_sent([it["id"] for it in items])


async def job_radar(context: ContextTypes.DEFAULT_TYPE):
    import asyncio
    await asyncio.to_thread(radar.fetch_and_filter)
    await _send_radar(TELEGRAM_CHAT_ID, context)


async def cmd_radar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import asyncio
    await update.message.reply_text(
        "🛰 Scanning radar feeds… first run can take several minutes (backlog); "
        "after that it is quick. The digest arrives when done.")
    await asyncio.to_thread(radar.fetch_and_filter)
    await _send_radar(update.message.chat_id, context)


async def cmd_compile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seeds = [s for s in store.saved_insights(50) if s["title"].startswith("🌱")]
    if len(seeds) < 2:
        await update.message.reply_text(
            f"Only {len(seeds)} seed(s) in the bank — /compile needs at least 2. "
            "Send more rambles first.")
        return
    await update.message.reply_text(f"🧩 Compiling {len(seeds)} seeds…")
    posts = capture.compile_seeds(seeds)
    if not posts:
        await update.message.reply_text(
            "No seed cluster has enough material for a solid post yet. They stay in the bank.")
        return
    for p in posts:
        iid = store.add_insight(p.get("title", ""), p.get("post", ""), "compiled from seeds")
        COMPILED_PENDING[iid] = p.get("seed_ids", [])
        pq = (p.get("pull_quote") or "").strip()
        if pq:
            try:
                await context.bot.send_photo(update.message.chat_id,
                    photo=socials.render_note_card(pq))
            except Exception:
                pass
        await update.message.reply_text(
            f"<b>{p.get('title','')}</b>\n<i>compiled from {len(p.get('seed_ids',[]))} seed(s)</i>\n\n"
            f"{p.get('post','')}",
            parse_mode="HTML", reply_markup=_insight_kb(iid))


HELP_TEXT = """<b>NHC Pipeline — commands</b>

<b>News flow</b>
/fetch — pull the trade feeds now (also runs automatically every 6h)
/digest — show pending signal candidates (also arrives daily at 08:00)
/rejected — last 15 rejected items with reasons, ♻️ to override
/stats — counts by status

<b>Publishing</b>
On each signal card: ✅ Publish (commits to the site) · ✏️ Edit (reply with an
instruction, or TEXT: to replace the body) · ❌ Skip
After publishing: 📣 Social pack — card image + Instagram and LinkedIn captions

<b>Reports</b>
/report — synthesize signals since the last report into a Market Report draft
/report 180 — same, with a 180-day window

<b>Radar (private — never published)</b>
/radar — scan science/regulatory feeds now; weekly digest arrives Sundays 09:00
Covers: longevity trials, therapy evidence shifts, psychedelic medicine access,
diagnostics, regulatory moves

<b>Thinking capture</b>
Send a voice note, paste a long text, or /capture &lt;text&gt; — becomes either one
LinkedIn-ready post (reports voice) or a 🌱 seed if too thin
/ideas — your saved insight bank (posts and seeds)
/compile — cluster the saved seeds into posts once enough material has accumulated

/help — this message"""


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    days = None
    if context.args:
        try:
            days = int(context.args[0])
        except ValueError:
            pass
    await update.message.reply_text("🗞 Synthesizing signals into a report draft…")
    r = reports_gen.draft(days)
    if not r:
        await update.message.reply_text("Draft failed — check logs.")
        return
    if r.get("error"):
        await update.message.reply_text(r["error"])
        return
    PENDING_REPORT[chat_id] = r
    md = reports_gen.report_markdown(r)
    import io as _io
    await context.bot.send_document(chat_id, document=_io.BytesIO(md.encode()),
        filename="report-draft.md")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Publish report", callback_data="repub:0"),
        InlineKeyboardButton("🔄 Redraft", callback_data="redraft:0"),
        InlineKeyboardButton("❌ Discard", callback_data="rediscard:0"),
    ]])
    await update.message.reply_text(
        f"<b>{r['title']}</b>\n<i>from {r['n_signals']} signals since {r['since']}</i>\n\n"
        f"{r.get('description','')}\n\n"
        f"{r.get('body','')[:600]}…",
        parse_mode="HTML", reply_markup=kb)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c = store.counts()
    await update.message.reply_text(
        "📊 " + " · ".join(f"{k}: {v}" for k, v in sorted(c.items())) if c else "Empty.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled exception:", exc_info=context.error)
    chat_id = None
    if isinstance(update, Update) and update.effective_chat:
        chat_id = update.effective_chat.id
    else:
        chat_id = TELEGRAM_CHAT_ID
    try:
        await context.bot.send_message(chat_id, f"⚠️ Error: {context.error}")
    except Exception:
        pass


def main():
    store.init()
    store.init_insights()
    radar.init()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_error_handler(on_error)
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("fetch", cmd_fetch))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("rejected", cmd_rejected))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("capture", cmd_capture))
    app.add_handler(CommandHandler("compile", cmd_compile))
    app.add_handler(CommandHandler("radar", cmd_radar))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ideas", cmd_ideas))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    tz = zoneinfo.ZoneInfo(TZ)
    app.job_queue.run_repeating(job_fetch_and_filter, interval=FETCH_EVERY_HOURS * 3600, first=20)
    app.job_queue.run_daily(job_digest, time=datetime.time(hour=DIGEST_HOUR, tzinfo=tz))
    from config import RADAR_DIGEST_DAY, RADAR_DIGEST_HOUR
    app.job_queue.run_daily(job_radar, time=datetime.time(hour=RADAR_DIGEST_HOUR, tzinfo=tz),
                            days=(RADAR_DIGEST_DAY,))
    log.info("Bot up. Fetch every %dh, digest daily at %02d:00 %s", FETCH_EVERY_HOURS, DIGEST_HOUR, TZ)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
# cache-bust 1781137158
