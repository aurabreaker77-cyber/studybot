import os
import logging
import asyncio
import base64
import io
import random
import requests
from datetime import datetime
from dotenv import load_dotenv
from groq import Groq
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler
)

load_dotenv()
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_txt(filename):
    try:
        with open(os.path.join(BASE_DIR, "prompts", filename), "r", encoding="utf-8") as f:
            content = f.read()
            if not content.strip():
                print(f"⚠️ WARNING: {filename} is empty!")
            return content
    except Exception as e:
        print(f"❌ CRITICAL: Failed to load {filename}: {e}")
        return ""

SYSTEM_PROMPT           = load_txt("system_prompt.txt")
GROUP_SYSTEM_PROMPT     = load_txt("group_prompt.txt")
BRAINY_SYSTEM_PROMPT    = load_txt("brainy_prompt.txt")
IMAGE_SYSTEM_PROMPT     = load_txt("image_prompt.txt")
ROAST_SYSTEM_PROMPT     = load_txt("roast_prompt.txt")
ROAST_COMMAND_PROMPT    = load_txt("roast_command_prompt.txt")
TIP_SYSTEM_PROMPT       = load_txt("tip_prompt.txt")
FACT_SYSTEM_PROMPT      = load_txt("fact_prompt.txt")
JOKE_SYSTEM_PROMPT      = load_txt("joke_prompt.txt")
QUIZ_SYSTEM_PROMPT      = load_txt("quiz_prompt.txt")
SUMMARIZE_SYSTEM_PROMPT = load_txt("summarize_prompt.txt")
SEARCH_SYSTEM_PROMPT    = load_txt("search_prompt.txt")
BANTER_SYSTEM_PROMPT    = load_txt("banter_prompt.txt")

# ── Tokens ────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# ── API Keys (add as many as you want) ───────────────────
GROQ_API_KEYS       = [k for k in [os.getenv(f"GROQ_API_KEY_{i}")       for i in range(1, 6)] if k]
NVIDIA_API_KEYS     = [k for k in [os.getenv(f"NVIDIA_API_KEY_{i}")     for i in range(1, 6)] if k]
DEEPSEEK_API_KEYS   = [k for k in [os.getenv(f"DEEPSEEK_API_KEY_{i}")   for i in range(1, 6)] if k]
GEMINI_API_KEYS     = [k for k in [os.getenv(f"GEMINI_API_KEY_{i}")     for i in range(1, 6)] if k]
TAVILY_API_KEYS     = [k for k in [os.getenv(f"TAVILY_API_KEY_{i}")     for i in range(1, 6)] if k]
CEREBRAS_API_KEYS   = [k for k in [os.getenv(f"CEREBRAS_API_KEY_{i}")   for i in range(1, 6)] if k]
OPENROUTER_API_KEYS = [k for k in [os.getenv(f"OPENROUTER_API_KEY_{i}") for i in range(1, 6)] if k]
SAMBANOVA_API_KEYS  = [k for k in [os.getenv(f"SAMBANOVA_API_KEY_{i}")  for i in range(1, 6)] if k]
TOGETHER_API_KEYS   = [k for k in [os.getenv(f"TOGETHER_API_KEY_{i}")   for i in range(1, 6)] if k]

# ── Supabase (used for broadcast user list — persists across restarts) ──
SUPABASE_URL = os.getenv("SUPABASE_URL", "")          # e.g. https://xxxx.supabase.co
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")  # service_role key (server-side only, never expose to clients)

if not TELEGRAM_TOKEN or not GROQ_API_KEYS:
    print("ERROR: The bot server must be down try contacting dev for fix:- @shreyanshhh_08")
    exit()

print(f"Groq: {len(GROQ_API_KEYS)} | Nvidia: {len(NVIDIA_API_KEYS)} | Deepseek: {len(DEEPSEEK_API_KEYS)} | Gemini: {len(GEMINI_API_KEYS)} | Tavily: {len(TAVILY_API_KEYS)} | Cerebras: {len(CEREBRAS_API_KEYS)} | OpenRouter: {len(OPENROUTER_API_KEYS)} | SambaNova: {len(SAMBANOVA_API_KEYS)} | Together: {len(TOGETHER_API_KEYS)}")
print(f"Supabase: {'connected' if (SUPABASE_URL and SUPABASE_KEY) else 'NOT configured — broadcast list wont persist'}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   SUPABASE — persistent user registry for /broadcast
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Table schema (run once in Supabase SQL editor):
#
#   create table bot_users (
#     chat_id     bigint primary key,
#     chat_type   text default 'private',   -- 'private' or 'group'
#     username    text,
#     first_name  text,
#     joined_at   timestamptz default now(),
#     last_seen   timestamptz default now()
#   );
#
# Uses the service_role key (server-side only) so RLS doesn't block writes.
# All calls are wrapped in try/except — if Supabase is down or not configured,
# the bot keeps working normally, it just can't persist/broadcast to users.

def _supabase_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def supabase_register_user(chat_id: int, chat_type: str, username: str, first_name: str) -> None:
    """Upsert a user/group into bot_users. Call this on /start and on any incoming message
    so even users who never typed /start still end up reachable by /broadcast."""
    if not (SUPABASE_URL and SUPABASE_KEY):
        return
    try:
        payload = {
            "chat_id": chat_id,
            "chat_type": chat_type,
            "username": username or "",
            "first_name": first_name or "",
            "last_seen": datetime.now().isoformat(),
        }
        headers = _supabase_headers()
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        requests.post(
            f"{SUPABASE_URL}/rest/v1/bot_users",
            headers=headers, json=payload, timeout=8
        )
    except Exception as e:
        print(f"Supabase register_user failed (non-fatal): {str(e)[:100]}")


def supabase_get_all_users() -> list:
    """Returns list of dicts: [{chat_id, chat_type, first_name}, ...]"""
    if not (SUPABASE_URL and SUPABASE_KEY):
        return []
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/bot_users?select=chat_id,chat_type,first_name",
            headers=_supabase_headers(), timeout=15
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Supabase get_all_users failed: {str(e)[:100]}")
        return []


def supabase_remove_user(chat_id: int) -> None:
    """Called when a broadcast send fails because the user blocked the bot/deleted account —
    keeps the table clean so future broadcasts don't keep retrying dead chats."""
    if not (SUPABASE_URL and SUPABASE_KEY):
        return
    try:
        requests.delete(
            f"{SUPABASE_URL}/rest/v1/bot_users?chat_id=eq.{chat_id}",
            headers=_supabase_headers(), timeout=8
        )
    except Exception as e:
        print(f"Supabase remove_user failed (non-fatal): {str(e)[:100]}")


def supabase_user_count() -> int:
    if not (SUPABASE_URL and SUPABASE_KEY):
        return 0
    try:
        headers = _supabase_headers()
        headers["Prefer"] = "count=exact"
        resp = requests.head(f"{SUPABASE_URL}/rest/v1/bot_users?select=chat_id", headers=headers, timeout=10)
        content_range = resp.headers.get("content-range", "")
        if "/" in content_range:
            return int(content_range.split("/")[-1])
        return 0
    except Exception:
        return 0
if OWNER_ID: print(f"Owner ID: {OWNER_ID}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   PERSISTENT MEMORY — Supabase conversation history
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#  Run this SQL in Supabase ONCE to enable persistent memory:
#
#  create table if not exists user_memory (
#    user_id      bigint primary key,
#    first_name   text    default '',
#    username     text    default '',
#    level        text    default '',
#    score        int     default 0,
#    total        int     default 0,
#    joined_at    timestamptz default now(),
#    history      jsonb   default '[]'::jsonb,   -- last 20 messages
#    ask_history  jsonb   default '[]'::jsonb,   -- last 10 /ask messages
#    updated_at   timestamptz default now()
#  );
#
#  create index if not exists idx_user_memory_user_id on user_memory(user_id);

MAX_SAVED_HISTORY = 20   # how many messages to persist (same as in-memory MAX_HISTORY)
MAX_LIKED_NOTES   = 15   # how many 👍'd answer summaries to keep per user

def _sb_save_user_memory(user_id: int, first_name: str = "", username: str = "",
                          history: list = None, ask_history: list = None,
                          liked_notes: list = None,
                          level: str = "", score: int = 0, total: int = 0) -> None:
    """Upsert full user state into Supabase user_memory table — non-blocking fire-and-forget."""
    if not (SUPABASE_URL and SUPABASE_KEY):
        return
    try:
        import json as _json
        payload = {
            "user_id":     user_id,
            "first_name":  first_name or "",
            "username":    username or "",
            "level":       level or "",
            "score":       score,
            "total":       total,
            "updated_at":  datetime.now().isoformat(),
        }
        if history is not None:
            # Only save last MAX_SAVED_HISTORY messages & truncate content to save space
            trimmed = history[-MAX_SAVED_HISTORY:]
            payload["history"] = _json.dumps([
                {"role": m["role"], "content": m["content"][:800]}
                for m in trimmed
            ])
        if ask_history is not None:
            trimmed_ask = ask_history[-10:]
            payload["ask_history"] = _json.dumps([
                {"role": m["role"], "content": m["content"][:600]}
                for m in trimmed_ask
            ])
        if liked_notes is not None:
            payload["liked_notes"] = _json.dumps(liked_notes[-MAX_LIKED_NOTES:])
        headers = _supabase_headers()
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        requests.post(
            f"{SUPABASE_URL}/rest/v1/user_memory",
            headers=headers, json=payload, timeout=6
        )
    except Exception as e:
        print(f"[memory] save failed (non-fatal): {str(e)[:80]}")


def _sb_load_user_memory(user_id: int) -> dict:
    """Load a user's full state from Supabase. Returns {} if not found."""
    if not (SUPABASE_URL and SUPABASE_KEY):
        return {}
    try:
        import json as _json
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/user_memory?user_id=eq.{user_id}&select=*&limit=1",
            headers=_supabase_headers(), timeout=8
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return {}
        row = rows[0]
        # Deserialize JSON columns
        for key in ("history", "ask_history", "liked_notes"):
            val = row.get(key)
            if isinstance(val, str):
                try:
                    row[key] = _json.loads(val)
                except Exception:
                    row[key] = []
            elif val is None:
                row[key] = []
        return row
    except Exception as e:
        print(f"[memory] load failed (non-fatal): {str(e)[:80]}")
        return {}


def load_user_into_memory(user_id: int, first_name: str = "", username: str = "") -> None:
    """
    Called once per user on their first message/command in a session.
    Restores their conversation history + profile from Supabase into in-memory dicts.
    ALL features (chat, /ask, /brainy) now share ONE unified history (user_conversations)
    so context carries across every entry point — that used to be split into two silos.
    """
    if user_id in user_conversations:
        return   # already loaded this session
    row = _sb_load_user_memory(user_id)
    # Restore unified conversation history. Old saves may still have a separate
    # ask_history column from before the unification — merge it in once so nobody's
    # past /ask context gets silently dropped.
    history = row.get("history") or []
    legacy_ask_history = row.get("ask_history") or []
    if legacy_ask_history and not history:
        history = legacy_ask_history
    user_conversations[user_id] = history
    # Restore profile / progress data
    if user_id not in user_data_store:
        user_data_store[user_id] = {
            "level":  row.get("level") or "",
            "score":  row.get("score") or 0,
            "total":  row.get("total") or 0,
            "joined": datetime.now().strftime("%d %b %Y"),
            "liked_notes": row.get("liked_notes") or [],
        }
    if row:
        d = user_data_store[user_id]
        d["level"] = row.get("level") or d.get("level") or ""
        d["score"] = row.get("score") or d.get("score") or 0
        d["total"] = row.get("total") or d.get("total") or 0
        d["liked_notes"] = row.get("liked_notes") or d.get("liked_notes") or []
        restored = len(user_conversations[user_id])
        if restored:
            print(f"[memory] restored {restored} messages for user {user_id} ({first_name})")


def save_user_memory_async(user_id: int) -> None:
    """Fire-and-forget: saves current in-memory state for user_id to Supabase."""
    import threading
    data = user_data_store.get(user_id, {})
    threading.Thread(
        target=_sb_save_user_memory,
        kwargs=dict(
            user_id     = user_id,
            history     = user_conversations.get(user_id, []),
            liked_notes = data.get("liked_notes", []),
            level       = data.get("level", ""),
            score       = data.get("score", 0),
            total       = data.get("total", 0),
        ),
        daemon=True
    ).start()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   FANCY UNICODE FONT HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def bold(text: str) -> str:
    """Convert text to Unicode bold (Mathematical Bold)"""
    result = ""
    for ch in text:
        if 'A' <= ch <= 'Z':
            result += chr(ord(ch) - ord('A') + 0x1D400)
        elif 'a' <= ch <= 'z':
            result += chr(ord(ch) - ord('a') + 0x1D41A)
        elif '0' <= ch <= '9':
            result += chr(ord(ch) - ord('0') + 0x1D7CE)
        else:
            result += ch
    return result

def mono(text: str) -> str:
    """Convert text to Unicode monospace"""
    result = ""
    for ch in text:
        if 'A' <= ch <= 'Z':
            result += chr(ord(ch) - ord('A') + 0x1D670)
        elif 'a' <= ch <= 'z':
            result += chr(ord(ch) - ord('a') + 0x1D68A)
        elif '0' <= ch <= '9':
            result += chr(ord(ch) - ord('0') + 0x1D7F6)
        else:
            result += ch
    return result

def italic(text: str) -> str:
    """Convert text to Unicode italic"""
    result = ""
    special = {'h': '𝒉'}
    for ch in text:
        if ch in special:
            result += special[ch]
        elif 'A' <= ch <= 'Z':
            result += chr(ord(ch) - ord('A') + 0x1D434)
        elif 'a' <= ch <= 'z':
            result += chr(ord(ch) - ord('a') + 0x1D44E)
        else:
            result += ch
    return result

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   RESPONSE CLEANER — Fixes **bold** markdown artifacts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import re

def clean_response(text: str) -> str:
    """
    Convert AI markdown **bold** and *italic* → Unicode fonts.
    Handles multiline bold, nested patterns, and stray asterisks.
    """
    if not text:
        return text

    def replace_bold(m):
        inner = m.group(1).strip()
        return bold(inner) if inner else ""

    def replace_italic(m):
        inner = m.group(1).strip()
        return italic(inner) if inner else ""

    # Step 1: **bold** → Unicode bold (non-greedy, handles multiline)
    text = re.sub(r'\*\*(.+?)\*\*', replace_bold, text, flags=re.DOTALL)

    # Step 2: __bold__ → Unicode bold
    text = re.sub(r'__(.+?)__', replace_bold, text, flags=re.DOTALL)

    # Step 3: *italic* → Unicode italic (single asterisk only, not at line start bullets)
    text = re.sub(r'(?<!\*)\*(?!\*)([^\*\n]+?)(?<!\*)\*(?!\*)', replace_italic, text)

    # Step 4: _italic_ → Unicode italic
    text = re.sub(r'(?<!_)_(?!_)([^_\n]+?)(?<!_)_(?!_)', replace_italic, text)

    # Step 5: # headings → Unicode bold (so headings actually look bold, not plain text)
    def replace_heading(m):
        inner = m.group(2).strip()
        return bold(inner) if inner else ""
    text = re.sub(r'^(#{1,6})\s+(.+)$', replace_heading, text, flags=re.MULTILINE)

    # Step 6: Remove remaining stray ** or * that weren't converted
    # But KEEP "* " at start of line (bullet points)
    text = re.sub(r'\*\*', '', text)                          # remove leftover **
    text = re.sub(r'(?<!\n)\*(?=[^\s\n])', '', text)         # remove * mid-word only
    text = re.sub(r'(?<=[^\s\n])\*(?!\s|\n|$)', '', text)    # remove * after word only

    # Step 7: Clean up excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   WEB SEARCH ENGINE — DuckDuckGo (no API key needed)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def web_search(query: str, max_results: int = 5) -> str:
    """
    Search using Tavily API (primary) with DuckDuckGo as fallback.
    Returns a formatted string of results for the AI to use.
    """
    # ── PRIMARY: Tavily API ──────────────────────────────────
    if TAVILY_API_KEYS:
        for _tavily_attempt in range(len(TAVILY_API_KEYS)):
            try:
                key = _rotate_key("tavily", TAVILY_API_KEYS)
                payload = {
                    "api_key": key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results,
                    "include_answer": True,
                    "include_raw_content": False
                }
                resp = requests.post(
                    "https://api.tavily.com/search",
                    json=payload,
                    timeout=15,
                    headers={"Content-Type": "application/json"}
                )
                resp.raise_for_status()
                data = resp.json()

                results = []

                # Tavily's pre-summarized answer
                if data.get("answer"):
                    results.append(f"📌 Direct Answer: {data['answer']}")

                # Individual search results
                for r in data.get("results", [])[:max_results]:
                    title   = r.get("title", "")
                    content = r.get("content", "")
                    url     = r.get("url", "")
                    if content:
                        snippet = content[:300]
                        results.append(f"🔹 {title}\n   {snippet}\n   🔗 {url}" if url else f"🔹 {title}\n   {snippet}")

                if results:
                    print(f"Tavily search success (key #{_tavily_attempt+1}): {query[:40]}")
                    return "\n\n".join(results)

            except Exception as e:
                err_str = str(e).lower()
                if any(w in err_str for w in ["429", "rate", "quota", "limit"]):
                    print(f"Tavily key #{_tavily_attempt+1} rate-limited, trying next...")
                    continue
                print(f"Tavily search failed: {str(e)[:80]}, falling back to DuckDuckGo...")
                break

    # ── FALLBACK: DuckDuckGo ─────────────────────────────────
    try:
        ddg_url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
            "no_redirect": "1",
        }
        resp = requests.get(ddg_url, params=params, timeout=10,
                            headers={"User-Agent": "BrainyBot/1.0"})
        resp.raise_for_status()
        data = resp.json()

        results = []

        if data.get("AbstractText"):
            results.append(f"📌 {data['AbstractText'][:600]}")
            if data.get("AbstractURL"):
                results.append(f"🔗 Source: {data['AbstractURL']}")

        if data.get("Answer"):
            results.append(f"⚡ Direct Answer: {data['Answer']}")

        if data.get("Definition"):
            results.append(f"📖 Definition: {data['Definition'][:400]}")

        topics = data.get("RelatedTopics", [])
        count = 0
        for t in topics:
            if count >= max_results:
                break
            if isinstance(t, dict) and t.get("Text"):
                results.append(f"→ {t['Text'][:250]}")
                count += 1
            elif isinstance(t, dict) and t.get("Topics"):
                for sub in t["Topics"]:
                    if count >= max_results:
                        break
                    if isinstance(sub, dict) and sub.get("Text"):
                        results.append(f"→ {sub['Text'][:250]}")
                        count += 1

        if not results:
            # Last resort: DuckDuckGo lite scrape
            try:
                lite_resp = requests.get(
                    "https://lite.duckduckgo.com/lite/",
                    params={"q": query},
                    timeout=10,
                    headers={"User-Agent": "Mozilla/5.0 BrainyBot"}
                )
                from html.parser import HTMLParser

                class _DDGParser(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.snippets = []

                    def handle_data(self, data):
                        data = data.strip()
                        if data and len(data) > 40:
                            self.snippets.append(data)

                parser = _DDGParser()
                parser.feed(lite_resp.text)
                seen = set()
                for s in parser.snippets:
                    if s not in seen and not s.startswith(("Next", "Prev", "DuckDuckGo", "About")):
                        results.append(f"→ {s[:300]}")
                        seen.add(s)
                    if len(results) >= max_results:
                        break
            except Exception:
                pass

        if not results:
            return f"❌ '{query}' NO results for query, please try again."

        return "\n".join(results)

    except requests.exceptions.Timeout:
        return "⏰ Search timeout. Try again after a while."
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return f"❌ Error in search: {str(e)[:100]}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   GLOBAL STATE

MAINTENANCE_MODE        = False
user_conversations      = {}   # UNIFIED history for chat + /ask + /brainy (20 msgs = 10 exchanges)
user_data_store         = {}
interaction_log         = []   # Saved interactions for AI learning context
MAX_HISTORY             = 20   # 20 messages (10 exchanges)
MAX_INTERACTION_LOG     = 100  # Keep last 100 saved interactions for learning
CHOOSING_LEVEL          = 1

# 👍/👎 feedback: message_id → {"user_id", "question", "answer"}. Bounded so it
# can't grow forever — oldest entries are evicted once the cap is hit.
from collections import OrderedDict
pending_feedback     = OrderedDict()
MAX_PENDING_FEEDBACK  = 500

def _remember_feedback_target(message_id: int, user_id: int, question: str, answer: str) -> None:
    pending_feedback[message_id] = {"user_id": user_id, "question": question, "answer": answer}
    while len(pending_feedback) > MAX_PENDING_FEEDBACK:
        pending_feedback.popitem(last=False)  # evict oldest

def _feedback_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👍", callback_data="fb_up"),
        InlineKeyboardButton("👎", callback_data="fb_down"),
    ]])

