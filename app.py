import os
import uuid
import hmac
import hashlib
import json
import urllib.parse
import random
import requests
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory

# Import AI + Supabase helpers from study_bot (same Supabase project the Telegram bot uses)
import study_bot

# Security module — input sanitization, rate limiting, blacklist, headers
from security import (
    security_guard, login_required, sanitize_input,
    is_blacklisted, check_rate_limit, log_security_event, security_headers
)

app = Flask(__name__)
# IMPORTANT: set a real FLASK_SECRET_KEY env var on Railway. This key signs the session
# cookie. The cookie only ever holds a user_id — never a password or token — and Flask
# marks it HttpOnly by default, so it can't be read by page JS or stashed in
# localStorage/sessionStorage. Nothing is stored in browser cache beyond that one signed
# cookie, and it's useless without the secret key living on the server.
app.secret_key = os.getenv("FLASK_SECRET_KEY", "brainy_secret_super_key_123")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = 86400  # 24 hours

@app.after_request
def apply_security_headers(response):
    return security_headers(response)

SUPABASE_URL = study_bot.SUPABASE_URL
SUPABASE_KEY = study_bot.SUPABASE_KEY
MESSAGE_LIMIT = 50

# In-memory browser auth handshake sessions (short-lived, just for the login flow):
# { session_id: { "status": "pending"|"authenticated", "user": { ... } } }
auth_sessions = {}


# ── SUPABASE HELPERS (chat_sessions / chat_messages) ──

def _sb_headers(prefer: str | None = None) -> dict:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def sb_list_sessions(user_id: int) -> list:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/chat_sessions"
        f"?user_id=eq.{user_id}&select=id,title,created_at&order=created_at.desc",
        headers=_sb_headers(), timeout=10
    )
    r.raise_for_status()
    return r.json()


def sb_create_session(user_id: int, title: str) -> dict:
    session_id = str(uuid.uuid4())
    payload = {"id": session_id, "user_id": user_id, "title": title}
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/chat_sessions",
        headers=_sb_headers("return=representation"), json=payload, timeout=10
    )
    r.raise_for_status()
    return r.json()[0]


def sb_get_session(session_id: str, user_id: int) -> dict | None:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/chat_sessions"
        f"?id=eq.{session_id}&user_id=eq.{user_id}&select=id,title",
        headers=_sb_headers(), timeout=10
    )
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


def sb_rename_session(session_id: str, user_id: int, title: str) -> None:
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/chat_sessions?id=eq.{session_id}&user_id=eq.{user_id}",
        headers=_sb_headers(), json={"title": title}, timeout=10
    )


def sb_delete_session(session_id: str, user_id: int) -> None:
    # chat_messages has ON DELETE CASCADE on session_id, so this wipes the messages too.
    requests.delete(
        f"{SUPABASE_URL}/rest/v1/chat_sessions?id=eq.{session_id}&user_id=eq.{user_id}",
        headers=_sb_headers(), timeout=10
    )


def sb_get_messages(session_id: str) -> list:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/chat_messages"
        f"?session_id=eq.{session_id}&select=role,content&order=id.asc",
        headers=_sb_headers(), timeout=10
    )
    r.raise_for_status()
    return r.json()


def sb_get_recent_messages(session_id: str, limit: int = 15) -> list:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/chat_messages"
        f"?session_id=eq.{session_id}&select=role,content&order=id.desc&limit={limit}",
        headers=_sb_headers(), timeout=10
    )
    r.raise_for_status()
    return list(reversed(r.json()))


def sb_insert_message(session_id: str, role: str, content: str) -> None:
    payload = {"session_id": session_id, "role": role, "content": content}
    requests.post(
        f"{SUPABASE_URL}/rest/v1/chat_messages",
        headers=_sb_headers("return=minimal"), json=payload, timeout=10
    )


def sb_count_user_messages(session_id: str) -> int:
    headers = _sb_headers()
    headers["Prefer"] = "count=exact"
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/chat_messages"
        f"?session_id=eq.{session_id}&role=eq.user&select=id",
        headers=headers, timeout=10
    )
    content_range = r.headers.get("content-range", "")
    if "/" in content_range:
        try:
            return int(content_range.split("/")[-1])
        except ValueError:
            return 0
    return 0


