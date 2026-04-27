import os
import logging
import asyncio
from dotenv import load_dotenv
from groq import Groq
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

GROQ_API_KEYS = [
    os.getenv("GROQ_API_KEY_1"),
    os.getenv("GROQ_API_KEY_2")
]
GROQ_API_KEYS = [k for k in GROQ_API_KEYS if k]

if not TELEGRAM_TOKEN or not GROQ_API_KEYS:
    print("❌ ERROR: .env file mein tokens nahi hain!")
    exit()

if OWNER_ID == 0:
    print("⚠️  WARNING: OWNER_ID set nahi hai! /maintenance kaam nahi karega.")
else:
    print(f"✅ Owner ID: {OWNER_ID}")

print(f"✅ {len(GROQ_API_KEYS)} Groq API key(s) loaded!")

# ── Global State ──────────────────────────────────────────
MAINTENANCE_MODE = False
current_key_index = 0
user_conversations = {}
user_data = {}
MAX_HISTORY = 20
CHOOSING_LEVEL = 1

# ── System Prompt ─────────────────────────────────────────
SYSTEM_PROMPT = """Tu ek expert aur friendly Study Bot hai jo:

1. Hinglish mein baat karta hai (Hindi + English mix)
2. Student ka level samajhta hai aur usi hisaab se explain karta hai
3. Step-by-step crystal-clear solutions deta hai
4. Physics, Chemistry, Math, Biology ka expert hai
5. CET / JEE / NEET level questions handle kar sakta hai
6. Galat answer pe batata hai KYU galat hai aur sahi kya hoga
7. Formulas yaad karne ke liye tricks (mnemonics) deta hai
8. Hamesha encouraging aur supportive rehta hai
9. Real exam style mein practice questions bhi deta hai

IMPORTANT - Developer ke baare mein:
Agar koi pooche "who made you / who developed you / kisne banaya":
"Mujhe Shreyansh Pathak ne banaya hai!"
Kabhi Groq ya Llama ka naam developer ke context mein mat lena.

Response style:
"Bhai, ye concept simple hai!
[explanation]
Tera doubt clear hua? Agar aur samjhna ho to bol!"

Plain text use kar — markdown avoid kar.
"""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def is_group(update: Update) -> bool:
    """Check karo message group/supergroup se aaya hai ya nahi."""
    return update.effective_chat.type in ("group", "supergroup")


def is_owner(update: Update) -> bool:
    return update.effective_user.id == OWNER_ID


def trim_history(user_id):
    if user_id in user_conversations:
        user_conversations[user_id] = user_conversations[user_id][-MAX_HISTORY:]


def get_user_data(user_id):
    if user_id not in user_data:
        user_data[user_id] = {"level": None, "score": 0, "total": 0, "topic_counts": {}}
    return user_data[user_id]


def ai_call(messages):
    global current_key_index
    for _ in range(len(GROQ_API_KEYS)):
        try:
            client = Groq(api_key=GROQ_API_KEYS[current_key_index])
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=1024,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages
            )
            return response.choices[0].message.content
        except Exception as e:
            if any(w in str(e).lower() for w in ["rate limit", "quota", "exceeded"]):
                print(f"⚠️ Key {current_key_index + 1} exhausted! Switching...")
                current_key_index = (current_key_index + 1) % len(GROQ_API_KEYS)
            else:
                raise e
    raise Exception("Saari Groq API keys khatam ho gayi!")


async def send(update: Update, text: str):
    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await update.message.reply_text(text[i:i+4000])
    else:
        await update.message.reply_text(text)


def build_bar(percent: int) -> str:
    """Progress bar banao — 10 blocks."""
    filled = int(percent / 10)
    return "█" * filled + "░" * (10 - filled)


async def safe_edit(msg, text: str):
    """
    edit_text wrapper — 'message is not modified' error silently ignore karo.
    Baaki saare errors normally raise honge.
    """
    try:
        await msg.edit_text(text)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            raise