key_idx = {"groq": 0, "nvidia": 0, "deepseek": 0, "gemini": 0, "tavily": 0, "cerebras": 0, "openrouter": 0, "sambanova": 0, "together": 0}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

THINKING_DOTS = ["🧠 ███▒▒▒▒▒▒▒ 20%", "🧠 ██████▒▒▒▒ 55%", "🧠 ██████████ 100%"]
SCANNING_DOTS = ["🔍 ███▒▒▒▒▒▒▒ 20%", "🔍 ██████▒▒▒▒ 55%", "🔍 ██████████ 100%"]


OWNER_NAMES = ["shreyansh", "pathak", "shreyansh pathak", "owner", "creator", "admin", "developer"]
ABUSE_KEYWORDS = [
    "chutiya", "madarchod", "bhenchod", "gandu", "randi", "harami", "sala", "saala",
    "bakwas", "stupid", "idiot", "dumb", "loser", "fool", "moron", "bastard",
    "bc", "mc", "bsdk", "lodu", "lawde", "bhosdike", "chodu",
    "fuck", "shit", "asshole", "dumbass", "retard", "worthless", "trash", "garbage",
    "bhadwa", "ullu", "pagal", "bevkoof", "nikamma", "haramkhor", "hizda", "hizdu"
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   MULTI-PROVIDER AI ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _rotate_key(provider: str, keys: list) -> str:
    key = keys[key_idx[provider]]
    key_idx[provider] = (key_idx[provider] + 1) % len(keys)
    return key

def _is_rate_err(e: Exception) -> bool:
    s = str(e).lower()
    return any(w in s for w in ["rate limit", "quota", "exceeded", "429", "402", "too many"])

def _call_groq(messages, system_prompt, max_tokens):
    if not GROQ_API_KEYS:
        raise Exception("NO_KEYS: groq")
    for _ in range(len(GROQ_API_KEYS)):
        try:
            key = _rotate_key("groq", GROQ_API_KEYS)
            client = Groq(api_key=key)
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=max_tokens,
                messages=[{"role": "system", "content": system_prompt}] + messages
            )
            truncated = resp.choices[0].finish_reason == "length"
            return resp.choices[0].message.content, truncated
        except Exception as e:
            if _is_rate_err(e):
                print(f"Groq key exhausted, rotating...")
                continue
            raise
    raise Exception("All Groq keys exhausted")

def _call_gemini(messages, system_prompt, max_tokens):
    if not GEMINI_API_KEYS:
        raise Exception("NO_KEYS: gemini")
    GEMINI_MODELS = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-3-flash-preview",
    ]
    rate_limited_count = 0
    for _ in range(len(GEMINI_API_KEYS)):
        try:
            key = _rotate_key("gemini", GEMINI_API_KEYS)
            contents = []
            for m in messages:
                role = "user" if m["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})
            payload = {
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": contents,
                "generationConfig": {"maxOutputTokens": max_tokens}
            }
            last_gemini_err = None
            for model in GEMINI_MODELS:
                try:
                    resp = requests.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
                        json=payload, timeout=20
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    candidate = data["candidates"][0]
                    parts = candidate.get("content", {}).get("parts")
                    if not parts:
                        # Thinking-enabled model spent the whole token budget on internal
                        # reasoning and never produced visible text — give a clear reason
                        # instead of a bare KeyError so it's obvious what happened.
                        reason = candidate.get("finishReason", "UNKNOWN")
                        raise Exception(f"Gemini returned no text (finishReason={reason}, likely ran out of tokens during thinking)")
                    text = parts[0]["text"]
                    truncated = candidate.get("finishReason") == "MAX_TOKENS"
                    return text, truncated
                except Exception as me:
                    if "404" in str(me) or "not found" in str(me).lower():
                        print(f"Gemini model {model} not found, trying next model...")
                        last_gemini_err = me
                        continue
                    raise
            if last_gemini_err:
                raise last_gemini_err
        except Exception as e:
            if _is_rate_err(e):
                rate_limited_count += 1
                print(f"Gemini key {rate_limited_count} rate limited, rotating...")
                continue
            if any(c in str(e) for c in ["401", "403", "API_KEY", "invalid"]):
                print(f"Gemini key invalid/expired, skipping...")
                continue
            raise
    # All keys rate limited or invalid — skip to next provider immediately
    print(f"All Gemini keys exhausted, moving to next provider...")
    raise Exception("NO_KEYS: gemini")

def _call_deepseek(messages, system_prompt, max_tokens):
    if not DEEPSEEK_API_KEYS:
        raise Exception("NO_KEYS: deepseek")
    DEEPSEEK_MODELS = ["deepseek-chat", "deepseek-v4-flash"]  # alias retires 2026-07-24, v4-flash is the direct replacement
    for _ in range(len(DEEPSEEK_API_KEYS)):
        key = _rotate_key("deepseek", DEEPSEEK_API_KEYS)
        last_err = None
        for model in DEEPSEEK_MODELS:
            try:
                payload = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system_prompt}] + messages
                }
                resp = requests.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload, timeout=25
                )
                resp.raise_for_status()
                data = resp.json()
                truncated = data["choices"][0].get("finish_reason") == "length"
                return data["choices"][0]["message"]["content"], truncated
            except Exception as e:
                err_str = str(e).lower()
                if "404" in err_str or "model" in err_str and "not" in err_str:
                    last_err = e
                    continue  # try next model name on this same key
                SKIP_ERRS = ["rate limit", "quota", "exceeded", "429", "402",
                             "insufficient", "balance", "credit", "payment"]
                if any(w in err_str for w in SKIP_ERRS):
                    print(f"Deepseek key has no balance (top up at platform.deepseek.com) — skipping to next provider...")
                    raise Exception("NO_KEYS: deepseek")
                last_err = e
                break
        if last_err:
            continue
    # All keys exhausted/out of balance — skip to next provider
    raise Exception("NO_KEYS: deepseek")

def _call_nvidia(messages, system_prompt, max_tokens):
    if not NVIDIA_API_KEYS:
        raise Exception("NO_KEYS: nvidia")
    for _ in range(len(NVIDIA_API_KEYS)):
        try:
            key = _rotate_key("nvidia", NVIDIA_API_KEYS)
            payload = {
                "model": "meta/llama-3.3-70b-instruct",
                "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system_prompt}] + messages
            }
            resp = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload, timeout=25
            )
            resp.raise_for_status()
            data = resp.json()
            truncated = data["choices"][0].get("finish_reason") == "length"
            return data["choices"][0]["message"]["content"], truncated
        except Exception as e:
            if _is_rate_err(e):
                print(f"Nvidia key exhausted, rotating...")
                continue
            raise
    raise Exception("All Nvidia keys exhausted")

