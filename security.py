# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   SECURITY.PY — BRAINY Web App Security Module
#   Input sanitization, rate limiting, blacklist, headers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import re
import time
import os
import random
from functools import wraps
from flask import request, jsonify, session


# ── 1. BLACKLIST PATTERNS ─────────────────────────────────
# Compiled regex patterns for detecting malicious input.
# If ANY pattern matches user input, the request is blocked.

BLACKLIST_PATTERNS = [
    # ── XSS ──
    re.compile(r'<script.*?>', re.IGNORECASE),
    re.compile(r'javascript:', re.IGNORECASE),
    re.compile(r'on\w+\s*=', re.IGNORECASE),
    re.compile(r'<iframe.*?>', re.IGNORECASE),
    re.compile(r'<object.*?>', re.IGNORECASE),
    re.compile(r'<embed.*?>', re.IGNORECASE),

    # ── SQL Injection ──
    re.compile(r'\bDROP\b.*\bTABLE\b', re.IGNORECASE),
    re.compile(r'\bDELETE\b.*\bFROM\b', re.IGNORECASE),
    re.compile(r'\bINSERT\b.*\bINTO\b', re.IGNORECASE),
    re.compile(r'\bUPDATE\b.*\bSET\b', re.IGNORECASE),
    re.compile(r'\bSELECT\b.*\bFROM\b', re.IGNORECASE),
    re.compile(r'--'),
    re.compile(r'/\*.*?\*/', re.DOTALL),

    # ── Command Injection ──
    re.compile(r'[;&|$()]'),
    re.compile(r'`.*?`'),
    re.compile(r'\|\|'),
    re.compile(r'&&'),

    # ── Spam / Abuse ──
    re.compile(r'(.{20,})\1{3,}'),           # Repeated text blocks
    re.compile(r'[\U0001F600-\U0001F64F]{10,}'),  # Too many emojis
    re.compile(r'[A-Za-z0-9]{100,}'),         # Extremely long single words

    # ── System Paths ──
    re.compile(r'/etc/passwd'),
    re.compile(r'/proc/self/environ'),
    re.compile(r'/var/log/'),

    # ── Social Engineering ──
    re.compile(r'give me (admin|owner|developer) access', re.IGNORECASE),
    re.compile(r'change my (level|role|permission)', re.IGNORECASE),
    re.compile(r'i am (admin|owner|developer)', re.IGNORECASE),
]


# ── 2. RATE LIMITING ─────────────────────────────────────
# In-memory rate limiter with automatic IP blocking.
# For production at scale, swap with Redis.

rate_limits = {}    # { identifier: [timestamp, timestamp, ...] }
blocked_ips = {}    # { ip: unblock_timestamp }
violation_counts = {}  # { ip: count } — for escalating blocks


def check_rate_limit(identifier: str, limit: int = 100, window: int = 60) -> bool:
    """Check if an identifier (IP or user key) is rate limited.

    Returns True if allowed, False if blocked.
    On violation: blocks the IP for 5 minutes.
    On 3+ violations from the same IP: blocks for 24 hours.
    """
    # Check if IP is currently blocked
    if identifier in blocked_ips:
        if time.time() < blocked_ips[identifier]:
            return False
        else:
            del blocked_ips[identifier]

    now = time.time()
    if identifier not in rate_limits:
        rate_limits[identifier] = []

    # Clean timestamps outside the sliding window
    rate_limits[identifier] = [t for t in rate_limits[identifier] if t > now - window]

    if len(rate_limits[identifier]) >= limit:
        # Track violation count for escalating blocks
        ip_key = identifier.split("_")[-1] if "_" in identifier else identifier
        violation_counts[ip_key] = violation_counts.get(ip_key, 0) + 1

        if violation_counts[ip_key] >= 3:
            # Repeated offender — block for 24 hours
            blocked_ips[identifier] = now + 86400
            log_security_event("ip_blocked_24h", ip_key, None, f"Violations: {violation_counts[ip_key]}")
        else:
            # First/second offense — block for 5 minutes
            blocked_ips[identifier] = now + 300
            log_security_event("ip_blocked_5m", ip_key, None, f"Violations: {violation_counts[ip_key]}")

        return False

    rate_limits[identifier].append(now)

    # Prevent unbounded growth: with many unique IPs over a long uptime,
    # rate_limits/blocked_ips would otherwise never shrink. Sweep
    # occasionally rather than on every call (cheap amortized cost).
    if random.random() < 0.01:
        _cleanup_rate_limit_state(now)

    return True


