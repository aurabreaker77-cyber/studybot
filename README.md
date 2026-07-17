<div align="center">
  <h1>🧠 BRAINY — AI Study Bot & Web App</h1>

  <p>
    <a href="https://github.com/aurabreaker7/BrainyAi"><img src="https://img.shields.io/badge/GitHub-Repo-181717?style=for-the-badge&logo=github&logoColor=white" alt="GitHub Repo"></a>
    <a href="https://t.me/AiChatExpert_Bot"><img src="https://img.shields.io/badge/Telegram-Bot-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram Bot"></a>
    <a href="https://t.me/aurabreaker7"><img src="https://img.shields.io/badge/Telegram-Channel-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram Channel"></a>
  </p>

  <p><strong>A multi-provider AI assistant with a BRAINY-style web interface and Telegram Mini App integration.</strong></p>
</div>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📝 Project Description

**BRAINY** is an advanced, multi-provider AI assistant designed primarily as a study companion. It seamlessly bridges a feature-rich Telegram Bot with a modern, Brainy-style web interface. Powered by an intelligent routing system, BRAINY automatically directs user queries to the best-suited AI provider among 10+ integrations (including Groq, Gemini, DeepSeek, Cerebras, OpenAI, Mistral, OpenRouter, SambaNova, Together, and Nvidia).

Whether you need deep explanations for physics concepts, real-time web search, interactive flashcards, or just a quick joke, BRAINY handles it all natively through natural language intent detection.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 🔧 Tech Stack

- **Backend:** Python 3.10+ / Flask
- **Database:** Supabase (PostgreSQL)
- **Frontend:** HTML + CSS + JS (Single-file architecture)
- **AI Providers:** Groq, Gemini, DeepSeek, Cerebras, OpenAI, Mistral, OpenRouter, SambaNova, Together, Nvidia
- **Search:** Tavily API + DuckDuckGo
- **Hosting:** Railway / Render
- **Telegram SDK:** `python-telegram-bot` v21.9

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ✨ Key Features

### 🤖 AI Capabilities
| Feature | Description |
|---------|-------------|
| **Multi-Provider AI** | → Intelligent routing across 10+ AI providers for optimal responses |
| **Intent Detection** | → Natural language routing (no strict commands needed) |
| **Study Assistance** | → Specialized prompts for Physics, Chemistry, Math, and Biology |
| **Web Search** | → Real-time search using Tavily and DuckDuckGo |
| **Deep Learning** | → `/brainy` mode for comprehensive, in-depth explanations |
| **5-Angle Learning** | → `/ask5` mode to explain topics from 5 different perspectives |
| **General Utilities** | → Summarization, definitions, and translations |

### 🌐 Web App Features
| Feature | Description |
|---------|-------------|
| **Modern UI** | → Brainy-style interface with a sleek dark theme |
| **Chat History** | → Persistent sessions saved securely in Supabase |
| **Navigation** | → Collapsible sidebar with a mobile-friendly hamburger menu |
| **Authentication** | → Seamless Telegram login integration |
| **User Profiles** | → View stats, quiz scores, and member details |
| **Custom Memory** | → Memory viewer for learning context and liked notes |
| **Code Highlighting**| → Prism.js syntax highlighting with one-click copy buttons |
| **Responsive** | → Fully optimized for both mobile and desktop |
| **Conversation export** | → Export chat to .txt or copy to clipboard |
| **Theme** | → Fully optimized for light/dark mode |

### 📱 Telegram Bot Features
| Feature | Description |
|---------|-------------|
| **Quizzes** | → Native Telegram polls with per-chat leaderboards (`/quiz`, `/leaderboard`) |
| **Flashcards** | → Swipeable flashcards organized by chapter (`/flashcards`) |
| **Formulas** | → Subject-wise quick reference formula sheets (`/formula`) |
| **Study Plans** | → Personalized 7-day study plans (`/myplan`) |
| **Saved Notes** | → Save AI answers automatically by reacting with 👍 (`/mynotes`) |
| **Image Solving** | → Vision capabilities for solving image-based questions (`/image`) |
| **Motivation** | → Personalized motivation boosts (`/motivate`) |

### 🔐 Security Features
| Feature | Description |
|---------|-------------|
| **Input Sanitization**| → Protection against XSS, SQLi, and Command Injection |
| **Blacklist System** | → Detection and blocking of unwanted/malicious patterns |
| **Rate Limiting** | → Advanced limits enforced per IP and per User |
| **Secure Auth** | → Telegram `initData` HMAC verification |
| **Session Security** | → HttpOnly, Secure, and SameSite cookie configurations |
| **Database Security** | → Row Level Security (RLS) enabled on Supabase |

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📁 Project Structure