def _call_cerebras(messages, system_prompt, max_tokens):
    if not CEREBRAS_API_KEYS:
        raise Exception("NO_KEYS: cerebras")
    # NOTE: Llama 3.3 70B was removed from Cerebras's public catalog — these are the
    # current models as of mid-2026. (Re-applying this fix; it reverted in this upload.)
    CEREBRAS_MODELS = ["gpt-oss-120b", "zai-glm-4.7"]
    for _ in range(len(CEREBRAS_API_KEYS)):
        try:
            key = _rotate_key("cerebras", CEREBRAS_API_KEYS)
            last_err = None
            for model in CEREBRAS_MODELS:
                try:
                    payload = {
                        "model": model,
                        "max_tokens": min(max_tokens, 2048),  # Cerebras max safe limit per call
                        "messages": [{"role": "system", "content": system_prompt}] + messages
                    }
                    resp = requests.post(
                        "https://api.cerebras.ai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json=payload, timeout=20
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    message = data["choices"][0]["message"]
                    if "content" not in message or message["content"] is None:
                        # Reasoning model (gpt-oss) burned the whole token budget on
                        # internal reasoning and never emitted a final answer.
                        reason = data["choices"][0].get("finish_reason", "unknown")
                        raise Exception(f"Cerebras returned no content (finish_reason={reason}, likely ran out of tokens during reasoning)")
                    truncated = data["choices"][0].get("finish_reason") == "length"
                    print(f"Cerebras model used: {model}")
                    return message["content"], truncated
                except Exception as me:
                    if "404" in str(me) or "not found" in str(me).lower() or "model" in str(me).lower():
                        print(f"Cerebras model {model} not found, trying next...")
                        last_err = me
                        continue
                    raise me
            if last_err:
                raise last_err
        except Exception as e:
            if _is_rate_err(e):
                print(f"Cerebras key exhausted, rotating...")
                continue
            if "404" not in str(e) and "model" not in str(e).lower():
                raise
    raise Exception("NO_KEYS: cerebras")

def _call_openrouter(messages, system_prompt, max_tokens):
    if not OPENROUTER_API_KEYS:
        raise Exception("NO_KEYS: openrouter")
    # Free models on OpenRouter (":free" suffix = zero cost, ~20 RPM / shared daily cap)
    OPENROUTER_MODELS = [
        "meta-llama/llama-3.3-70b-instruct:free",
        "deepseek/deepseek-chat-v3.1:free",
        "google/gemma-3-27b-it:free",
        "qwen/qwen3-235b-a22b:free",
    ]
    for _ in range(len(OPENROUTER_API_KEYS)):
        key = _rotate_key("openrouter", OPENROUTER_API_KEYS)
        last_err = None
        for model in OPENROUTER_MODELS:
            try:
                payload = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system_prompt}] + messages
                }
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://t.me/aurabreaker7",
                        "X-Title": "BRAINY Study Bot"
                    },
                    json=payload, timeout=25
                )
                resp.raise_for_status()
                data = resp.json()
                truncated = data["choices"][0].get("finish_reason") == "length"
                return data["choices"][0]["message"]["content"], truncated
            except Exception as e:
                err_str = str(e).lower()
                if "404" in err_str or "no longer" in err_str or "not found" in err_str:
                    print(f"OpenRouter model {model} unavailable, trying next free model...")
                    last_err = e
                    continue
                if _is_rate_err(e):
                    last_err = e
                    continue
                last_err = e
                break
        if last_err and _is_rate_err(last_err):
            continue
    raise Exception("NO_KEYS: openrouter")



def _call_sambanova(messages, system_prompt, max_tokens):
    """SambaNova Cloud — free tier, fast Meta Llama models"""
    if not SAMBANOVA_API_KEYS:
        raise Exception("NO_KEYS: sambanova")
    SAMBANOVA_MODELS = [
        "Meta-Llama-3.3-70B-Instruct",
        "Meta-Llama-3.1-70B-Instruct",
        "Meta-Llama-3.1-8B-Instruct",
    ]
    for _ in range(len(SAMBANOVA_API_KEYS)):
        key = _rotate_key("sambanova", SAMBANOVA_API_KEYS)
        last_err = None
        for model in SAMBANOVA_MODELS:
            try:
                payload = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system_prompt}] + messages
                }
                resp = requests.post(
                    "https://api.sambanova.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload, timeout=20
                )
                resp.raise_for_status()
                data = resp.json()
                truncated = data["choices"][0].get("finish_reason") == "length"
                return data["choices"][0]["message"]["content"], truncated
            except Exception as e:
                err_str = str(e).lower()
                if "404" in err_str or "not found" in err_str or "model" in err_str:
                    last_err = e
                    continue
                if _is_rate_err(e):
                    print(f"SambaNova key rate-limited, rotating...")
                    last_err = e
                    break
                last_err = e
                break
        if last_err and not _is_rate_err(last_err):
            raise last_err
    raise Exception("NO_KEYS: sambanova")


def _call_together(messages, system_prompt, max_tokens):
    """Together AI — free $1 credit on signup, fast inference"""
    if not TOGETHER_API_KEYS:
        raise Exception("NO_KEYS: together")
    TOGETHER_MODELS = [
        "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
        "meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo",
        "Qwen/Qwen2.5-72B-Instruct-Turbo",
    ]
    for _ in range(len(TOGETHER_API_KEYS)):
        key = _rotate_key("together", TOGETHER_API_KEYS)
        last_err = None
        for model in TOGETHER_MODELS:
            try:
                payload = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system_prompt}] + messages
                }
                resp = requests.post(
                    "https://api.together.xyz/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload, timeout=20
                )
                resp.raise_for_status()
                data = resp.json()
                truncated = data["choices"][0].get("finish_reason") == "length"
                return data["choices"][0]["message"]["content"], truncated
            except Exception as e:
                err_str = str(e).lower()
                if "404" in err_str or "not found" in err_str:
                    last_err = e
                    continue
                if _is_rate_err(e):
                    print(f"Together AI key rate-limited, rotating...")
                    last_err = e
                    break
                last_err = e
                break
        if last_err and not _is_rate_err(last_err):
            raise last_err
    raise Exception("NO_KEYS: together")


NUMERICAL_KEYWORDS = [
    "solve", "calculate", "find", "prove", "derive", "numerical",
    "integral", "differentiate", "equation", "theorem", "formula",
    "nikalo", "karo", "kyun", "kaise", "proof", "barao", "ghataao",
    "speed", "distance", "force", "energy", "voltage", "current",
    "resistance", "mass", "acceleration", "momentum", "wavelength"
]

CREATIVE_KEYWORDS = [
    "roast", "joke", "funny", "story", "poem", "caption",
    "write", "creative", "rap", "shayari", "fun", "meme"
]

GK_KEYWORDS = [
    "who", "what", "when", "where", "which", "kaun", "kya",
    "kab", "kahan", "capital", "president", "history", "country",
    "current affairs", "news", "award", "winner", "founded", "ai", "model", "gpt", "chatgpt"
]

# ── Off-topic banter detection ──────────────────────────────
# Anything that isn't study-related and reads like casual chit-chat switches
# the bot to BANTER_SYSTEM_PROMPT (funnier, looser tone) instead of the serious
# study persona. Sensitive topics are always excluded from this — never joke there.
STUDY_TOPIC_KEYWORDS = NUMERICAL_KEYWORDS + GK_KEYWORDS + [
    "physics", "chemistry", "maths", "math", "biology", "bio",
    "jee", "neet", "gujcet", "cet", "exam", "syllabus", "chapter", "ncert",
    "organic", "inorganic", "mechanics", "thermodynamics", "electrostatics",
    "optics", "trigonometry", "calculus", "algebra", "genetics", "ecology",
    "periodic table", "mole", "atom", "molecule", "reaction",
    "study", "revision", "quiz", "practice", "concept", "topic", "subject",
    "homework", "assignment", "explain", "define", "class 11", "class 12",
    "board exam", "marks", "percentage", "rank", "college", "admission",
    "level", "doubt", "question paper", "mock test", "formula"
]

SENSITIVE_KEYWORDS = [
    "sad", "depress", "suicide", "kill myself", "die", "death", "crying", "cry",
    "hurt", "breakup", "alone", "lonely", "hate myself", "worthless", "anxiety",
    "panic", "stressed", "stress", "give up", "tired of life", "no one cares",
    "self harm", "udaas", "akela", "rona", "dukhi", "pareshan"
]

def is_offtopic_chat(text: str) -> bool:
    """True when a message looks like casual chit-chat rather than a study question —
    short, no academic keywords, not a sensitive/emotional topic (never joke there)."""
    t = text.lower().strip()
    if not t or len(t.split()) > 18:
        return False
    if any(k in t for k in SENSITIVE_KEYWORDS):
        return False
    if any(k in t for k in STUDY_TOPIC_KEYWORDS):
        return False
    return True

def detect_question_type(messages) -> str:
    last_msg = ""
    for m in reversed(messages):
        if m["role"] == "user":
            last_msg = m["content"].lower()
            break
    if any(k in last_msg for k in NUMERICAL_KEYWORDS):
        return "numerical"
    if any(k in last_msg for k in CREATIVE_KEYWORDS):
        return "creative"
    if any(k in last_msg for k in GK_KEYWORDS):
        return "gk"
    if len(last_msg.split()) > 15:
        return "detailed"
    return "simple"

def get_provider_chain(question_type: str, system_prompt: str) -> list:
    """
    Every model assigned by its real-world strength, not randomly:
      • Deepseek    → math/reasoning specialist (DeepSeek-V3 class) — best for numbers, proofs, step-by-step
      • Cerebras    → blazing inference speed (gpt-oss-120b @ ~3000 tok/s) — best default/fast/group chat
      • Gemini      → strongest world-knowledge + native search grounding — best for GK, facts, summaries
      • Groq        → fast Llama hosting, great at natural creative/comedic tone — best for jokes/roasts/stories
      • SambaNova   → fast Llama hosting, solid all-rounder backup
      • Together    → wide open-model catalog, good knowledge breadth — backup for GK/summarize
      • OpenRouter  → 25+ free models in one key — universal last-resort fallback
      • Nvidia      → NIM-hosted Llama — final safety-net fallback (slowest observed)
    Routing is keyed off the SPECIFIC system_prompt object first (so /tip, /fact, /joke, /roast,
    /summarize, /search each get their own ideal chain regardless of what keywords are in the
    wrapped text), then falls back to keyword-detected question_type for plain chat/ask/brainy.
    """

    # ── BRAINY deep-teaching mode + numerical questions → math specialists first
    if system_prompt == BRAINY_SYSTEM_PROMPT or question_type == "numerical":
        return [
            ("Deepseek",    _call_deepseek),
            ("Cerebras",    _call_cerebras),
            ("Gemini",      _call_gemini),
            ("Groq",        _call_groq),
            ("SambaNova",   _call_sambanova),
            ("Together",    _call_together),
            ("OpenRouter",  _call_openrouter),
            ("Nvidia",      _call_nvidia),
        ]

    # ── Roast modes (savage humor, punchy tone) → Groq's creative tone first
    if system_prompt in (ROAST_SYSTEM_PROMPT, ROAST_COMMAND_PROMPT):
        return [
            ("Groq",        _call_groq),
            ("Together",    _call_together),
            ("SambaNova",   _call_sambanova),
            ("Cerebras",    _call_cerebras),
            ("Gemini",      _call_gemini),
            ("OpenRouter",  _call_openrouter),
            ("Deepseek",    _call_deepseek),
            ("Nvidia",      _call_nvidia),
        ]

    # ── Comedy (one-liner jokes) → same creative-tone priority as roast
    if system_prompt == JOKE_SYSTEM_PROMPT:
        return [
            ("Groq",        _call_groq),
            ("Together",    _call_together),
            ("SambaNova",   _call_sambanova),
            ("Cerebras",    _call_cerebras),
            ("Gemini",      _call_gemini),
            ("OpenRouter",  _call_openrouter),
            ("Deepseek",    _call_deepseek),
            ("Nvidia",      _call_nvidia),
        ]

    # ── Tip / Fact (accuracy + broad world-knowledge matters) → Gemini first
    if system_prompt in (TIP_SYSTEM_PROMPT, FACT_SYSTEM_PROMPT):
        return [
            ("Gemini",      _call_gemini),
            ("Together",    _call_together),
            ("Cerebras",    _call_cerebras),
            ("Groq",        _call_groq),
            ("SambaNova",   _call_sambanova),
            ("Deepseek",    _call_deepseek),
            ("OpenRouter",  _call_openrouter),
            ("Nvidia",      _call_nvidia),
        ]

    # ── Quiz (needs accurate facts/formulas + strict format adherence — not creative tone)
    if system_prompt == QUIZ_SYSTEM_PROMPT:
        return [
            ("Gemini",      _call_gemini),
            ("Deepseek",    _call_deepseek),
            ("Together",    _call_together),
            ("Cerebras",    _call_cerebras),
            ("Groq",        _call_groq),
            ("SambaNova",   _call_sambanova),
            ("OpenRouter",  _call_openrouter),
            ("Nvidia",      _call_nvidia),
        ]

    # ── Summarize (long-context compression) → Gemini's long-context handling first
    if system_prompt == SUMMARIZE_SYSTEM_PROMPT:
        return [
            ("Gemini",      _call_gemini),
            ("Cerebras",    _call_cerebras),
            ("Together",    _call_together),
            ("Deepseek",    _call_deepseek),
            ("Groq",        _call_groq),
            ("SambaNova",   _call_sambanova),
            ("OpenRouter",  _call_openrouter),
            ("Nvidia",      _call_nvidia),
        ]

    # ── Search synthesis (needs accurate grounding from live web results) → Gemini first
    if system_prompt == SEARCH_SYSTEM_PROMPT:
        return [
            ("Gemini",      _call_gemini),
            ("Cerebras",    _call_cerebras),
            ("Deepseek",    _call_deepseek),
            ("Together",    _call_together),
            ("Groq",        _call_groq),
            ("SambaNova",   _call_sambanova),
            ("OpenRouter",  _call_openrouter),
            ("Nvidia",      _call_nvidia),
        ]

    # ── Group chat (fast, punchy, low-latency replies) → speed-first chain
    if system_prompt == GROUP_SYSTEM_PROMPT:
        return [
            ("Cerebras",    _call_cerebras),
            ("Groq",        _call_groq),
            ("SambaNova",   _call_sambanova),
            ("Gemini",      _call_gemini),
            ("Deepseek",    _call_deepseek),
            ("OpenRouter",  _call_openrouter),
            ("Together",    _call_together),
            ("Nvidia",      _call_nvidia),
        ]

    # ── Generic creative (poems, stories, captions via /ask) → Groq's tone first
    if question_type == "creative":
        return [
            ("Groq",        _call_groq),
            ("Cerebras",    _call_cerebras),
            ("SambaNova",   _call_sambanova),
            ("Together",    _call_together),
            ("Gemini",      _call_gemini),
            ("OpenRouter",  _call_openrouter),
            ("Deepseek",    _call_deepseek),
            ("Nvidia",      _call_nvidia),
        ]

    # ── General knowledge questions → Gemini's world-knowledge first
    if question_type == "gk":
        return [
            ("Gemini",      _call_gemini),
            ("Together",    _call_together),
            ("Cerebras",    _call_cerebras),
            ("Groq",        _call_groq),
            ("SambaNova",   _call_sambanova),
            ("Deepseek",    _call_deepseek),
            ("OpenRouter",  _call_openrouter),
            ("Nvidia",      _call_nvidia),
        ]

    # ── Long/detailed explanations → fast model that can sustain longer output
    if question_type == "detailed":
        return [
            ("Cerebras",    _call_cerebras),
            ("Deepseek",    _call_deepseek),
            ("Gemini",      _call_gemini),
            ("Groq",        _call_groq),
            ("SambaNova",   _call_sambanova),
            ("Together",    _call_together),
            ("OpenRouter",  _call_openrouter),
            ("Nvidia",      _call_nvidia),
        ]

    # ── Default/simple chat → fastest model first
    return [
        ("Cerebras",    _call_cerebras),
        ("Groq",        _call_groq),
        ("SambaNova",   _call_sambanova),
        ("Gemini",      _call_gemini),
        ("Deepseek",    _call_deepseek),
        ("OpenRouter",  _call_openrouter),
        ("Together",    _call_together),
        ("Nvidia",      _call_nvidia),
    ]