def verify_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data))
        if "hash" not in parsed:
            return None
        hash_value = parsed.pop("hash")

        sorted_pairs = sorted([f"{k}={v}" for k, v in parsed.items()])
        data_check_string = "\n".join(sorted_pairs)

        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if computed_hash == hash_value:
            user_data = json.loads(parsed.get("user", "{}"))
            return user_data
    except Exception as e:
        print(f"Error verifying initData: {e}")
    return None


# Serve the single merged index.html (HTML + CSS + JS all in one file).
# Lives right next to app.py — no templates/ subfolder needed.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


# ── AUTHENTICATION APIS ──

@app.route("/api/auth/init", methods=["POST"])
def auth_init():
    session_id = str(uuid.uuid4())
    auth_sessions[session_id] = {"status": "pending", "user": None}
    bot_username = "AiChatExpert_Bot"
    return jsonify({
        "session_id": session_id,
        "bot_url": f"https://t.me/{bot_username}?start=sess_{session_id}"
    })


@app.route("/api/auth/status/<session_id>", methods=["GET"])
def auth_status(session_id):
    sess = auth_sessions.get(session_id)
    if not sess:
        return jsonify({"status": "not_found"}), 404

    if sess["status"] == "authenticated":
        user = sess["user"]
        session["user_id"] = user["id"]
        session["first_name"] = user["first_name"]
        session["username"] = user.get("username", "")
        auth_sessions.pop(session_id, None)
        return jsonify({"status": "authenticated", "user": user})

    return jsonify({"status": "pending"})


@app.route("/api/auth/verify", methods=["GET"])
def auth_verify():
    session_id = request.args.get("session_id")
    user_id = request.args.get("user_id")
    first_name = request.args.get("first_name", "")
    username = request.args.get("username", "")

    if not session_id or not user_id:
        return "❌ Missing session_id or user_id", 400

    if session_id in auth_sessions:
        auth_sessions[session_id] = {
            "status": "authenticated",
            "user": {"id": int(user_id), "first_name": first_name, "username": username}
        }
        return """
        <html>
            <head>
                <title>Login Successful</title>
                <style>
                    body {
                        background-color: #0d1117; color: #c9d1d9;
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
                        display: flex; flex-direction: column; align-items: center; justify-content: center;
                        height: 100vh; margin: 0;
                    }
                    .card {
                        background: rgba(22, 27, 34, 0.8); border: 1px solid #30363d; border-radius: 12px;
                        padding: 30px; text-align: center; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
                        backdrop-filter: blur(4px);
                    }
                    h1 { color: #58a6ff; font-size: 24px; margin-bottom: 10px; }
                    p { font-size: 16px; margin-bottom: 20px; }
                    .success-icon { font-size: 48px; margin-bottom: 15px; }
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="success-icon">🔓</div>
                    <h1>Login Authorized</h1>
                    <p>Verification successful! You can now close this window and return to your chat page.</p>
                </div>
            </body>
        </html>
        """
    return "❌ Invalid or expired session ID", 400


@app.route("/api/auth/initdata", methods=["POST"])
def auth_initdata():
    data = request.json or {}
    init_data = data.get("initData")
    if not init_data:
        return jsonify({"error": "initData missing"}), 400

    user_data = verify_telegram_init_data(init_data, study_bot.TELEGRAM_TOKEN)
    if user_data:
        session["user_id"] = user_data["id"]
        session["first_name"] = user_data["first_name"]
        session["username"] = user_data.get("username", "")
        return jsonify({"status": "authenticated", "user": user_data})
    return jsonify({"error": "Invalid signature"}), 401


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"status": "logged_out"})


# login_required and security_guard are imported from security.py


# ── CHAT SESSION APIS ──

@app.route("/api/sessions", methods=["GET"])
@login_required
def get_sessions():
    user_id = session["user_id"]
    try:
        return jsonify(sb_list_sessions(user_id))
    except Exception as e:
        print(f"get_sessions failed: {e}")
        return jsonify({"error": "Could not load sessions"}), 500


@app.route("/api/sessions", methods=["POST"])
@login_required
def create_session():
    user_id = session["user_id"]
    data = request.json or {}
    title = data.get("title", "New Chat")
    try:
        row = sb_create_session(user_id, title)
        return jsonify({"id": row["id"], "title": row["title"]})
    except Exception as e:
        print(f"create_session failed: {e}")
        return jsonify({"error": "Could not create session"}), 500