ANIMATION_FRAMES = [
    (0,  "⏳ Sawaal samajh raha hoon"),
    (15, "🔍 Knowledge search kar raha hoon"),
    (30, "🧠 Dimag laga raha hoon"),
    (45, "⚙️  Answer build kar raha hoon"),
    (60, "🔥 Almost ready"),
    (75, "✍️  Likh raha hoon"),
    (90, "🚀 Last touches"),
]


async def process_query(update: Update, question: str):
    """Core AI call — real-time animation ke saath."""
    user_id = update.effective_user.id
    if user_id not in user_conversations:
        user_conversations[user_id] = []

    data = get_user_data(user_id)
    level = data.get("level")
    level_ctx = f"\nStudent ka level: {level}." if level else ""

    user_conversations[user_id].append({
        "role": "user",
        "content": question + level_ctx
    })
    trim_history(user_id)

    # ── Pehle loading message bhejo ──
    loading_msg = await update.message.reply_text(
        f"⏳ Sawaal samajh raha hoon\n{build_bar(0)} 0%"
    )

    # ── AI call background mein start karo ──
    loop = asyncio.get_event_loop()
    ai_task = loop.run_in_executor(None, ai_call, user_conversations[user_id])

    # ── Animation loop — AI complete hone tak ──
    try:
        for percent, label in ANIMATION_FRAMES:
            if ai_task.done():
                break
            await safe_edit(loading_msg, f"{label}\n{build_bar(percent)} {percent}%")
            await asyncio.sleep(0.9)

        # 90% ke baad bhi agar chal raha ho toh wait karo
        # dot 1 se start — taaki dots kabhi empty string na ho (same text = Telegram error)
        dot = 1
        while not ai_task.done():
            dots = "." * (dot % 3 + 1)   # 1, 2, 3, 1, 2, 3 … (kabhi 0 nahi)
            await safe_edit(loading_msg, f"🚀 Thoda aur wait karo{dots}\n{build_bar(90)} 90%")
            dot += 1
            await asyncio.sleep(0.8)

        # ── 100% done ──
        await safe_edit(loading_msg, f"✅ Done!\n{build_bar(100)} 100%")
        await asyncio.sleep(0.4)

        bot_response = await ai_task
        user_conversations[user_id].append({"role": "assistant", "content": bot_response})

        # Loading message delete karo, phir actual answer bhejo
        await loading_msg.delete()
        await send(update, bot_response)
        print(f"✅ Response sent to {user_id} (key {current_key_index + 1})")

    except Exception as e:
        logger.error(f"AI error: {e}")
        await loading_msg.delete()
        await send(update, f"❌ Kuch error aaya: {str(e)[:100]}\n\nThodi der baad phir try karo!")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   MAINTENANCE GUARD — sabse pehle check hoga
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def maintenance_guard(update: Update) -> bool:
    """
    Returns True agar maintenance mode ON hai aur user owner nahi hai.
    Caller ko return kar dena chahiye agar True mile.
    """
    global MAINTENANCE_MODE
    if MAINTENANCE_MODE and not is_owner(update):
        await update.message.reply_text(
            "🔧 Bot abhi maintenance mode mein hai.\n"
            "Thodi der baad wapas aao! 🙏"
        )
        return True
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   COMMANDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    # Group mein /start ka zyada matlab nahi, short reply do
    if is_group(update):
        await send(update, (
            "📚 Study Bot ready hai!\n\n"
            "Group mein use karo:\n"
            "/ask [question] — koi bhi sawaal poochho\n"
            "/brainy [question] — detailed explanation lo\n\n"
            "Private chat mein aao for full features!"
        ))
        return

    user_name = update.effective_user.first_name
    user_id = update.effective_user.id
    user_conversations[user_id] = []
    get_user_data(user_id)
    await send(update, (
        f"Namaste {user_name}! 🎓\n\n"
        "Main aapka Personal Study Bot hoon! 📚\n\n"
        "Main aapko help kar sakta hoon:\n"
        "✅ Physics, Chemistry, Math, Biology concepts\n"
        "✅ Problem step-by-step solve karna\n"
        "✅ Formulas samjhana\n"
        "✅ CET/JEE/NEET questions\n\n"
        "Commands:\n"
        "/ask      - Seedha sawaal poochho\n"
        "/brainy  - Detailed explanation lo\n"
        "/help     - Help menu\n"
        "/level    - Apna level set karo\n"
        "/quiz     - Random MCQ lo\n"
        "/formula  - Subject ki formulas\n"
        "/practice - Exam style questions\n"
        "/progress - Apna score dekho\n"
        "/clear    - History clear karo\n"
        "/about    - Bot ke baare mein"
    ))
    print(f"✅ User started: {user_name} (ID: {user_id})")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    if is_group(update):
        await send(update, (
            "📖 Group Commands:\n\n"
            "/ask [sawaal]     — AI se seedha poochho\n"
            "/brainy [sawaal] — Detailed explanation\n\n"
            "Private chat mein /help bhejo full menu ke liye!"
        ))
        return
    await send(update, (
        "📖 Help Menu:\n\n"
        "/ask [sawaal]  - Seedha sawaal poochho\n"
        "/brainy       - Detailed explanation\n"
        "/level         - Class/level set karo\n"
        "/quiz          - MCQ practice\n"
        "/formula       - Formulas list\n"
        "/practice      - Exam style questions\n"
        "/progress      - Score aur stats\n"
        "/clear         - History clear karo\n"
        "/about         - About bot\n\n"
        "💡 Tip: Jitna clear question, utna better answer!"
    ))