PROVIDER_MAX_TOKENS = {
    "Groq":       8192,
    "Gemini":     8192,
    "Deepseek":   8192,
    "Nvidia":     4096,
    "Cerebras":   2048,   # hard per-call ceiling — continuation rounds make up the rest
    "OpenRouter": 4096,
    "SambaNova":  4096,
    "Together":   4096,
}

MAX_CONTINUATION_ROUNDS = 4  # safety cap so one runaway answer can't loop forever / burn quota

def ai_call(messages, system_prompt=None, max_tokens=None):
    """
    No more fixed truncation. max_tokens is just a *starting* budget — if the model's
    answer genuinely needs more space, we detect the cut-off (finish_reason == length /
    MAX_TOKENS) and automatically ask it to continue from where it stopped, stitching the
    pieces together. The model decides when it's actually finished, not an arbitrary cap.
    """
    prompt = system_prompt or SYSTEM_PROMPT
    q_type = detect_question_type(messages)

    if max_tokens is None:
        TOKEN_MAP = {
            "numerical": 1200,
            "detailed":  1000,
            "gk":        700,
            "creative":  800,
            "simple":    500,
        }
        max_tokens = TOKEN_MAP.get(q_type, 600)

    chain = get_provider_chain(q_type, prompt)
    print(f"Q-type: {q_type} | starting tokens: {max_tokens} → {chain[0][0]}")
    last_err = None

    for name, caller in chain:
        try:
            provider_cap = PROVIDER_MAX_TOKENS.get(name, max_tokens)
            call_tokens = min(max_tokens, provider_cap) if max_tokens else provider_cap
            text, truncated = caller(messages, prompt, call_tokens)
            full_text = text or ""

            rounds = 0
            convo = list(messages)
            while truncated and rounds < MAX_CONTINUATION_ROUNDS:
                rounds += 1
                convo = convo + [
                    {"role": "assistant", "content": full_text},
                    {"role": "user", "content": "Continue exactly from where you stopped. Don't repeat anything, don't restart — just keep going."}
                ]
                try:
                    cont_text, truncated = caller(convo, prompt, provider_cap)
                    full_text += cont_text or ""
                except Exception as ce:
                    print(f"Continuation failed on {name} (round {rounds}): {str(ce)[:60]} — returning partial answer")
                    break

            suffix = f" (+{rounds} continuation{'s' if rounds != 1 else ''})" if rounds else ""
            print(f"✅ {name}{suffix}")
            return full_text
        except Exception as e:
            if "NO_KEYS:" in str(e):
                continue
            print(f"❌ {name}: {str(e)[:60]}")
            last_err = e
    raise Exception(f"All providers failed: {last_err}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   IMAGE ANALYSIS ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _analyze_gemini_vision(image_bytes: bytes, question: str) -> str:
    if not GEMINI_API_KEYS:
        raise Exception("NO_KEYS: gemini_vision")
    VISION_MODELS = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-3-flash-preview",
    ]
    key = _rotate_key("gemini", GEMINI_API_KEYS)
    img_b64 = base64.b64encode(image_bytes).decode("utf-8")
    user_text = question if question else "Solve or explain whatever question, problem, or concept is in this image."

    contents = [{"role": "user", "parts": [
        {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
        {"text": user_text}
    ]}]

    last_err = None
    for model in VISION_MODELS:
        try:
            full_text = ""
            rounds = 0
            convo = list(contents)
            while True:
                payload = {
                    "system_instruction": {"parts": [{"text": IMAGE_SYSTEM_PROMPT}]},
                    "contents": convo,
                    "generationConfig": {"maxOutputTokens": 1500}
                }
                resp = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
                    json=payload, timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
                candidate = data["candidates"][0]
                chunk = candidate["content"]["parts"][0]["text"]
                full_text += chunk
                truncated = candidate.get("finishReason") == "MAX_TOKENS"
                if not truncated or rounds >= MAX_CONTINUATION_ROUNDS:
                    break
                rounds += 1
                convo = convo + [
                    {"role": "model", "parts": [{"text": chunk}]},
                    {"role": "user", "parts": [{"text": "Continue exactly from where you stopped. Don't repeat anything, don't restart — just keep going."}]}
                ]
            return full_text
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                print(f"Gemini vision model {model} not found, trying next...")
                last_err = e
                continue
            raise
    raise last_err or Exception("All Gemini vision models failed")

def _analyze_groq_vision(image_bytes: bytes, question: str) -> str:
    if not GROQ_API_KEYS:
        raise Exception("NO_KEYS: groq_vision")
    key = _rotate_key("groq", GROQ_API_KEYS)
    img_b64 = base64.b64encode(image_bytes).decode("utf-8")
    user_text = question if question else "Solve or explain whatever question, problem, or concept is in this image."
    client = Groq(api_key=key)

    convo = [
        {"role": "system", "content": IMAGE_SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            {"type": "text", "text": user_text}
        ]}
    ]
    full_text = ""
    rounds = 0
    while True:
        resp = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            max_tokens=1500,
            messages=convo
        )
        chunk = resp.choices[0].message.content
        full_text += chunk
        truncated = resp.choices[0].finish_reason == "length"
        if not truncated or rounds >= MAX_CONTINUATION_ROUNDS:
            break
        rounds += 1
        convo = convo + [
            {"role": "assistant", "content": chunk},
            {"role": "user", "content": "Continue exactly from where you stopped. Don't repeat anything, don't restart — just keep going."}
        ]
    return full_text

def analyze_image(image_bytes: bytes, question: str = "") -> str:
    """Try Gemini vision first, fall back to Groq vision silently."""
    if GEMINI_API_KEYS:
        try:
            result = _analyze_gemini_vision(image_bytes, question)
            return result
        except Exception as e:
            err = str(e)
            # 404 = model not found, 401/403 = key invalid — all silent fallback
            if any(code in err for code in ["404", "401", "403", "NO_KEYS"]):
                print(f"Gemini vision unavailable, using Groq vision...")
            else:
                print(f"Gemini vision error: {err[:60]}, trying Groq vision...")
    else:
        print("No Gemini keys, using Groq vision directly...")
    return _analyze_groq_vision(image_bytes, question)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   HELPER FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def is_group(update: Update) -> bool:
    return update.effective_chat.type in ("group", "supergroup")

def is_owner(update: Update) -> bool:
    return update.effective_user.id == OWNER_ID

def trim_history(user_id):
    """Keep only last MAX_HISTORY messages (20 = 10 exchanges) - unified for chat/ask/brainy"""
    if user_id in user_conversations:
        user_conversations[user_id] = user_conversations[user_id][-MAX_HISTORY:]

def save_interaction(user_id: int, question: str, answer: str, source: str = "chat"):
    """Save a Q&A interaction to the global learning log"""
    global interaction_log
    entry = {
        "user_id": user_id,
        "q": question[:300],
        "a": answer[:500],
        "source": source,
        "time": datetime.now().strftime("%d/%m %H:%M")
    }
    interaction_log.append(entry)
    if len(interaction_log) > MAX_INTERACTION_LOG:
        interaction_log = interaction_log[-MAX_INTERACTION_LOG:]

def get_learning_context(limit: int = 5) -> str:
    """Build a short learning context string from recent interactions for the AI prompt"""
    if not interaction_log:
        return ""
    recent = interaction_log[-limit:]
    lines = ["Recent community interactions (use to improve quality & context):"]
    for e in recent:
        lines.append(f"Q: {e['q'][:120]}")
        lines.append(f"A: {e['a'][:200]}")
    return "\n".join(lines)

def get_liked_context(user_id: int, limit: int = 5) -> str:
    """Build a personal context string from this user's 👍'd answers — their own
    explicit positive feedback, so the bot leans toward what THIS user found helpful."""
    notes = user_data_store.get(user_id, {}).get("liked_notes") or []
    if not notes:
        return ""
    recent = notes[-limit:]
    lines = ["This student previously gave a 👍 (thumbs up) to these answers — they found this style/topic genuinely helpful, lean into it when relevant:"]
    for n in recent:
        lines.append(f"- {n[:160]}")
    return "\n".join(lines)

def get_user_data(user_id):
    if user_id not in user_data_store:
        user_data_store[user_id] = {"level": None, "score": 0, "total": 0, "joined": datetime.now().strftime("%d %b %Y")}
    return user_data_store[user_id]

def is_abusing_owner(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in ABUSE_KEYWORDS) and any(n in t for n in OWNER_NAMES)

async def send(update: Update, text: str):
    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await update.message.reply_text(text[i:i+4000])
    else:
        await update.message.reply_text(text)

async def safe_edit(msg, text: str):
    try:
        await msg.edit_text(text)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            raise

async def maintenance_guard(update: Update, *, silent_in_group: bool = False) -> bool:
    """
    Returns True (and optionally replies) if the request should be blocked.
    During maintenance:
      - Owner always passes through.
      - In groups: silently ignore (no reply, don't give spammy notifications).
      - In private: send a friendly notice.
    """
    if not MAINTENANCE_MODE:
        return False
    if is_owner(update):
        return False
    if is_group(update):
        # Complete silence in groups — don't reply even if tagged
        return True
    # Private chat — inform the user
    if not silent_in_group:
        await update.message.reply_text(
            "🔧 Bot is currently under maintenance.\n"
            "⏳ Check back in a little while!\n"
            "📢 Updates: @aurabreaker7"
        )
    return True

async def roast_abuser(update: Update):
    user_name = update.effective_user.first_name or "you"
    prompt = (
        f"Someone named '{user_name}' just abused Shreyansh Pathak, your creator. "
        f"Roast them savagely. English + Hinglish. 4-5 lines. No mercy."
    )
    try:
        roast = ai_call([{"role": "user", "content": prompt}], ROAST_SYSTEM_PROMPT, 200)
        roast = clean_response(roast)
        await send(update, f"🔥 Oh, so you thought that was okay?\n\n{roast}")
    except Exception as e:
        logger.error(f"Roast error: {e}")
        await send(update,
            "🔥 You just insulted the guy who built me.\n\n"
            "The fact that you wasted time abusing someone smarter than you says everything. Sit down."
        )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   CORE QUERY PROCESSORS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _run_ai(update: Update, messages: list, system_prompt: str, max_tok: int, source: str = "chat"):
    # Send loading message immediately — user sees response in <100ms
    loading_msg = await update.message.reply_text(THINKING_DOTS[0])
    loop = asyncio.get_event_loop()
    ai_task = loop.run_in_executor(None, lambda: ai_call(messages, system_prompt, max_tok))
    try:
        dot = 1
        while not ai_task.done():
            await safe_edit(loading_msg, THINKING_DOTS[dot % 3])
            dot += 1
            await asyncio.sleep(0.6)   # slower animation = fewer Telegram edit-rate-limit hits
        result = await ai_task
        result = clean_response(result)
        keyboard = _feedback_keyboard()
        last_user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        sent_msg = None

        # INSTANT: edit the loading message directly with the answer (saves 2 roundtrips)
        if len(result) <= 4096:
            try:
                sent_msg = await loading_msg.edit_text(result, reply_markup=keyboard)
            except Exception:
                # edit failed (e.g. same text) — fall back to delete+send
                await loading_msg.delete()
                sent_msg = await update.message.reply_text(result, reply_markup=keyboard)
        else:
            # Long answer: delete loading, send in chunks — buttons go on the final chunk
            await loading_msg.delete()
            chunks = [result[i:i+4000] for i in range(0, len(result), 4000)]
            for i, chunk in enumerate(chunks):
                is_last = (i == len(chunks) - 1)
                sent_msg = await update.message.reply_text(chunk, reply_markup=keyboard if is_last else None)

        if sent_msg is not None and last_user_msg:
            _remember_feedback_target(sent_msg.message_id, update.effective_user.id, last_user_msg, result)

        print(f"✅ Sent to {update.effective_user.id} via {source}")
        # Save interaction for learning
        if last_user_msg and result:
            save_interaction(update.effective_user.id, last_user_msg, result, source)
        return result
    except Exception as e:
        logger.error(f"AI error: {e}")
        try:
            await loading_msg.edit_text(f"❌ Kuch error aaya: {str(e)[:100]}\n\n⏳ Thodi der baad phir try karo!")
        except Exception:
            await loading_msg.delete()
            await send(update, f"❌ Kuch error aaya: {str(e)[:100]}\n\n⏳ Thodi der baad phir try karo!")
        return None

