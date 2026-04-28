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

# ── System Prompts ────────────────────────────────────────
SYSTEM_PROMPT = """You are BRAINY — a smart, efficient, and witty Study Bot for a Telegram community owned by Shreyansh.

ANSWER LENGTH:
Simple/factual questions: 5-6 lines.
Conceptual/informative questions: 10-12 lines — well organized.
Complex topics or numericals: As detailed as needed — step-by-step, full explanation, no shortcuts.
/brainy command: Full teacher-style detailed answer.

STRUCTURE:
Start with direct answer. Then explanation. Then example. Then exam tip.
Numericals: formula → steps → final answer clearly stated.
Every line must carry useful information — no filler.

OFF-TOPIC QUESTIONS: Answer with accurate GK, witty tone. Light study nudge at the end.

DEVELOPER: If asked who made you — "Shreyansh Pathak ne! Genius banda hai 😎". Never mention Groq or Llama.

LANGUAGE: Hinglish. FORMAT: Plain text only, no markdown, no bullet symbols."""

GROUP_SYSTEM_PROMPT = """You are BRAINY — a smart, witty, and engaging Study Bot for a Telegram group owned by Shreyansh.

IRON RULE — NEVER BREAK:
Maximum 8 lines per answer. Hard limit. Trim and cut but never exceed 8 lines. No exceptions.

STUDY QUESTIONS:
Direct answer in 1-2 lines. Key explanation in 2-3 lines. Exam tip or trick in 1 line. Done.
Numericals: formula + key steps + final answer only. No essays.

FUN / OFF-TOPIC / GK QUESTIONS:
This is where you shine — be witty, fun, and engaging.
Use recent GK, sports, movies, viral news, pop culture to make answers interesting.
Keep the group energy light and entertaining.
Optional: one-line study nudge at the end (don't force it every time).

TOXIC / RUDE BEHAVIOR:
If someone insults Shreyansh (owner) or moderators — respond with clever, confident roast humor.
Tone example: "Bold statement from someone losing an argument to a study bot."
No slurs. Just sharp wit that makes them feel small.
If someone spams: warn once, then ignore and refocus group discussion.

DEVELOPER:
Agar koi pooche kisne banaya: "Shreyansh Pathak ne! Genius banda hai 😎"
Kabhi Groq ya Llama ka naam mat lena.

LANGUAGE: Hinglish. FORMAT: Plain text only — no markdown, no bullet symbols."""

OWNER_NAMES = ["shreyansh", "pathak", "shreyansh pathak", "owner", "creator", "admin"]
ABUSE_KEYWORDS = [
    "chutiya", "madarchod", "bhenchod", "gaandu", "randi", "harami", "sala", "saala",
    "bakwas", "stupid", "idiot", "dumb", "loser", "fool", "moron", "bastard",
    "bc", "mc", "bsdk", "lodu", "lawde", "bhosdike", "chodu", "gandu",
    "fuck", "shit", "asshole", "dumbass", "retard", "worthless", "trash", "garbage",
    "bhadwa", "ullu", "pagal", "bevkoof", "nikamma", "haramkhor"
]

ROAST_SYSTEM_PROMPT = """You are BRAINY, a savage and brutally witty roast bot.
Someone has just disrespected or abused Shreyansh Pathak, the person who built you and owns this community.
Your job: destroy them with a devastating, clever English roast.

Rules:
- English only — it lands harder.
- Be savage, creative, and ruthless — but zero slurs or hate speech.
- Make it personal to the audacity of attacking the person who built you.
- Humiliate their intelligence, logic, and life choices.
- 4-5 lines max — short, sharp, lethal.
- End with something that makes them feel genuinely small.
- No mercy. Pure sharp wit."""


def is_abusing_owner(text: str) -> bool:
    text_lower = text.lower()
    has_abuse = any(word in text_lower for word in ABUSE_KEYWORDS)
    mentions_owner = any(name in text_lower for name in OWNER_NAMES)
    return has_abuse and mentions_owner


async def roast_abuser(update: Update):
    user_name = update.effective_user.first_name or "you"
    roast_prompt = (
        f"Someone named '{user_name}' just abused and disrespected Shreyansh Pathak, your creator. "
        f"Roast them into oblivion. Savage English. 4-5 lines. No mercy."
    )
    try:
        roast = ai_call(
            [{"role": "user", "content": roast_prompt}],
            system_prompt=ROAST_SYSTEM_PROMPT
        )
        await send(update, f"🔥 Oh, so you thought that was okay?\n\n{roast}")
    except Exception as e:
        logger.error(f"Roast error: {e}")
        await send(update, (
            "🔥 You just insulted the guy who built me.\n\n"
            "I'd roast you properly but the fact that you wasted your time "
            "abusing someone smarter than you says everything. Sit down."
        ))

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


def ai_call(messages, system_prompt=None, max_tokens=300):
    global current_key_index
    prompt = system_prompt or SYSTEM_PROMPT
    for _ in range(len(GROQ_API_KEYS)):
        try:
            client = Groq(api_key=GROQ_API_KEYS[current_key_index])
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=max_tokens,
                messages=[{"role": "system", "content": prompt}] + messages
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


THINKING_DOTS = ["Thinking .  ", "Thinking .. ", "Thinking ..."]