@app.route("/api/sessions/<session_id>", methods=["PATCH"])
@login_required
def rename_session(session_id):
    user_id = session["user_id"]
    data = request.json or {}
    title = data.get("title")
    if not title:
        return jsonify({"error": "Title required"}), 400
    sb_rename_session(session_id, user_id, title)
    return jsonify({"status": "ok"})


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
@login_required
def delete_session(session_id):
    user_id = session["user_id"]
    sb_delete_session(session_id, user_id)
    return jsonify({"status": "ok"})


@app.route("/api/chat/<session_id>", methods=["GET"])
@login_required
def get_chat_history(session_id):
    user_id = session["user_id"]
    sess = sb_get_session(session_id, user_id)
    if not sess:
        return jsonify({"error": "Session not found"}), 404

    messages = sb_get_messages(session_id)
    user_msg_count = sum(1 for m in messages if m["role"] == "user")

    return jsonify({
        "messages": messages,
        "user_message_count": user_msg_count,
        "message_limit": MESSAGE_LIMIT
    })


@app.route("/api/chat/send", methods=["POST"])
@login_required
@security_guard
def send_message():
    user_id = session["user_id"]
    first_name = session["first_name"]
    username = session["username"]
    ip = request.remote_addr or "unknown"

    data = request.json or {}
    session_id = data.get("session_id")
    content = data.get("content", "").strip()

    if not session_id or not content:
        return jsonify({"error": "Missing session_id or content"}), 400

    # Sanitize user input
    content = sanitize_input(content)

    # Blacklist check
    if is_blacklisted(content):
        log_security_event("blacklist_blocked", ip, user_id, content[:100])
        return jsonify({"error": "Invalid input detected."}), 403

    # Per-user rate limit: 10 messages per minute
    if not check_rate_limit("user_{}".format(user_id), limit=10, window=60):
        log_security_event("user_rate_limit", ip, user_id, "")
        return jsonify({"error": "Message limit reached. Please wait a moment."}), 429

    sess = sb_get_session(session_id, user_id)
    if not sess:
        return jsonify({"error": "Session not found"}), 404

    # Enforce the 50-message-per-session limit BEFORE spending an AI call
    current_count = sb_count_user_messages(session_id)
    if current_count >= MESSAGE_LIMIT:
        return jsonify({
            "error": "limit_reached",
            "message": "This chat hit its 50-message limit. Start a new chat to keep going.",
            "user_message_count": current_count,
            "message_limit": MESSAGE_LIMIT
        }), 403

    # Save user message
    sb_insert_message(session_id, "user", content)
    new_count = current_count + 1

    # Fetch last 15 messages (now including the one we just saved) for context
    messages_context = [{"role": m["role"], "content": m["content"]} for m in sb_get_recent_messages(session_id, 15)]

    # Run intent detection
    intent, payload = study_bot.detect_intent(content)

    system_prompt = study_bot.SYSTEM_PROMPT
    max_tok = None

    user_profile = study_bot.get_user_data(user_id)

    if intent == "joke":
        system_prompt = study_bot.JOKE_SYSTEM_PROMPT
        max_tok = 150
        messages_context = [{"role": "user", "content": "Tell one genuinely funny joke — preferably a science, programming, or Hinglish wordplay joke."}]
    elif intent == "fact":
        system_prompt = study_bot.FACT_SYSTEM_PROMPT
        max_tok = 200
        categories = ["science", "space", "human body", "history", "technology and AI", "mathematics", "psychology"]
        category = random.choice(categories)
        messages_context = [{"role": "user", "content": f"Give one mind-blowing lesser-known fact about {category}."}]
    elif intent == "tip":
        system_prompt = study_bot.TIP_SYSTEM_PROMPT
        max_tok = 250
        messages_context = [{"role": "user", "content": "Give one powerful productivity tip. Make it practical and actionable."}]
    elif intent == "define":
        system_prompt = study_bot.DEFINE_SYSTEM_PROMPT
        max_tok = 350
    elif intent == "summarize":
        system_prompt = study_bot.SUMMARIZE_SYSTEM_PROMPT
        max_tok = 500
    elif intent == "translate":
        system_prompt = study_bot.TRANSLATE_SYSTEM_PROMPT
        max_tok = 400
    elif intent == "motivate":
        system_prompt = study_bot.MOTIVATE_SYSTEM_PROMPT
        max_tok = 250
        total = user_profile.get("total", 0)
        score = user_profile.get("score", 0)
        context_hint = ""
        if total > 0:
            pct = round(score / total * 100)
            if pct < 50:
                context_hint = f"{first_name} is struggling a bit (accuracy: {pct}%), needs encouragement without sugar-coating."
            elif pct >= 80:
                context_hint = f"{first_name} is performing well (accuracy: {pct}%), motivate them to aim even higher."
            else:
                context_hint = f"{first_name} is doing okay (accuracy: {pct}%), push them to level up."
        prompt = (
            f"Give a short, powerful motivational message for {first_name}.\n"
            f"{context_hint}\n"
            "Make it punchy, real, personal — not generic quotes. Mix English + Hinglish. 5-7 lines max."
        )
        messages_context = [{"role": "user", "content": prompt}]
    elif intent == "search":
        query = payload or content
        try:
            search_results = study_bot.web_search(query, max_results=5)
            ai_prompt = (
                f"User ne search kiya: '{query}'\n\n"
                f"Internet se yeh results aaye hain:\n\n"
                f"{search_results}\n\n"
                f"In results ke basis pe ek clear, accurate, engaging answer do Hinglish mein. "
                f"Agar results mein kafi info nahi hai, toh honestly batao. "
                f"NEVER use **asterisks** markdown. Use emojis and → for formatting."
            )
            messages_context = [{"role": "user", "content": ai_prompt}]
            system_prompt = study_bot.SEARCH_SYSTEM_PROMPT
            max_tok = 600
        except Exception as e:
            print(f"Web search failed: {e}")
    elif intent == "brainy":
        system_prompt = study_bot.BRAINY_SYSTEM_PROMPT
        max_tok = 1000
    elif study_bot.is_offtopic_chat(content):
        system_prompt = study_bot.BANTER_SYSTEM_PROMPT or study_bot.SYSTEM_PROMPT

    # Inject learning contexts
    learn_ctx = study_bot.get_learning_context(5)
    liked_ctx = study_bot.get_liked_context(user_id, 5)
    extra = "\n\n".join(c for c in (learn_ctx, liked_ctx) if c)
    if extra:
        system_prompt = system_prompt + "\n\n" + extra

    try:
        response_text = study_bot.ai_call(messages_context, system_prompt, max_tok)
        response_text = study_bot.clean_response(response_text)
    except Exception as e:
        print(f"AI Call failed in Web App: {e}")
        response_text = f"❌ Error communicating with AI: {str(e)[:100]}"

    # Save assistant reply + auto-title the chat on its first exchange
    sb_insert_message(session_id, "assistant", response_text)

    title_updated = None
    if sess["title"] == "New Chat":
        words = content.split()[:5]
        new_title = " ".join(words) + ("..." if len(content.split()) > 5 else "")
        sb_rename_session(session_id, user_id, new_title)
        title_updated = new_title

    # ── Sync to the Telegram bot's own memory/personalization store ──
    try:
        study_bot.load_user_into_memory(user_id, first_name, username)
        if user_id in study_bot.user_conversations:
            study_bot.user_conversations[user_id].append({"role": "user", "content": content})
            study_bot.user_conversations[user_id].append({"role": "assistant", "content": response_text})
            study_bot.trim_history(user_id)
            study_bot.save_user_memory_async(user_id)
    except Exception as se:
        print(f"Sync to Supabase memory failed: {se}")

    return jsonify({
        "role": "assistant",
        "content": response_text,
        "new_title": title_updated,
        "user_message_count": new_count,
        "message_limit": MESSAGE_LIMIT
    })


# ── PROFILE & STATS APIS ──

@app.route("/api/user/profile", methods=["GET"])
@login_required
def get_user_profile():
    user_id = session["user_id"]
    study_bot.load_user_into_memory(user_id, session["first_name"], session["username"])
    profile = study_bot.get_user_data(user_id)

    return jsonify({
        "user_id": user_id,
        "first_name": session["first_name"],
        "username": session["username"],
        "level": profile.get("level") or "Not set",
        "score": profile.get("score", 0),
        "total": profile.get("total", 0),
        "joined": profile.get("joined") or "Recently"
    })


@app.route("/api/user/memory", methods=["GET"])
@login_required
def get_user_memory():
    user_id = session["user_id"]
    study_bot.load_user_into_memory(user_id, session["first_name"], session["username"])
    profile = study_bot.get_user_data(user_id)
    liked_notes = profile.get("liked_notes") or []

    learn_history = study_bot.get_learning_context(10) or "No custom learning patterns registered yet."

    return jsonify({
        "liked_notes": liked_notes,
        "learn_context": learn_history
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