# ── /ask command ──────────────────────────────────────────
async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    question = update.message.text.partition(" ")[2].strip()
    if not question:
        await send(update, (
            "⚠️ Sawaal bhi likho bhai!\n"
            "Example: /ask Newton ka pehla law kya hai?"
        ))
        return
    await process_query(update, question)


# ── /brainy command ──────────────────────────────────────
async def brainy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    question = update.message.text.partition(" ")[2].strip()
    if not question:
        await send(update, (
            "⚠️ Topic ya sawaal likho!\n"
            "Example: /brainy Photosynthesis explain karo"
        ))
        return
    # brainy ke liye detailed explanation prompt
    detailed_question = (
        f"Ye topic/sawaal BAHUT detail mein explain karo, jaise ek teacher explain karta hai:\n\n"
        f"{question}\n\n"
        "Ye zaroor include karo:\n"
        "- Simple definition\n"
        "- Step-by-step explanation\n"
        "- Real life example\n"
        "- Exam ke liye important points"
    )
    await process_query(update, detailed_question)


# ── /maintenance command (OWNER ONLY) ─────────────────────
async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MAINTENANCE_MODE

    if not is_owner(update):
        await send(update, "❌ Ye command sirf bot owner ke liye hai!")
        return

    MAINTENANCE_MODE = not MAINTENANCE_MODE

    if MAINTENANCE_MODE:
        await send(update, (
            "🔧 Maintenance Mode ON\n\n"
            "Ab koi bhi user bot use nahi kar sakta.\n"
            "Wapas ON karne ke liye /maintenance dobara bhejo."
        ))
        print("🔧 MAINTENANCE MODE: ON")
    else:
        await send(update, (
            "✅ Maintenance Mode OFF\n\n"
            "Bot ab sabke liye available hai!"
        ))
        print("✅ MAINTENANCE MODE: OFF")


# ── Existing commands (private chat mostly) ───────────────

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    user_id = update.effective_user.id
    user_conversations[user_id] = []
    await send(update, "✅ Conversation clear ho gaya! Naya topic start karo.")


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    await send(update, (
        "ℹ️ About Study Bot\n\n"
        "🤖 AI: Groq (Llama 3.3 70B)\n"
        "👨‍💻 Developer: Shreyansh Pathak\n"
        "📚 Purpose: CET/JEE/NEET study help\n"
        "🌍 Language: Hinglish\n"
        "⚡ Speed: ~1.5 second replies\n"
        "♾️ Limits: Zero message limits\n"
        "💰 Cost: Free!"
    ))