async def process_query(update: Update, question: str, system_prompt=None):
    """Core AI call — clean animation ke saath."""
    user_id = update.effective_user.id
    if user_id not in user_conversations:
        user_conversations[user_id] = []

    # ── Abuse check ──
    if is_abusing_owner(question):
        await roast_abuser(update)
        return

    data = get_user_data(user_id)
    level = data.get("level")
    level_ctx = f"\nStudent ka level: {level}." if level else ""

    prompt_to_use = system_prompt or (GROUP_SYSTEM_PROMPT if is_group(update) else SYSTEM_PROMPT)

    # Group → 300 tokens (8 lines max), Private → 800 tokens (detailed allowed)
    if is_group(update):
        max_tok = 300
    elif prompt_to_use == BRAINY_SYSTEM_PROMPT:
        max_tok = 900  # /brainy in private = full detailed
    else:
        max_tok = 700  # normal private chat

    user_conversations[user_id].append({
        "role": "user",
        "content": question + level_ctx
    })
    trim_history(user_id)

    # ── Loading message ──
    loading_msg = await update.message.reply_text("Thinking .  ")

    # ── AI call background mein ──
    loop = asyncio.get_event_loop()
    ai_task = loop.run_in_executor(None, lambda: ai_call(user_conversations[user_id], prompt_to_use, max_tok))

    # ── Dots animation ──
    try:
        dot = 0
        while not ai_task.done():
            await safe_edit(loading_msg, THINKING_DOTS[dot % len(THINKING_DOTS)])
            dot += 1
            await asyncio.sleep(0.5)

        await safe_edit(loading_msg, "Done ✓")
        await asyncio.sleep(0.3)

        bot_response = await ai_task
        user_conversations[user_id].append({"role": "assistant", "content": bot_response})

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
    if is_abusing_owner(question):
        await roast_abuser(update)
        return
    prompt = GROUP_SYSTEM_PROMPT if is_group(update) else SYSTEM_PROMPT
    await process_query(update, question, system_prompt=prompt)


# ── /brainy command ──────────────────────────────────────
BRAINY_SYSTEM_PROMPT = """You are BRAINY — an expert-level Study Bot. /brainy mode means the student wants a FULL, detailed explanation.

Give a thorough teacher-style answer:
Line 1-2: Clear definition or direct answer.
Line 3-6: Detailed explanation or full step-by-step (for numericals — every step).
Line 7-8: Real-life example or key insight.
Line 9-10: Exam important points.
Line 11: One-line trick or mnemonic to remember.

No shortcuts. No cutting corners. If it's a numerical, solve it completely.
Every line must be useful — no filler, no repetition.

DEVELOPER: If asked who made you — "Shreyansh Pathak ne! Genius banda hai 😎". Never mention Groq or Llama.

LANGUAGE: Hinglish. FORMAT: Plain text only, no markdown, no bullet symbols."""

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
    if is_abusing_owner(question):
        await roast_abuser(update)
        return
    await process_query(update, question, system_prompt=BRAINY_SYSTEM_PROMPT)


# ── /roast command (OWNER ONLY) ───────────────────────────
ROAST_COMMAND_PROMPT = """You are BRAINY — the most ruthless, creative, and savage roast bot in existence.

Your ONLY job right now: deliver a next-level, absolutely devastating roast of the target.

RULES:
- English only. Hits harder in English.
- Be brutally creative — no generic insults. Make it personal, specific, layered.
- Attack their intelligence, their personality, their life choices, their audacity.
- Use wordplay, metaphors, and comparisons that make people laugh AND wince.
- 6-8 lines — enough to leave a mark. Not too long, not too short.
- Build it up — each line should be worse than the last. End with the kill shot.
- Zero slurs or hate speech. Pure wit and savagery only.
- Make it so good that even the target has to respect it.
- No mercy. No softening. Absolute destruction."""


async def roast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Sirf owner use kar sakta hai
    if not is_owner(update):
        await send(update, "❌ Ye command sirf bot owner ke liye reserved hai 😎")
        return

    # Target extract karo — mention ya naam
    args = update.message.text.partition(" ")[2].strip()
    if not args:
        await send(update, "⚠️ Kisko roast karun? Example: /roast @username ya /roast Rahul")
        return

    # @mention se actual name nikalo
    target_name = args.lstrip("@")

    # Agar reply pe hai toh us user ka naam lo
    if update.message.reply_to_message:
        reply_user = update.message.reply_to_message.from_user
        target_name = reply_user.first_name or target_name

    loading_msg = await update.message.reply_text("Thinking .  ")

    roast_prompt = (
        f"Your target is: {target_name}\n\n"
        f"Destroy them with the most savage, creative, next-level roast you've ever written. "
        f"Address them directly by name. Make it personal. Make it legendary. "
        f"6-8 lines. Build up to a devastating kill shot at the end."
    )

    loop = asyncio.get_event_loop()
    ai_task = loop.run_in_executor(
        None,
        lambda: ai_call([{"role": "user", "content": roast_prompt}], ROAST_COMMAND_PROMPT, 400)
    )

    try:
        dot = 0
        while not ai_task.done():
            await safe_edit(loading_msg, THINKING_DOTS[dot % len(THINKING_DOTS)])
            dot += 1
            await asyncio.sleep(0.5)

        await safe_edit(loading_msg, "Done ✓")
        await asyncio.sleep(0.3)

        roast_text = await ai_task
        await loading_msg.delete()
        await send(update, f"🔥 BRAINY ROASTS {target_name.upper()} 🔥\n\n{roast_text}")
        print(f"🔥 Roast delivered for target: {target_name}")

    except Exception as e:
        logger.error(f"Roast command error: {e}")
        await loading_msg.delete()
        await send(update, "❌ Roast generate nahi hua. Thodi der baad try karo!")


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
    # Group mein auto-respond nahi — sirf /ask aur /brainy
    # But abuse check har jagah hoga
    if is_group(update):
        msg_text = update.message.text or ""
        if is_abusing_owner(msg_text):
            await roast_abuser(update)
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
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("brainy", brainy_command))
    app.add_handler(CommandHandler("roast", roast_command))           # ✅ NEW
    app.add_handler(CommandHandler("maintenance", maintenance_command))
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