async def process_ask(update: Update, question: str):
    if is_abusing_owner(question):
        await roast_abuser(update)
        return
    user_id    = update.effective_user.id
    first_name = update.effective_user.first_name or ""
    username   = update.effective_user.username or ""

    # ── Restore from Supabase if first message this session ──
    load_user_into_memory(user_id, first_name, username)

    if user_id not in user_conversations:
        user_conversations[user_id] = []
    data = get_user_data(user_id)
    level = data.get("level")
    level_ctx = f"\nStudent ka level: {level}." if level else ""

    prompt = GROUP_SYSTEM_PROMPT if is_group(update) else SYSTEM_PROMPT
    max_tok = 250 if is_group(update) else None

    # ── Inject user identity + learning context ───────────────
    user_ctx_parts = []
    if first_name:
        user_ctx_parts.append(f"User's name: {first_name}. Address them by name occasionally to feel personal.")
    if level:
        user_ctx_parts.append(f"Student level: {level}. Tailor depth/complexity accordingly.")
    learn_ctx = get_learning_context(5)
    if learn_ctx:
        user_ctx_parts.append(learn_ctx)
    if user_ctx_parts:
        prompt = prompt + "\n\n" + "\n".join(user_ctx_parts)

    user_conversations[user_id].append({"role": "user", "content": question + level_ctx})
    trim_history(user_id)
    result = await _run_ai(update, user_conversations[user_id], prompt, max_tok, source="ask")
    if result:
        user_conversations[user_id].append({"role": "assistant", "content": result})
        # ── Persist to Supabase async (non-blocking) ─────────
        save_user_memory_async(user_id)

async def process_brainy(update: Update, question: str):
    if is_abusing_owner(question):
        await roast_abuser(update)
        return
    user_id    = update.effective_user.id
    first_name = update.effective_user.first_name or ""
    username   = update.effective_user.username or ""

    # ── Restore from Supabase if first message this session ──
    load_user_into_memory(user_id, first_name, username)

    data = get_user_data(user_id)
    level = data.get("level")
    level_ctx = f"\nStudent ka level: {level}." if level else ""
    user_conversations[user_id].append({"role": "user", "content": question + level_ctx})
    trim_history(user_id)

    # Inject learning context + this user's own liked-answer memory into brainy prompt
    learn_ctx  = get_learning_context(3)
    liked_ctx  = get_liked_context(user_id, 3)
    brainy_prompt = BRAINY_SYSTEM_PROMPT
    extra = "\n\n".join(c for c in (learn_ctx, liked_ctx) if c)
    if extra:
        brainy_prompt = brainy_prompt + "\n\n" + extra

    result = await _run_ai(update, user_conversations[user_id], brainy_prompt, 1000, source="brainy")
    if result:
        user_conversations[user_id].append({"role": "assistant", "content": result})
        save_user_memory_async(user_id)