def _cleanup_rate_limit_state(now: float = None) -> None:
    """Drops empty/expired entries from the in-memory rate-limit state.
    Called probabilistically from check_rate_limit — not required for
    correctness, only to bound memory use over long-running processes."""
    now = now if now is not None else time.time()
    for key in [k for k, v in rate_limits.items() if not v]:
        del rate_limits[key]
    for key in [k for k, until in blocked_ips.items() if until <= now]:
        del blocked_ips[key]


def block_ip(ip: str, duration: int = 86400) -> None:
    """Manually block an IP for a given duration (default 24 hours)."""
    blocked_ips[ip] = time.time() + duration


# ── 3. INPUT SANITIZATION ────────────────────────────────

def sanitize_input(text: str) -> str:
    """Sanitize user input — strip dangerous characters and patterns.

    - Removes null bytes and control characters
    - Strips <script> tags and all HTML tags
    - Removes SQL injection characters (' " ;)
    - Removes command injection characters (& | $ ( ) `)
    - Enforces 2000 character max length
    """
    if not text:
        return ""

    # Remove null bytes
    text = text.replace('\x00', '')

    # Remove control characters (keep newline \n, carriage return \r, tab \t)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # Strip <script>...</script> blocks entirely
    text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Strip all remaining HTML tags
    text = re.sub(r'<.*?>', '', text)

    # Remove SQL injection patterns
    text = re.sub(r'[\'\";]+', '', text)

    # Remove command injection characters
    text = re.sub(r'[&|$()`]', '', text)

    # Enforce max length (prevent DoS via huge payloads)
    text = text[:2000]

    return text.strip()


def is_blacklisted(text: str) -> bool:
    """Check if text matches any blacklist pattern.

    Returns True if a match is found (input should be blocked).
    """
    if not text:
        return False

    for pattern in BLACKLIST_PATTERNS:
        if pattern.search(text):
            return True
    return False


# ── 4. SECURITY DECORATORS ───────────────────────────────

def login_required(f):
    """Decorator: reject requests that don't have a valid session.

    Checks for 'user_id' in the Flask session cookie.
    Returns 401 if not authenticated.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated


def security_guard(f):
    """Decorator: apply all security checks to a route.

    1. Rate limit check (per IP)
    2. Blacklist scan on GET query params
    3. Blacklist scan on POST/PUT/PATCH JSON body values
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr or "unknown"

        # Rate limit check (100 requests per minute per IP)
        if not check_rate_limit(ip):
            log_security_event("rate_limit_exceeded", ip, session.get("user_id"), "")
            return jsonify({"error": "Too many requests. Try again later."}), 429

        # Check GET query parameters
        if request.method == 'GET':
            for key, value in request.args.items():
                if is_blacklisted(value):
                    log_security_event("blacklist_match", ip, session.get("user_id"), f"GET param: {key}")
                    return jsonify({"error": "Invalid input detected"}), 403

        # Check POST/PUT/PATCH JSON body
        if request.method in ['POST', 'PUT', 'PATCH']:
            data = request.get_json(silent=True) or {}
            for key, value in data.items():
                if isinstance(value, str) and is_blacklisted(value):
                    log_security_event("blacklist_match", ip, session.get("user_id"), f"POST param: {key}")
                    return jsonify({"error": "Invalid input detected"}), 403

        return f(*args, **kwargs)
    return decorated


# ── 5. SECURITY EVENT LOGGING ────────────────────────────

def log_security_event(event_type: str, ip: str, user_id: int = None, detail: str = "") -> None:
    """Log security events to stdout and security.log file.

    Format: [SECURITY] {timestamp} | {event_type} | {ip} | {user_id} | {detail}

    Never logs passwords, tokens, or full user input — only truncated
    detail strings for forensic review.
    """
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    # Truncate detail to prevent log injection / bloat
    safe_detail = detail[:200] if detail else ""
    log_line = f"[SECURITY] {timestamp} | {event_type} | {ip} | {user_id} | {safe_detail}"
    print(log_line)

    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "security.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except Exception:
        # If file logging fails (e.g. read-only filesystem on Railway),
        # stdout logging above still captures the event.
        pass


# ── 6. SECURITY RESPONSE HEADERS ─────────────────────────

def security_headers(response):
    """Add security headers to every HTTP response.

    - Content-Security-Policy (CSP)
    - X-Frame-Options: DENY
    - X-Content-Type-Options: nosniff
    - Referrer-Policy: strict-origin-when-cross-origin
    - Permissions-Policy: restrict geolocation, block microphone
    """
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://telegram.org https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(self), microphone=()'
    return response