```text
BrainyAi/
├── app.py                 # Flask web app backend and API routes
├── index.html             # Complete frontend (ChatGPT-style UI)
├── study_bot.py           # Telegram bot daemon with all AI/routing logic
├── security.py            # Security module (Rate limiting, sanitization)
├── requirements.txt       # Python dependencies
├── Procfile               # Railway/Render deployment config (gunicorn)
└── prompts/               # System prompt templates for intent routing
    ├── system_prompt.txt
    ├── brainy_prompt.txt
    ├── quiz_prompt.txt
    ├── ask5_prompt.txt
    └── ... (14 more specialized prompts)
├── fonts/ font files 
│ ├── math_symbols.txt
│ ├── mono_font_unicode.txt
│ ├── bold_font_unicode.txt
│ ├── italic_font_unicode.txt
│ ├── greek_letters.txt
│ ├── math_operators.txt
└── ... (more)
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 🚀 Quick Start

### 1. Clone the Repository
```bash
git clone https://github.com/aurabreaker7/BrainyAi.git
cd BrainyAi
```

### 2. Install Dependencies
```bash
python -m venv env
source env/bin/activate  # On Windows: env\Scripts\activate
pip install -r requirements.txt
```

### 3. Environment Variables
Create a `.env` file in the root directory and add your keys (refer to the `.env.example` if available). Minimum required keys:
```env
TELEGRAM_TOKEN=your_bot_token
YOUR_AI_API_KEY=your_ai_api_key
FLASK_SECRET_KEY=your_secure_random_string
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_KEY=your_supabase_service_key
```

### 4. Run the Application
You can run the web app and the Telegram bot separately:
```bash
# Terminal 1: Run the Flask Web App
python app.py

# Terminal 2: Run the Telegram Bot
python study_bot.py
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ☁️ Deployment (Railway / Render)

This project is configured for easy deployment on PaaS providers like Railway or Render using the included `Procfile`.

1. Connect your GitHub repository to Railway/Render.
2. Add all your environment variables in the platform's settings.
3. The `Procfile` will automatically start the necessary processes:
   - `web: gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
   - `worker: python study_bot.py`
4. Deploy and enjoy!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 👥 Contributors

<a href="https://github.com/aurabreaker7/BrainyAi/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=aurabreaker7/BrainyAi" />
</a>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ⚠️ Disclaimer

**Personal Project:** This project was created for educational purposes, API testing, and personal skill development. It is **not intended for commercial or business use**. It is open-sourced purely for learning purposes.
<br>
**DATA WE STORE:-** <ul>
  <li>Telegram username-id - to assign and verify session id for web.</li>
  <li>Your chats are end-to-end encrypted, and are stored in hash values.</li>
  <li>Timestamp of chat, or time when user started the bot.</li>
  <li>Your poll responses are stored.</li>
</ul>
<br>
<b>We do not store, log, or collect any of your sensitive information or personal data, because no sensitive data ever enters or rests on our systems, there is no data to leak or breach. All data is processed in real-time and immediately discarded after use. No user messages are stored when user chats in telegram private chat.</b>
<br>
<br>
<p>BRAINY does not permanently store IP addresses in the database. User accounts, chat history, and memory are tied only to Telegram/session user IDs — never to IP addresses.
IP addresses are used only transiently, for security purposes:

Rate limiting — IPs are held briefly in server memory to detect abuse (e.g. 100 requests/minute), and cleared automatically or on server restart.
Security logging — if a request triggers abuse detection (rate-limit breach, malicious input pattern, server error), the IP is written to a local security.log file for forensic review. Normal, safe usage never generates a log entry. Limiting is not totally based on IP it also rely's on telegram userid.

No IP address is ever linked to chat content, personal data, or stored in the Supabase database.</p>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<br>
<p>⭐ Show Your Support

If you find this project useful, please consider giving it a **Star** and **[Following](https://github.com/aurabreaker7)** me on GitHub! It helps more developers discover the project and keeps me motivated to build more open-source tools.</p>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 📬 Contact & Links

- **Creator:** Shreyansh Pathak
- **Telegram:** [@shreyanshhh_08](https://t.me/shreyanshhh_08)
- **Channel:** [@aurabreaker7](https://t.me/aurabreaker7)
- **Bot Link:** [@AiChatExpert_Bot](https://t.me/AiChatExpert_Bot)