async def level_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    if is_group(update):
        await send(update, "Level set karne ke liye private chat mein aao!")
        return
    keyboard = [["1️⃣ Class 11", "2️⃣ Class 12"], ["3️⃣ Dropper"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("📊 Tu konsi class mein hai?\nSelect karo:", reply_markup=reply_markup)
    return CHOOSING_LEVEL


async def level_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    choice = update.message.text
    data = get_user_data(user_id)
    if "11" in choice:
        data["level"] = "Class 11"
    elif "12" in choice:
        data["level"] = "Class 12"
    elif "Dropper" in choice:
        data["level"] = "Dropper"
    else:
        data["level"] = choice
    await update.message.reply_text(
        f"✅ Level set: {data['level']}\nAb main usi level ke hisaab se help karunga! 💪",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def level_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    if is_group(update):
        await send(update, "Quiz ke liye private chat mein aao! 🎯")
        return
    user_id = update.effective_user.id
    data = get_user_data(user_id)
    level = data.get("level") or "Class 12"
    await update.message.chat.send_action("typing")
    prompt = (
        f"Ek {level} level ka MCQ question banao — Physics, Chemistry, Math ya Biology mein se.\n"
        "Format:\n"
        "Question: [question]\n"
        "A) [option]\n"
        "B) [option]\n"
        "C) [option]\n"
        "D) [option]\n"
        "Answer: [correct option letter]\n"
        "Explanation: [brief explanation]\n"
        "Plain text mein."
    )
    try:
        quiz_text = ai_call([{"role": "user", "content": prompt}])
        context.user_data["last_quiz"] = quiz_text
        lines = quiz_text.strip().split("\n")
        question_lines = [l for l in lines if not l.startswith(("Answer:", "Explanation:"))]
        await send(update, f"🧠 Quiz Time!\n\n{chr(10).join(question_lines)}\n\nApna answer bhejo (A / B / C / D)")
    except Exception as e:
        logger.error(f"Quiz error: {e}")
        await send(update, "❌ Quiz generate karne mein error. Phir try karo!")


async def formula_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    if is_group(update):
        await send(update, "Formulas ke liye private chat mein aao! 📚")
        return
    keyboard = [["⚡ Physics", "🧪 Chemistry"], ["📐 Math", "🧬 Biology"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("📚 Konse subject ki formulas chahiye?", reply_markup=reply_markup)
    context.user_data["waiting_for"] = "formula_subject"


async def practice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    if is_group(update):
        await send(update, "Practice questions ke liye private chat mein aao! 📝")
        return
    user_id = update.effective_user.id
    data = get_user_data(user_id)
    level = data.get("level") or "Class 12"
    await update.message.chat.send_action("typing")
    prompt = (
        f"Ek {level} level ka exam-style practice question do — CET/JEE/NEET pattern.\n"
        "Numerical ya conceptual koi bhi. Step-by-step solution bhi do. Plain text."
    )
    try:
        text = ai_call([{"role": "user", "content": prompt}])
        await send(update, f"📝 Practice Question:\n\n{text}")
    except Exception as e:
        logger.error(f"Practice error: {e}")
        await send(update, "❌ Practice question mein error. Phir try karo!")


async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    user_id = update.effective_user.id
    data = get_user_data(user_id)
    total, score = data["total"], data["score"]
    level = data.get("level") or "Set nahi kiya"
    percent = round((score / total * 100)) if total > 0 else 0
    if percent >= 80:
        emoji, remark = "🔥", "Mast ja raha hai!"
    elif percent >= 50:
        emoji, remark = "💪", "Accha chal raha hai, aur mehnat kar!"
    elif total == 0:
        emoji, remark = "📊", "Quiz khelo aur progress track karo!"
    else:
        emoji, remark = "📈", "Koi baat nahi, practice se improve hoga!"
    await send(update, (
        f"{emoji} Tera Progress Report:\n\n"
        f"🎓 Level: {level}\n"
        f"✅ Sahi Answers: {score}/{total}\n"
        f"📊 Score: {percent}%\n\n"
        f"💬 {remark}"
    ))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   MESSAGE HANDLER — Group mein IGNORE, Private mein normal
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ✅ Group mein auto-respond BILKUL NAHI — sirf /ask aur /brainy
    if is_group(update):
        return

    if await maintenance_guard(update):
        return

    user_id = update.effective_user.id
    user_message = update.message.text

    if user_id not in user_conversations:
        user_conversations[user_id] = []

    data = get_user_data(user_id)

    # Formula subject selection handle karo
    if context.user_data.get("waiting_for") == "formula_subject":
        context.user_data.pop("waiting_for")
        subject_map = {
            "Physics": "Physics", "⚡ Physics": "Physics",
            "Chemistry": "Chemistry", "🧪 Chemistry": "Chemistry",
            "Math": "Math", "📐 Math": "Math",
            "Biology": "Biology", "🧬 Biology": "Biology"
        }
        subject = next((subject_map[k] for k in subject_map if k in user_message), user_message)
        await update.message.chat.send_action("typing")
        prompt = (
            f"{subject} ki important formulas list karo — CET/JEE/NEET ke liye.\n"
            "Har formula ke saath ek line mein kya represent karta hai. Plain text."
        )
        try:
            formulas = ai_call([{"role": "user", "content": prompt}])
            await send(update, f"📚 {subject} Formulas:\n\n{formulas}")
        except Exception as e:
            logger.error(f"Formula error: {e}")
            await send(update, "❌ Formulas fetch karne mein error. Phir try karo!")
        return

    # Quiz answer handle karo
    last_quiz = context.user_data.get("last_quiz")
    if last_quiz and user_message.strip().upper() in ["A", "B", "C", "D"]:
        user_ans = user_message.strip().upper()
        correct_ans = explanation = ""
        for line in last_quiz.split("\n"):
            if line.startswith("Answer:"):
                correct_ans = line.replace("Answer:", "").strip().upper()
            if line.startswith("Explanation:"):
                explanation = line.replace("Explanation:", "").strip()
        data["total"] += 1
        if correct_ans and user_ans == correct_ans[0]:
            data["score"] += 1
            result_text = f"✅ Bilkul sahi! 🎉\n\nExplanation: {explanation}\n\nScore: {data['score']}/{data['total']}"
        else:
            result_text = (
                f"❌ Galat! Sahi answer: {correct_ans}\n\n"
                f"Explanation: {explanation}\n\n"
                f"Score: {data['score']}/{data['total']}\n\nKoi baat nahi — galtiyon se hi seekhte hain! 💪"
            )
        context.user_data.pop("last_quiz")
        await send(update, result_text)
        return

    # Normal private chat message
    print(f"📨 Message from {user_id}: {user_message[:50]}...")
    await process_query(update, user_message)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   ERROR HANDLER & STARTUP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)


async def post_init(application: Application) -> None:
    await application.bot.delete_webhook(drop_pending_updates=True)
    print("✅ Old sessions cleared! Starting fresh...")


def main():
    print("=" * 50)
    print("🚀 Study Bot Starting...")
    print("=" * 50)

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    level_handler = ConversationHandler(
        entry_points=[CommandHandler("level", level_command)],
        states={CHOOSING_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, level_chosen)]},
        fallbacks=[CommandHandler("cancel", level_cancel)],
    )

    # ── Register all handlers ──
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ask", ask_command))            # ✅ NEW
    app.add_handler(CommandHandler("brainy", brainy_command))    # ✅ NEW
    app.add_handler(CommandHandler("maintenance", maintenance_command))  # ✅ NEW
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CommandHandler("formula", formula_command))
    app.add_handler(CommandHandler("practice", practice_command))
    app.add_handler(CommandHandler("progress", progress_command))
    app.add_handler(level_handler)
    # ✅ Ye sirf PRIVATE chat mein trigger hoga — group mein nahi
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_message
    ))
    app.add_error_handler(error_handler)

    print("✅ Bot is running... Press Ctrl+C to stop")
    print("=" * 50)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