async def process_query(update: Update, question: str, system_prompt=None):
    user_id    = update.effective_user.id
    first_name = update.effective_user.first_name or ""
    username   = update.effective_user.username or ""

    # ── Restore from Supabase if first message this session ──
    load_user_into_memory(user_id, first_name, username)

    if is_abusing_owner(question):
        await roast_abuser(update)
        return
    data = get_user_data(user_id)
    level = data.get("level")
    level_ctx = f"\nStudent ka level: {level}." if level else ""

    if is_group(update):
        base_prompt = GROUP_SYSTEM_PROMPT
    elif system_prompt:
        base_prompt = system_prompt
    elif is_offtopic_chat(question):
        # Casual chit-chat, not a study question → funnier off-topic persona
        base_prompt = BANTER_SYSTEM_PROMPT or SYSTEM_PROMPT
    else:
        base_prompt = SYSTEM_PROMPT
    max_tok = 250 if is_group(update) else None   # None = ai_call picks smart limit per question type

    # Inject learning context + this user's own liked-answer memory
    learn_ctx = get_learning_context(5)
    liked_ctx = get_liked_context(user_id, 5)
    extra = "\n\n".join(c for c in (learn_ctx, liked_ctx) if c)
    if extra:
        base_prompt = base_prompt + "\n\n" + extra

    user_conversations[user_id].append({"role": "user", "content": question + level_ctx})
    trim_history(user_id)
    result = await _run_ai(update, user_conversations[user_id], base_prompt, max_tok, source="query")
    if result:
        user_conversations[user_id].append({"role": "assistant", "content": result})
        save_user_memory_async(user_id)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   IMAGE HANDLER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_group(update) and MAINTENANCE_MODE and not is_owner(update):
        return  # Silent during maintenance
    if await maintenance_guard(update):
        return
    caption = update.message.caption or ""
    if is_group(update):
        if not caption.lower().startswith("/image"):
            return
        question = caption.partition(" ")[2].strip()
    else:
        question = caption
        if question.lower().startswith("/image"):
            question = question.partition(" ")[2].strip()

    if update.message.photo:
        file_obj = await context.bot.get_file(update.message.photo[-1].file_id)
    elif update.message.document and update.message.document.mime_type.startswith("image/"):
        file_obj = await context.bot.get_file(update.message.document.file_id)
    else:
        await send(update, "❌ Only image files are supported!")
        return

    loading_msg = await update.message.reply_text("🔍 Scanning .  ")
    try:
        buf = io.BytesIO()
        await file_obj.download_to_memory(buf)
        image_bytes = buf.getvalue()
        loop = asyncio.get_event_loop()
        ai_task = loop.run_in_executor(None, lambda: analyze_image(image_bytes, question))
        dot = 0
        while not ai_task.done():
            await safe_edit(loading_msg, SCANNING_DOTS[dot % 3])
            dot += 1
            await asyncio.sleep(0.5)
        result = await ai_task
        result = clean_response(result)
        await loading_msg.delete()
        await send(update, f"📷 𝗜𝗺𝗮𝗴𝗲 𝗔𝗻𝗮𝗹𝘆𝘀𝗶𝘀:\n\n{result}")
        print(f"Image analyzed for {update.effective_user.id}")
    except Exception as e:
        logger.error(f"Image error: {e}")
        await loading_msg.delete()
        if "NO_KEYS" in str(e):
            await send(update,
                "❌ Add GEMINI_API_KEY_1 to .env for image analysis!\n"
                "🔗 Free key: aistudio.google.com"
            )
        else:
            await send(update, f"❌ Error scanning image: {str(e)[:100]}\n\n⏳ Try again in a bit!")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   ALL COMMANDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    if is_group(update):
        chat = update.effective_chat
        supabase_register_user(chat.id, "group", chat.title or "", "")
        await send(update,
            "⚡ 𝗕𝗥𝗔𝗜𝗡𝗬 𝗦𝘁𝘂𝗱𝘆 𝗕𝗼𝘁 𝗶𝘀 𝗮𝗰𝘁𝗶𝘃𝗲! ⚡\n\n"
            "📋 𝗚𝗿𝗼𝘂𝗽 𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀:\n"
            "⚡ /ask [question]  — Ask the AI\n"
            "🧠 /brainy [topic] — Deep explanation\n"
            "📷 /image [question] — Solve from an image\n"
            "💡 /tip            — Study tip of the day\n"
            "🤯 /fact           — Mind-blowing fact\n"
            "😂 /joke           — Hear a joke\n"
            "🔍 /search [query] — Real-time web search\n\n"
            "🔒 Come to a private chat for full features!\n"
            "📢 Join: @aurabreaker7"
        )
        return
    user_name = update.effective_user.first_name
    user_id   = update.effective_user.id
    user_conversations[user_id] = []
    get_user_data(user_id)
    supabase_register_user(user_id, "private", update.effective_user.username or "", user_name or "")
    await send(update,
        f"⚡ 𝗡𝗮𝗺𝗮𝘀𝘁𝗲, {user_name}! ⚡\n\n"
        "🤖 I'm 𝗕𝗥𝗔𝗜𝗡𝗬 — Your Personal AI Study Partner!\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎯 What I can do:\n"
"→ Crack Physics, Chemistry, Math & Biology problems\n"
"→ Break down numericals step-by-step — no shortcuts\n"
"→ Solve questions straight from your photos\n"
"→ Run MCQ quizzes & build practice sets\n"
"→ Pull up any subject's formulas instantly\n"
"→ Answer GK, current affairs & tech questions\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀:\n"
        "⚡ /ask       — Fast answer\n"
        "🧠 /brainy    — Deep teacher-level explanation\n"
        "🔢 /ask5      — 5 angles on one concept\n"
        "📷 /image     — Solve from an image\n"
        "🎯 /level     — Set your class level\n"
        "📝 /quiz      — Random MCQ (tap A/B/C/D!)\n"
        "📚 /formula   — Subject formulas list\n"
        "🏋️ /practice  — Exam-style question\n"
        "📊 /progress  — Score card\n"
        "📅 /myplan    — 7-day study plan\n"
        "📓 /mynotes   — Your saved 👍 answers\n"
        "💡 /tip       — Study tip of the day\n"
        "🤯 /fact      — Mind-blowing fact\n"
        "😂 /joke      — Hear a joke\n"
        "💪 /motivate  — Personal motivation\n"
        "📖 /define    — Dictionary for any word\n"
        "🌐 /translate — Translate any text\n"
        "📋 /summarize — Summary of a topic\n"
        "🔍 /search    — Real-time web search\n"
        "🗑️ /clear     — Reset chat history\n"
        "ℹ️ /about     — About the bot\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    print(f"User started: {user_name} ({user_id})")


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick latency check — measures Telegram round-trip + bot processing time."""
    start = datetime.now()
    msg = await update.message.reply_text("🏓 Pinging...")
    ms = int((datetime.now() - start).total_seconds() * 1000)
    try:
        await msg.edit_text(f"🏓 Pong! {ms}ms")
    except Exception:
        pass


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    if is_group(update):
        await send(update,
            "📋 𝗚𝗿𝗼𝘂𝗽 𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀:\n\n"
            "⚡ /ask       — Flash 3.1 {Fast Answer}\n"
            "🧠 /brainy [topic] — Detailed explanation\n"
            "📷 /image     — Answer to the image question\n"
            "💡 /tip            — Study tip\n"
            "🤯 /fact           — Interesting fact\n"
            "🔒Send /help in a private chat to see the full menu!"
        )
        return
    await send(update,
        "📋 𝗛𝗲𝗹𝗽 𝗠𝗲𝗻𝘂 — 𝗕𝗥𝗔𝗜𝗡𝗬\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚡ /ask       — Fast answer\n"
        "🧠 /brainy    — Deep teacher-level explanation\n"
        "🔢 /ask5      — 5 angles on one concept\n"
        "📷 /image     — Solve from an image\n"
        "🎯 /level     — Set your class level\n"
        "📝 /quiz      — Random MCQ (tap A/B/C/D!)\n"
        "📚 /formula   — Subject formulas list\n"
        "🏋️ /practice  — Exam-style question\n"
        "📊 /progress  — Score card\n"
        "📅 /myplan    — 7-day study plan\n"
        "📓 /mynotes   — Your saved 👍 answers\n"
        "💡 /tip       — Study tip of the day\n"
        "🤯 /fact      — Mind-blowing fact\n"
        "😂 /joke      — Hear a joke\n"
        "💪 /motivate  — Personal motivation boost\n"
        "📖 /define    — Dictionary for any word\n"
        "🌐 /translate — Translate any text\n"
        "📋 /summarize — Summary of a topic\n"
        "🔍 /search    — Real-time web search\n"
        "🗑️ /clear     — Reset chat history\n"
        "ℹ️ /about     — About the bot\n"
        "🏓 /ping      — Check bot response speed\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    question = update.message.text.partition(" ")[2].strip()
    if not question:
        await send(update, "❓Write your Question too!\n📝 Example: /ask  What is the first law of Newton?")
        return
    await process_ask(update, question)


async def brainy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    question = update.message.text.partition(" ")[2].strip()
    if not question:
        await send(update, "🧠 Write the topic or question!\n📝 Example: /brainy Explain photosynthesis")
        return
    await process_brainy(update, question)


async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    if update.message.photo or (update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith("image/")):
        await handle_image(update, context)
    else:
        if is_group(update):
            await send(update,
                "📷 Use /image command with an image!\n\n"
                "→ Send the image\n"
                "→ Write image question as caption\n\n"
                "📝 Example: Image attach + caption: /image Solve this numerical"
            )
        else:
            await send(update,
                "📷 Just send an image with a question as the caption in private chat!\n\n"
                "💡 Attach the image and write your question in the caption."
            )


async def roast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await send(update, "🔒 This command is reserved for the bot owner only!")
        return
    args = update.message.text.partition(" ")[2].strip()
    if not args:
        await send(update, "🎯Who do you want to roast? Example: /roast @username or /roast Rahul")
        return
    target_name = args.lstrip("@")
    if update.message.reply_to_message:
        reply_user = update.message.reply_to_message.from_user
        target_name = reply_user.first_name or target_name
    loading_msg = await update.message.reply_text("🔥 Thinking .  ")
    roast_prompt = (
        f"Target: {target_name}\n\n"
        f"Destroy them with the most savage creative roast. Address by name. Make it legendary. "
        f"6-8 lines. Build up to devastating kill shot at end."
    )
    loop = asyncio.get_event_loop()
    ai_task = loop.run_in_executor(None, lambda: ai_call([{"role": "user", "content": roast_prompt}], ROAST_COMMAND_PROMPT, 400))
    try:
        dot = 0
        while not ai_task.done():
            await safe_edit(loading_msg, THINKING_DOTS[dot % 3])
            dot += 1
            await asyncio.sleep(0.4)
        roast_text = await ai_task
        roast_text = clean_response(roast_text)
        await loading_msg.delete()
        await send(update, f"🔥 𝗕𝗥𝗔𝗜𝗡𝗬 𝗥𝗢𝗔𝗦𝗧𝗦 {target_name.upper()}\n\n{roast_text}")
        print(f"Roast delivered for: {target_name}")
    except Exception as e:
        logger.error(f"Roast error: {e}")
        await loading_msg.delete()
        await send(update, "❌ Roast not generated!")


async def tip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Daily study/productivity tip"""
    if await maintenance_guard(update):
        return
    prompt = "Give one powerful study or productivity tip for a JEE/NEET/CET student. Make it practical and actionable."
    try:
        tip = ai_call([{"role": "user", "content": prompt}], TIP_SYSTEM_PROMPT, 250)
        tip = clean_response(tip)
        await send(update, f"💡 𝗧𝗶𝗽 𝗼𝗳 𝘁𝗵𝗲 𝗗𝗮𝘆:\n\n{tip}")
    except Exception as e:
        logger.error(f"Tip error: {e}")
        await send(update, "❌ Tip not generated!")


async def fact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Random mind-blowing fact"""
    if await maintenance_guard(update):
        return
    categories = ["science", "space", "human body", "history", "technology and AI", "mathematics", "psychology"]
    category = random.choice(categories)
    prompt = f"Give one mind-blowing lesser-known fact about {category}."
    try:
        fact = ai_call([{"role": "user", "content": prompt}], FACT_SYSTEM_PROMPT, 200)
        fact = clean_response(fact)
        await send(update, f"🤯 𝗠𝗶𝗻𝗱-𝗕𝗹𝗼𝘄𝗶𝗻𝗴 𝗙𝗮𝗰𝘁:\n\n{fact}")
    except Exception as e:
        logger.error(f"Fact error: {e}")
        await send(update, "❌ Fact not generated!")


async def joke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Random funny joke"""
    if await maintenance_guard(update):
        return
    prompt = "Tell one genuinely funny joke — preferably a science, programming, or Hinglish wordplay joke."
    try:
        joke = ai_call([{"role": "user", "content": prompt}], JOKE_SYSTEM_PROMPT, 150)
        joke = clean_response(joke)
        await send(update, f"😂 𝗝𝗼𝗸𝗲 𝗧𝗶𝗺𝗲:\n\n{joke}")
    except Exception as e:
        logger.error(f"Joke error: {e}")
        await send(update, "❌ Joke not generated. Check your life, joke isn't working! 😂")


async def summarize_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Summarize any topic"""
    if await maintenance_guard(update):
        return
    topic = update.message.text.partition(" ")[2].strip()
    if not topic:
        await send(update, "📋 Write the topic!\n📝 Example: /summarize Photosynthesis\n/summarize Newton's Laws of Motion")
        return
    prompt = f"Summarize this topic clearly and concisely for a student: {topic}"
    try:
        summary = ai_call([{"role": "user", "content": prompt}], SUMMARIZE_SYSTEM_PROMPT, 500)
        await send(update, clean_response(summary))
    except Exception as e:
        logger.error(f"Summarize error: {e}")
        await send(update, "❌ Summary not generated. Try again later!")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Real-time web search via DuckDuckGo"""
    if await maintenance_guard(update):
        return
    query = update.message.text.partition(" ")[2].strip()
    if not query:
        await send(update,
            "🔍 Kya search karun?\n\n"
            "📝 Usage: /search [query]\n\n"
            "Examples:\n"
            "→ /search IPL 2025 winner\n"
            "→ /search latest AI model 2025\n"
            "→ /search today's news India"
        )
        return

    loading_msg = await update.message.reply_text("🔍 ███▒▒▒▒▒▒▒ Searching...")
    scanning_frames = [
        "🔍 ███▒▒▒▒▒▒▒ Scanning web...",
        "🔍 ██████▒▒▒▒ Fetching results...",
        "🔍 ██████████ Processing..."
    ]

    try:
        loop = asyncio.get_event_loop()

        # Step 1: Run web search in executor (non-blocking)
        search_task = loop.run_in_executor(None, lambda: web_search(query, max_results=5))
        dot = 0
        while not search_task.done():
            await safe_edit(loading_msg, scanning_frames[dot % 3])
            dot += 1
            await asyncio.sleep(0.5)
        search_results = await search_task

        # Step 2: Feed search results to AI for a smart, formatted answer
        ai_prompt = (
            f"User ne search kiya: '{query}'\n\n"
            f"Internet se yeh results aaye hain:\n\n"
            f"{search_results}\n\n"
            f"In results ke basis pe ek clear, accurate, engaging answer do Hinglish mein. "
            f"Agar results mein kafi info nahi hai, toh honestly batao. "
            f"NEVER use **asterisks** markdown. Use emojis and → for formatting."
        )

        ai_task = loop.run_in_executor(
            None,
            lambda: ai_call([{"role": "user", "content": ai_prompt}], SEARCH_SYSTEM_PROMPT, 600)
        )
        while not ai_task.done():
            await safe_edit(loading_msg, scanning_frames[dot % 3])
            dot += 1
            await asyncio.sleep(0.5)
        ai_answer = await ai_task
        ai_answer = clean_response(ai_answer)

        await loading_msg.delete()
        await send(update,
            f"🔍 𝗪𝗲𝗯 𝗦𝗲𝗮𝗿𝗰𝗵: {mono(query)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{ai_answer}"
        )
        print(f"Search done for {update.effective_user.id}: {query[:40]}")

    except Exception as e:
        logger.error(f"Search command error: {e}")
        await loading_msg.delete()
        await send(update, f"❌ Search error: {str(e)[:100]}\n\n⏳ Try again in a bit!")


async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MAINTENANCE_MODE
    if not is_owner(update):
        await send(update, "🔒 This command is for the bot owner only!")
        return
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    if MAINTENANCE_MODE:
        await send(update,
            "🔧 Maintenance Mode ON\n"
            "⛔ No user can use the bot right now.\n"
            "🔄 Send /maintenance again to turn it back OFF."
        )
        print("MAINTENANCE MODE: ON")
    else:
        await send(update, "✅ Maintenance Mode OFF\n🚀 Bot is available for everyone again!")
        print("MAINTENANCE MODE: OFF")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    user_id = update.effective_user.id
    user_conversations[user_id] = []
    save_user_memory_async(user_id)   # persist the clear, so it survives a restart too
    await send(update, "🗑️ Conversation cleared!\n💬 Start a fresh topic anytime!")


async def providers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: ping every provider with a tiny test message and report what's actually working."""
    if not is_owner(update):
        await send(update, "🔒 This command is for the bot owner only!")
        return

    test_msg = [{"role": "user", "content": "Reply with only the word OK"}]
    checks = [
        ("Cerebras",    _call_cerebras,    CEREBRAS_API_KEYS),
        ("Groq",        _call_groq,        GROQ_API_KEYS),
        ("Gemini",      _call_gemini,      GEMINI_API_KEYS),
        ("Deepseek",    _call_deepseek,    DEEPSEEK_API_KEYS),
        ("OpenRouter",  _call_openrouter,  OPENROUTER_API_KEYS),
        ("SambaNova",   _call_sambanova,   SAMBANOVA_API_KEYS),
        ("Together",    _call_together,    TOGETHER_API_KEYS),
        ("Nvidia",      _call_nvidia,      NVIDIA_API_KEYS),
    ]

    status_msg = await update.message.reply_text("🔍 Testing all providers, one sec...")
    lines = ["🩺 Provider Health Check\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
    for name, fn, keys in checks:
        if not keys:
            lines.append(f"⚪ {name}: no key configured")
            continue
        start = datetime.now()
        try:
            result, _truncated = fn(test_msg, "You are a test bot.", 60)
            ms = int((datetime.now() - start).total_seconds() * 1000)
            preview = (result or "").strip()[:30]
            lines.append(f"✅ {name}: working ({ms}ms) → \"{preview}\"")
        except Exception as e:
            err = str(e)
            if "NO_KEYS" in err:
                lines.append(f"⛔ {name}: keys exhausted/invalid/rate-limited")
            else:
                lines.append(f"❌ {name}: {err[:90]}")
    try:
        await status_msg.edit_text("\n".join(lines))
    except Exception:
        await send(update, "\n".join(lines))


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: /broadcast <message> — sends a message to every user/group stored in Supabase.
    Asks for confirmation first since this can't be undone, then sends with a small delay
    between messages (Telegram rate-limits bulk sends) and auto-removes dead chats."""
    if not is_owner(update):
        await send(update, "🔒 This command is for the bot owner only!")
        return

    if not (SUPABASE_URL and SUPABASE_KEY):
        await send(update,
            "⚠️ Supabase configure nahi hai abhi.\n"
            "SUPABASE_URL aur SUPABASE_SERVICE_KEY env variables set karo Railway mein, "
            "phir bot restart karke try karo."
        )
        return

    text = " ".join(context.args) if context.args else ""
    if not text.strip():
        await send(update,
            "📢 𝗨𝘀𝗮𝗴𝗲:\n/broadcast <your message>\n\n"
            "Example:\n/broadcast Naya feature aa gaya hai! /quiz try karo 🔥"
        )
        return

    users = supabase_get_all_users()
    if not users:
        await send(update, "⚠️ Koi registered user nahi mila Supabase mein abhi tak.")
        return

    context.user_data["pending_broadcast"] = text
    await send(update,
        f"📢 𝗖𝗼𝗻𝗳𝗶𝗿𝗺 𝗕𝗿𝗼𝗮𝗱𝗰𝗮𝘀𝘁\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Recipients: {len(users)}\n\n"
        f"📝 Message preview:\n{text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Confirm bhejne ke liye: /confirmbroadcast\n"
        f"❌ Cancel karne ke liye: kuch bhi aur type karo"
    )


async def confirm_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await send(update, "🔒 This command is for the bot owner only!")
        return

    text = context.user_data.get("pending_broadcast")
    if not text:
        await send(update, "⚠️ Koi pending broadcast nahi hai. Pehle /broadcast <message> bhejo.")
        return

    users = supabase_get_all_users()
    status_msg = await update.message.reply_text(f"📤 Sending to {len(users)} chats, ek second...")

    sent, failed = 0, 0
    for u in users:
        chat_id = u.get("chat_id")
        if not chat_id:
            continue
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
            sent += 1
        except Exception as e:
            failed += 1
            err = str(e).lower()
            if any(w in err for w in ["blocked", "deactivated", "not found", "kicked", "chat not found"]):
                supabase_remove_user(chat_id)
        await asyncio.sleep(0.05)  # ~20 msgs/sec, stays under Telegram's bulk-send limits

    context.user_data["pending_broadcast"] = None
    try:
        await status_msg.edit_text(
            f"✅ Broadcast complete!\n"
            f"📨 Sent: {sent}\n"
            f"❌ Failed/removed: {failed}"
        )
    except Exception:
        await send(update, f"✅ Broadcast complete!\n📨 Sent: {sent}\n❌ Failed/removed: {failed}")


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    await send(update,
        "ℹ️ 𝗔𝗯𝗼𝘂𝘁 𝗕𝗥𝗔𝗜𝗡𝗬 𝘃𝟳\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 𝗪𝗵𝗮𝘁 𝗜 𝗮𝗺:\n"
        "→ Multi-provider AI Study Bot\n"
        "→ Built for CET / JEE / NEET students\n"
        "→ Works in private chat + groups\n\n"
        "🧠 𝗔𝗜 𝗘𝗻𝗴𝗶𝗻𝗲:\n"
        "→ Smart routing across 8 AI providers\n"
        "→ Best provider auto-selected per question type\n"
        "→ Vision AI for image analysis\n"
        "→ Persistent memory (history survives restarts)\n"
        "→ Learns from your 👍 liked answers\n\n"
        "⚡ 𝗙𝗲𝗮𝘁𝘂𝗿𝗲𝘀:\n"
        "→ Step-by-step numericals\n"
        "→ MCQ quiz with tap-to-answer buttons\n"
        "→ Formula sheets by subject\n"
        "→ Image question solving\n"
        "→ Study tips, facts, jokes\n"
        "→ Topic summaries\n"
        "→ Real-time web search\n"
        "→ 5-angle deep dives (/ask5)\n"
        "→ Personalized 7-day study plan\n"
        "→ Saved notes from your 👍 answers\n"
        "→ Translation & word definitions\n"
        "→ Personalized motivation\n"
        "→ Level-based adaptive answers\n\n"
        "📊 𝗦𝘁𝗮𝘁𝘀:\n"
        "→ Speed: 1-3 second replies\n"
        "→ Message limit: Zero\n"
        "→ Cost to you: Free\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👨‍💻 𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿: Shreyansh Pathak\n"
        "🔗 @shreyanshhh_08\n"
        "📢 Channel: @aurabreaker7"
    )


async def level_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    if is_group(update):
        await send(update, "🎯 Come to a private chat to set your level!")
        return
    keyboard = [["1️⃣ Class 11", "2️⃣ Class 12"], ["3️⃣ Dropper"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
        "🎯 Which class are you in?\n"
        "→ Iske hisaab se main answers adjust karunga!\n\n"
        "Select karo:",
        reply_markup=reply_markup
    )
    return CHOOSING_LEVEL


async def level_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    choice   = update.message.text
    data     = get_user_data(user_id)
    if "11" in choice:        data["level"] = "Class 11"
    elif "12" in choice:      data["level"] = "Class 12"
    elif "Dropper" in choice: data["level"] = "Dropper"
    else:                     data["level"] = choice
    await update.message.reply_text(
        f"✅ Level set: 𝗖𝗹𝗮𝘀𝘀 {data['level']}\n"
        f"🧠 I'll tailor my help to that level from now on!",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def level_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    if is_group(update):
        await send(update, "📝 Come to a private chat for quizzes!")
        return
    data  = get_user_data(update.effective_user.id)
    level = data.get("level") or "Class 12"
    await update.message.chat.send_action("typing")
    prompt = (
        f"Ek {level} level ka MCQ question banao — Physics, Chemistry, Math ya Biology mein se.\n"
        "Format:\nQuestion: [question]\nA) [option]\nB) [option]\nC) [option]\nD) [option]\n"
        "Answer: [correct option letter]\nExplanation: [brief explanation]\nPlain text mein."
    )
    try:
        quiz_text = ai_call([{"role": "user", "content": prompt}], QUIZ_SYSTEM_PROMPT, max_tokens=500)
        # Save for BOTH text-reply mode and inline-button mode
        context.user_data["last_quiz"]        = quiz_text
        context.user_data["last_quiz_inline"] = quiz_text
        lines = quiz_text.strip().split("\n")
        q_lines = [l for l in lines if not l.startswith(("Answer:", "Explanation:"))]
        q_lines = [clean_response(l) for l in q_lines]
        question_display = "\n".join(q_lines)
        # Inline A/B/C/D buttons — tap to answer, buttons disappear after
        quiz_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("A", callback_data="fb_quiz_A"),
            InlineKeyboardButton("B", callback_data="fb_quiz_B"),
            InlineKeyboardButton("C", callback_data="fb_quiz_C"),
            InlineKeyboardButton("D", callback_data="fb_quiz_D"),
        ]])
        await update.message.reply_text(
            f"📝 𝗤𝘂𝗶𝘇 𝗧𝗶𝗺𝗲! ⚡\n\n"
            f"{question_display}\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👇 Tap your answer:",
            reply_markup=quiz_keyboard
        )
    except Exception as e:
        logger.error(f"Quiz error: {e}")
        await send(update, "❌ Error generating quiz. Try again!")


async def formula_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    if is_group(update):
        await send(update, "📚 Come to a private chat for formulas!")
        return
    keyboard = [["⚡ Physics", "🧪 Chemistry"], ["📐 Math", "🧬 Biology"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
        "📚 Which subject's formulas do you need?",
        reply_markup=reply_markup
    )
    context.user_data["waiting_for"] = "formula_subject"


async def practice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    if is_group(update):
        await send(update, "🏋️ Come to a private chat for practice questions!")
        return
    data  = get_user_data(update.effective_user.id)
    level = data.get("level") or "Class 12"
    await update.message.chat.send_action("typing")
    prompt = (
        f"Ek {level} level ka exam-style practice question do — CET/JEE/NEET pattern.\n"
        "Numerical ya conceptual koi bhi. Step-by-step solution bhi do. Plain text."
    )
    try:
        text = ai_call([{"role": "user", "content": prompt}], max_tokens=1000)
        text = clean_response(text)
        await send(update, f"🏋️ 𝗣𝗿𝗮𝗰𝘁𝗶𝗰𝗲 𝗤𝘂𝗲𝘀𝘁𝗶𝗼𝗻:\n\n{text}")
    except Exception as e:
        logger.error(f"Practice error: {e}")
        await send(update, "❌ Error generating practice question. Try again!")


async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_guard(update):
        return
    data    = get_user_data(update.effective_user.id)
    total   = data["total"]
    score   = data["score"]
    level   = data.get("level") or "Not set"
    joined  = data.get("joined", "N/A")
    percent = round((score / total * 100)) if total > 0 else 0

    if percent >= 80:
        emoji, remark, bar = "🔥", "Crushing it! Keep it up!", "██████████"
    elif percent >= 60:
        emoji, remark, bar = "⚡", "Going strong — push a bit more!", "████████▒▒"
    elif percent >= 40:
        emoji, remark, bar = "📈", "Average right now — practice more!", "██████▒▒▒▒"
    elif total == 0:
        emoji, remark, bar = "🎯", "Play a quiz to start tracking progress!", "▒▒▒▒▒▒▒▒▒▒"
    else:
        emoji, remark, bar = "💪", "No worries — mistakes are how we learn!", "████▒▒▒▒▒▒"

    liked_count = len(data.get("liked_notes") or [])
    await send(update,
        f"📊 𝗣𝗿𝗼𝗴𝗿𝗲𝘀𝘀 𝗥𝗲𝗽𝗼𝗿𝘁\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Level: {mono(level)}\n"
        f"📅 Member since: {mono(joined)}\n\n"
        f"✅ Correct Answers: {mono(str(score))}\n"
        f"❌ Total Attempts: {mono(str(total))}\n"
        f"📈 Accuracy: {mono(str(percent)+'%')}\n"
        f"Score: {mono('['+bar+']')} {mono(str(percent)+'%')}\n"
        f"👍 Liked answers saved: {mono(str(liked_count))}\n\n"
        f"{emoji} {remark}"
    )


# ── NEW: /translate ─────────────────────────────────────────
async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Translate any text to English/Hindi/Hinglish on demand."""
    if await maintenance_guard(update):
        return
    args = update.message.text.partition(" ")[2].strip()
    if not args:
        await send(update,
            "🌐 Usage: /translate [text]\n\n"
            "Examples:\n"
            "→ /translate Mitochondria is the powerhouse of the cell\n"
            "→ /translate न्यूटन का पहला नियम क्या है?\n\n"
            "I'll detect the language and translate to English + give a Hindi explanation too!"
        )
        return
    prompt = (
        f"Translate and explain this text for a student:\n\"{args}\"\n\n"
        "1. Detect the source language.\n"
        "2. Give English translation (if not English).\n"
        "3. Give a simple Hindi/Hinglish explanation of what it means in a student context.\n"
        "Plain text, no markdown asterisks."
    )
    loading_msg = await update.message.reply_text(THINKING_DOTS[0])
    loop = asyncio.get_event_loop()
    ai_task = loop.run_in_executor(None, lambda: ai_call([{"role": "user", "content": prompt}], max_tokens=400))
    try:
        dot = 1
        while not ai_task.done():
            await safe_edit(loading_msg, THINKING_DOTS[dot % 3])
            dot += 1
            await asyncio.sleep(0.6)
        result = clean_response(await ai_task)
        await loading_msg.edit_text(f"🌐 𝗧𝗿𝗮𝗻𝘀𝗹𝗮𝘁𝗲:\n\n{result}")
    except Exception as e:
        logger.error(f"Translate error: {e}")
        await loading_msg.edit_text("❌ Translation failed. Try again!")


# ── NEW: /define ────────────────────────────────────────────
async def define_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dictionary-style definition + example for any word/concept."""
    if await maintenance_guard(update):
        return
    word = update.message.text.partition(" ")[2].strip()
    if not word:
        await send(update,
            "📖 Usage: /define [word or concept]\n\n"
            "Examples:\n"
            "→ /define entropy\n"
            "→ /define osmosis\n"
            "→ /define photon"
        )
        return
    prompt = (
        f"Give a concise dictionary-style definition of '{word}' for a science student.\n"
        "Include:\n"
        "1. Simple one-line definition\n"
        "2. Subject/field (Physics / Chemistry / Biology / Math / General)\n"
        "3. One real-world example or analogy\n"
        "4. A quick memory trick (if applicable)\n"
        "Plain text. No markdown asterisks."
    )
    loading_msg = await update.message.reply_text(THINKING_DOTS[0])
    loop = asyncio.get_event_loop()
    ai_task = loop.run_in_executor(None, lambda: ai_call([{"role": "user", "content": prompt}], max_tokens=350))
    try:
        dot = 1
        while not ai_task.done():
            await safe_edit(loading_msg, THINKING_DOTS[dot % 3])
            dot += 1
            await asyncio.sleep(0.6)
        result = clean_response(await ai_task)
        await loading_msg.edit_text(f"📖 𝗗𝗲𝗳𝗶𝗻𝗶𝘁𝗶𝗼𝗻 — {mono(word)}:\n\n{result}")
    except Exception as e:
        logger.error(f"Define error: {e}")
        await loading_msg.edit_text("❌ Definition not found. Try again!")


# ── NEW: /motivate ──────────────────────────────────────────
async def motivate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delivers a personalized motivational message for the student."""
    if await maintenance_guard(update):
        return
    user_name = update.effective_user.first_name or "champ"
    data = get_user_data(update.effective_user.id)
    level = data.get("level") or "student"
    total = data.get("total", 0)
    score = data.get("score", 0)

    context_hint = ""
    if total > 0:
        pct = round(score / total * 100)
        if pct < 50:
            context_hint = f"{user_name} is struggling a bit (quiz accuracy: {pct}%), needs encouragement without sugar-coating."
        elif pct >= 80:
            context_hint = f"{user_name} is performing well (accuracy: {pct}%), motivate them to aim even higher."
        else:
            context_hint = f"{user_name} is doing okay (accuracy: {pct}%), push them to level up."

    prompt = (
        f"Give a short, powerful motivational message for {user_name}, a {level} student preparing for competitive exams.\n"
        f"{context_hint}\n"
        "Make it punchy, real, personal — not generic quotes. Mix English + Hinglish. 5-7 lines max."
    )
    loading_msg = await update.message.reply_text("💪 Loading motivation...")
    loop = asyncio.get_event_loop()
    ai_task = loop.run_in_executor(None, lambda: ai_call([{"role": "user", "content": prompt}], max_tokens=250))
    try:
        dot = 1
        while not ai_task.done():
            await safe_edit(loading_msg, THINKING_DOTS[dot % 3])
            dot += 1
            await asyncio.sleep(0.5)
        result = clean_response(await ai_task)
        await loading_msg.edit_text(f"💪 𝗠𝗼𝘁𝗶𝘃𝗮𝘁𝗶𝗼𝗻 𝗳𝗼𝗿 {user_name}:\n\n{result}")
    except Exception as e:
        logger.error(f"Motivate error: {e}")
        await loading_msg.edit_text("❌ Failed to load motivation. You got this though 💪")


# ── NEW: /mynotes ───────────────────────────────────────────
async def mynotes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows all the answers the user has 👍'd — their personal saved notes."""
    if await maintenance_guard(update):
        return
    user_id = update.effective_user.id
    load_user_into_memory(user_id, update.effective_user.first_name or "", update.effective_user.username or "")
    data = get_user_data(user_id)
    notes = data.get("liked_notes") or []
    if not notes:
        await send(update,
            "📓 𝗬𝗼𝘂𝗿 𝗡𝗼𝘁𝗲𝘀 𝗮𝗿𝗲 𝗲𝗺𝗽𝘁𝘆!\n\n"
            "When I answer your question, tap the 👍 button to save it here as a personal note.\n"
            "I'll also remember what style/topics you liked for future answers!"
        )
        return
    lines = [f"📓 𝗬𝗼𝘂𝗿 𝗦𝗮𝘃𝗲𝗱 𝗡𝗼𝘁𝗲𝘀 ({len(notes)} entries)\n━━━━━━━━━━━━━━━━━━━━━━━━\n"]
    for i, note in enumerate(notes[-10:], 1):   # show last 10
        lines.append(f"{i}. {note[:200]}")
    lines.append("\n💡 Tap 👍 on any answer to save it here!")
    await send(update, "\n\n".join(lines))


# ── NEW: /myplan ────────────────────────────────────────────
async def myplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates a personalized 7-day study plan based on user's level."""
    if await maintenance_guard(update):
        return
    if is_group(update):
        await send(update, "📅 Come to a private chat for your personalized plan!")
        return
    user_id   = update.effective_user.id
    user_name = update.effective_user.first_name or "Student"
    data      = get_user_data(user_id)
    level     = data.get("level") or "Class 12"
    subject   = update.message.text.partition(" ")[2].strip() or None

    subject_hint = f"Focus on: {subject}." if subject else "Cover all subjects: Physics, Chemistry, Math, Biology."
    prompt = (
        f"Create a realistic 7-day study plan for {user_name}, a {level} student preparing for CET/JEE/NEET.\n"
        f"{subject_hint}\n"
        "Each day: morning + evening sessions, specific topics, and one revision task.\n"
        "Keep it practical — not overwhelming. Hinglish tone. Plain text, no markdown."
    )
    loading_msg = await update.message.reply_text(THINKING_DOTS[0])
    loop = asyncio.get_event_loop()
    ai_task = loop.run_in_executor(None, lambda: ai_call([{"role": "user", "content": prompt}], max_tokens=1000))
    try:
        dot = 1
        while not ai_task.done():
            await safe_edit(loading_msg, THINKING_DOTS[dot % 3])
            dot += 1
            await asyncio.sleep(0.6)
        result = clean_response(await ai_task)
        await loading_msg.delete()
        await send(update, f"📅 𝗬𝗼𝘂𝗿 𝟕-𝗗𝗮𝘆 𝗦𝘁𝘂𝗱𝘆 𝗣𝗹𝗮𝗻:\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n{result}")
    except Exception as e:
        logger.error(f"Plan error: {e}")
        try:
            await loading_msg.edit_text("❌ Plan generation failed. Try again!")
        except Exception:
            pass


# ── NEW: /stats (owner-only) ────────────────────────────────
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Live bot stats — active users, total interactions, provider keys, etc."""
    if not is_owner(update):
        await send(update, "🔒 Owner only!")
        return
    total_users_db    = supabase_user_count()
    active_session    = len(user_conversations)
    total_interactions = len(interaction_log)
    keys_summary = (
        f"Groq:{len(GROQ_API_KEYS)} Gemini:{len(GEMINI_API_KEYS)} "
        f"Deepseek:{len(DEEPSEEK_API_KEYS)} Cerebras:{len(CEREBRAS_API_KEYS)}\n"
        f"OpenRouter:{len(OPENROUTER_API_KEYS)} SambaNova:{len(SAMBANOVA_API_KEYS)} "
        f"Together:{len(TOGETHER_API_KEYS)} Nvidia:{len(NVIDIA_API_KEYS)} "
        f"Tavily:{len(TAVILY_API_KEYS)}"
    )
    feedback_pending = len(pending_feedback)
    await send(update,
        f"📊 𝗟𝗶𝘃𝗲 𝗕𝗼𝘁 𝗦𝘁𝗮𝘁𝘀\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Total users (Supabase): {mono(str(total_users_db))}\n"
        f"🟢 Active sessions (RAM):  {mono(str(active_session))}\n"
        f"💬 Interactions logged:    {mono(str(total_interactions))}\n"
        f"⏳ Pending feedback items: {mono(str(feedback_pending))}\n"
        f"🔧 Maintenance mode: {'ON 🔴' if MAINTENANCE_MODE else 'OFF 🟢'}\n\n"
        f"🔑 API Keys:\n{keys_summary}"
    )


# ── NEW: /ask5 ───────────────────────────────────────────────
async def ask5_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Answers a question using 5 different AI perspectives / approaches."""
    if await maintenance_guard(update):
        return
    question = update.message.text.partition(" ")[2].strip()
    if not question:
        await send(update,
            "🧠 Usage: /ask5 [question]\n\n"
            "Gets 5 different angles/explanations for the same concept.\n"
            "Example: /ask5 What is entropy?"
        )
        return
    prompt = (
        f"Answer this question from 5 different angles/approaches, each clearly labeled:\n\"{question}\"\n\n"
        "1. Simple (beginner-friendly, with analogy)\n"
        "2. Technical (precise scientific definition)\n"
        "3. Exam angle (what JEE/NEET/CET would ask)\n"
        "4. Real-world application (where you see this in daily life)\n"
        "5. Memory trick (how to never forget this)\n\n"
        "Hinglish tone. Plain text, no markdown asterisks."
    )
    await _run_ai(update, [{"role": "user", "content": prompt}], BRAINY_SYSTEM_PROMPT, 1200, source="ask5")



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   INLINE BUTTON CALLBACK HANDLER (👍 / 👎 + quiz inline)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles ALL inline keyboard button presses.
    — 👍 / 👎 feedback: removes the buttons instantly, logs/saves the feedback.
    — Any other data: ignored (safe fallback).
    """
    query = update.callback_query
    if not query:
        return

    # Always acknowledge to Telegram first (stops the loading spinner on the button)
    await query.answer()

    data     = query.data or ""
    user_id  = query.from_user.id if query.from_user else None
    msg_id   = query.message.message_id if query.message else None

    # ── 👍 / 👎 feedback ─────────────────────────────────────
    if data in ("fb_up", "fb_down"):
        # Remove the buttons immediately — one-shot interaction
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as e:
            # "Message is not modified" is fine; anything else log & continue
            if "not modified" not in str(e).lower():
                logger.warning(f"Could not remove feedback buttons: {e}")

        target = pending_feedback.get(msg_id) if msg_id else None

        if data == "fb_up" and target and user_id == target.get("user_id"):
            # Save the liked answer into the user's personal liked_notes for future context
            user_store = user_data_store.get(user_id, {})
            liked = user_store.setdefault("liked_notes", [])
            note  = f"Q: {target['question'][:100]} | A: {target['answer'][:200]}"
            if note not in liked:
                liked.append(note)
            # Cap at MAX_LIKED_NOTES
            if len(liked) > MAX_LIKED_NOTES:
                user_store["liked_notes"] = liked[-MAX_LIKED_NOTES:]
            save_user_memory_async(user_id)
            # Save to shared interaction log too
            save_interaction(user_id, target["question"], target["answer"], "feedback_liked")
            print(f"👍 from {user_id} on msg {msg_id}")

        elif data == "fb_down" and target and user_id == target.get("user_id"):
            print(f"👎 from {user_id} on msg {msg_id}")

        # Clean up memory regardless
        if msg_id and msg_id in pending_feedback:
            del pending_feedback[msg_id]

        return

    # ── Inline quiz answer buttons (fb_quiz_A / fb_quiz_B etc.) ──
    if data.startswith("fb_quiz_"):
        chosen = data.replace("fb_quiz_", "").upper()
        last_quiz = context.user_data.get("last_quiz_inline")
        if not last_quiz:
            await query.answer("⚠️ Quiz expired — send /quiz for a new one!", show_alert=True)
            return
        correct_ans = ""
        explanation = ""
        for line in last_quiz.split("\n"):
            if line.startswith("Answer:"):
                correct_ans = line.replace("Answer:", "").strip().upper()
            if line.startswith("Explanation:"):
                explanation = clean_response(line.replace("Explanation:", "").strip())
        user_store = user_data_store.get(user_id, {})
        user_store.setdefault("score", 0)
        user_store.setdefault("total", 0)
        user_store["total"] += 1
        if correct_ans and chosen == correct_ans[0]:
            user_store["score"] += 1
            result_text = (
                f"✅ 𝗖𝗼𝗿𝗿𝗲𝗰𝘁! 🎉\n\n"
                f"💡 {explanation}\n\n"
                f"📊 Score: {user_store['score']}/{user_store['total']}"
            )
        else:
            result_text = (
                f"❌ 𝗪𝗿𝗼𝗻𝗴!\n\n"
                f"✅ Correct answer: {correct_ans}\n"
                f"💡 {explanation}\n\n"
                f"📊 Score: {user_store['score']}/{user_store['total']}\n"
                f"💪 Mistakes = learning!"
            )
        # Remove buttons and update the quiz message with the result
        try:
            original_text = query.message.text or ""
            await query.edit_message_text(
                text=original_text + "\n\n" + result_text,
                reply_markup=None
            )
        except Exception:
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            if query.message:
                await query.message.reply_text(result_text)
        context.user_data.pop("last_quiz_inline", None)
        save_user_memory_async(user_id)
        return


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   MESSAGE HANDLER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_registered_chats_cache = set()  # avoids hitting Supabase on every single message

def _maybe_register_chat(update: Update) -> None:
    """Registers a chat in Supabase at most once per bot process run — keeps it cheap."""
    chat = update.effective_chat
    if not chat or chat.id in _registered_chats_cache:
        return
    _registered_chats_cache.add(chat.id)
    if chat.type == "private":
        u = update.effective_user
        supabase_register_user(chat.id, "private", (u.username if u else "") or "", (u.first_name if u else "") or "")
    else:
        supabase_register_user(chat.id, "group", chat.title or "", "")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    msg_text = msg.text or ""
    _maybe_register_chat(update)

    # ── GROUP HANDLING ──────────────────────────────────────
    if is_group(update):
        # During maintenance: complete silence, ignore everything including tags/replies
        if MAINTENANCE_MODE and not is_owner(update):
            return

        # Abuse check always runs
        if is_abusing_owner(msg_text):
            await roast_abuser(update)
            return

        # Check if bot is tagged (@mention)
        bot_username = (await context.bot.get_me()).username
        bot_mentioned = f"@{bot_username}".lower() in msg_text.lower()

        # Check if user replied to a bot message (left swipe reply)
        replied_to_bot = (
            msg.reply_to_message is not None
            and msg.reply_to_message.from_user is not None
            and msg.reply_to_message.from_user.username == bot_username
        )

        if bot_mentioned:
            # Strip the @mention and answer using user's history
            question = msg_text.replace(f"@{bot_username}", "").replace(f"@{bot_username.lower()}", "").strip()
            if question:
                await msg.chat.send_action("typing")
                await process_query(update, question)
        elif replied_to_bot:
            # User replied to bot without tagging — answer using their history
            if msg_text.strip():
                await msg.chat.send_action("typing")
                await process_query(update, msg_text.strip())
        return

    # ── PRIVATE CHAT HANDLING ───────────────────────────────
    if await maintenance_guard(update):
        return

    user_id = update.effective_user.id
    # ── Restore from Supabase if first message this session ──
    # (Was previously just blind-initializing user_conversations[user_id] = [] here,
    # which made load_user_into_memory's "already loaded" guard skip restoring real
    # history forever in this process — saved context never came back after a restart.)
    load_user_into_memory(user_id, update.effective_user.first_name or "", update.effective_user.username or "")
    data = get_user_data(user_id)

    # Formula subject selection
    if context.user_data.get("waiting_for") == "formula_subject":
        context.user_data.pop("waiting_for")
        subject_map = {
            "Physics": "Physics", "Chemistry": "Chemistry",
            "Math": "Math", "Biology": "Biology"
        }
        subject = next((v for k, v in subject_map.items() if k in msg_text), msg_text)
        await msg.chat.send_action("typing")
        prompt = (
            f"{subject} ki important formulas list karo — CET/JEE/NEET ke liye.\n"
            "Har formula ke saath ek line mein kya represent karta hai. Plain text."
        )
        try:
            formulas = ai_call([{"role": "user", "content": prompt}], max_tokens=1200)
            formulas = clean_response(formulas)
            await send(update, f"📚 𝗙𝗼𝗿𝗺𝘂𝗹𝗮𝘀 — {mono(subject)}:\n\n{formulas}")
        except Exception as e:
            logger.error(f"Formula error: {e}")
            await send(update, "❌ Error fetching formulas. Try again!")
        return

    # Quiz answer check
    last_quiz = context.user_data.get("last_quiz")
    if last_quiz and msg_text.strip().upper() in ["A", "B", "C", "D"]:
        user_ans = msg_text.strip().upper()
        correct_ans = explanation = ""
        for line in last_quiz.split("\n"):
            if line.startswith("Answer:"):
                correct_ans = line.replace("Answer:", "").strip().upper()
            if line.startswith("Explanation:"):
                explanation = clean_response(line.replace("Explanation:", "").strip())
        data["total"] += 1
        if correct_ans and user_ans == correct_ans[0]:
            data["score"] += 1
            result_text = (
                f"✅ 𝗖𝗼𝗿𝗿𝗲𝗰𝘁! 🎉\n\n"
                f"💡 Explanation: {explanation}\n\n"
                f"📊 Score: {data['score']}/{data['total']}"
            )
        else:
            result_text = (
                f"❌ 𝗪𝗿𝗼𝗻𝗴!\n\n"
                f"✅ Correct answer: {correct_ans}\n\n"
                f"💡 Explanation: {explanation}\n\n"
                f"📊 Score: {data['score']}/{data['total']}\n\n"
                f"💪 No worries — mistakes are how we learn!"
            )
        context.user_data.pop("last_quiz")
        await send(update, result_text)
        return

    # Check if user replied to a bot message in private (left swipe reply)
    if msg.reply_to_message and msg.reply_to_message.from_user:
        bot_info = await context.bot.get_me()
        if msg.reply_to_message.from_user.id == bot_info.id:
            # Treat as normal query with existing history context
            print(f"Reply-to-bot from {user_id}: {msg_text[:50]}...")
            await process_query(update, msg_text)
            return

    # Normal private chat — fire "typing" indicator instantly before any AI work
    print(f"Message from {user_id}: {msg_text[:50]}...")
    await msg.chat.send_action("typing")
    await process_query(update, msg_text)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   ERROR HANDLER & MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

async def post_init(application: Application) -> None:
    await application.bot.delete_webhook(drop_pending_updates=True)
    print("Old sessions cleared! Starting fresh...")


def main():
    print("=" * 55)
    print("  ⚡ BRAINY Study Bot v7.0 Starting...  ")
    print("  🧠 Cerebras + Groq + Gemini + DeepSeek + OpenRouter ")
    print("  🔍 Tavily Search | Inline Quiz | Feedback Fix | /ask5 ")
    print("=" * 55)

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

    # Register handlers
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("help",        help_command))
    app.add_handler(CommandHandler("ask",         ask_command))
    app.add_handler(CommandHandler("brainy",      brainy_command))
    app.add_handler(CommandHandler("image",       image_command))
    app.add_handler(CommandHandler("roast",       roast_command))
    app.add_handler(CommandHandler("maintenance", maintenance_command))
    app.add_handler(CommandHandler("providers",   providers_command))
    app.add_handler(CommandHandler("broadcast",        broadcast_command))
    app.add_handler(CommandHandler("confirmbroadcast", confirm_broadcast_command))
    app.add_handler(CommandHandler("clear",       clear_command))
    app.add_handler(CommandHandler("about",       about_command))
    app.add_handler(CommandHandler("ping",        ping_command))
    app.add_handler(CommandHandler("quiz",        quiz_command))
    app.add_handler(CommandHandler("formula",     formula_command))
    app.add_handler(CommandHandler("practice",    practice_command))
    app.add_handler(CommandHandler("progress",    progress_command))
    app.add_handler(CommandHandler("tip",         tip_command))
    app.add_handler(CommandHandler("fact",        fact_command))
    app.add_handler(CommandHandler("joke",        joke_command))
    app.add_handler(CommandHandler("summarize",   summarize_command))
    app.add_handler(CommandHandler("search",      search_command))
    app.add_handler(CommandHandler("translate",   translate_command))
    app.add_handler(CommandHandler("define",      define_command))
    app.add_handler(CommandHandler("motivate",    motivate_command))
    app.add_handler(CommandHandler("mynotes",     mynotes_command))
    app.add_handler(CommandHandler("myplan",      myplan_command))
    app.add_handler(CommandHandler("stats",       stats_command))
    app.add_handler(CommandHandler("ask5",        ask5_command))
    app.add_handler(level_handler)

    # Inline button callbacks (👍 / 👎 feedback, quiz inline buttons, etc.)
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    app.add_handler(MessageHandler(
        filters.PHOTO | filters.Document.IMAGE,
        handle_image
    ))

    # Handle all text messages (private + group — handle_message does the routing)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))

    app.add_error_handler(error_handler)

    print("✅ Bot is running... Press Ctrl+C to stop")
    print("=" * 55)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
