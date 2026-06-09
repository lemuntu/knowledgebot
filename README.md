# KnowledgeBot — Slack + AI + Jira + Zendesk

Ask questions in Slack, get answers from your real Jira backlog and Zendesk support queue in seconds.

![KnowledgeBot demo](https://honeyindex.com/wp-content/uploads/knowledgebot-demo.png)

> **Full guide:** [honeyindex.com/slack-jira-zendesk-ai-bot-knowledgebot](https://honeyindex.com/slack-jira-zendesk-ai-bot-knowledgebot/)

---

## What it does

KnowledgeBot sits in your Slack workspace and answers questions using your actual data:

```
@superbot what bugs are currently open?
→ Here are the currently open bugs:
  • SCRUM-6: Pro membership checkout failing on mobile — Status: To Do
  • SCRUM-7: Add workflow submission form — Status: To Do
  • SCRUM-8: Email notifications for workflow approvals — Status: To Do

@superbot are there customer complaints about search?
→ Found 1 Zendesk ticket matching "search":
  • Ticket #3: "The search on your website is broken" — Status: Open

@superbot what is the status of SCRUM-6?
→ SCRUM-6: Pro membership checkout failing on mobile
  Status: To Do | Priority: High | Assignee: Christian
  Description: Users on iOS and Android report the checkout
  flow fails at the payment step...
```

Every answer comes from your real Jira tickets and Zendesk queue — not hallucination.

---

## Stack

| Component | Technology |
|-----------|-----------|
| Bot server | Python + Flask |
| Slack integration | Slack SDK (`slack-sdk`) |
| Jira | Jira REST API v3 |
| Zendesk | Zendesk REST API |
| AI model | OpenAI gpt-4o-mini (switchable to Claude, Gemini, or local Ollama) |
| Deployment | systemd service |

---

## Cost

| Service | Cost |
|---------|------|
| Slack | $0 (free tier works) |
| Jira Software | $0 (free up to 10 users) |
| Zendesk | From $19/mo |
| OpenAI gpt-4o-mini | ~$20/mo (500 questions/day) |
| Server | $0 (self-hosted) |
| **Total** | **~$39-45/mo** |

For a 50-person team that is under $1 per person per month.

---

## Quick start

### 1. Clone and install

```bash
git clone https://github.com/lemuntu/knowledgebot.git
cd knowledgebot
python3 -m venv venv
source venv/bin/activate
pip install flask slack-sdk requests openai python-dotenv
```

### 2. Create your `.env` file

```bash
cp .env.example .env
nano .env
```

Fill in your credentials:

```env
SLACK_BOT_TOKEN=xoxb-your-token-here
SLACK_SIGNING_SECRET=your-signing-secret
JIRA_URL=https://yoursite.atlassian.net
JIRA_EMAIL=you@yourcompany.com
JIRA_API_TOKEN=your-jira-api-token
JIRA_PROJECT=SCRUM
ZENDESK_URL=https://yoursite.zendesk.com
ZENDESK_EMAIL=you@yourcompany.com
ZENDESK_API_TOKEN=your-zendesk-api-token
OPENAI_API_KEY=sk-your-openai-key
```

### 3. Create your Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch
2. Name it **KnowledgeBot**, select your workspace
3. **OAuth & Permissions → Bot Token Scopes** — add:
   ```
   app_mentions:read
   channels:history
   channels:read
   chat:write
   chat:write.public
   groups:history
   im:history
   im:read
   im:write
   ```
4. Install app to workspace → copy the **Bot Token** (`xoxb-...`)
5. **Basic Information → Signing Secret** → copy it

### 4. Start the bot

```bash
# Terminal 1 — expose with ngrok
ngrok http 5003

# Terminal 2 — start the bot
source venv/bin/activate
python3 bot.py
```

### 5. Register the webhook URL

In your Slack app → **Event Subscriptions → Enable Events → Request URL**:

```
https://YOUR-NGROK-URL.ngrok-free.app/slack/events
```

Subscribe to bot events:
- `app_mention`
- `message.channels`
- `message.im`

### 6. Test in Slack

```
/invite @KnowledgeBot

@KnowledgeBot what bugs are open?
@KnowledgeBot show me recent support tickets
@KnowledgeBot what is the status of SCRUM-1?
```

---

## Production deployment

For production, run as a systemd service with a proper reverse proxy instead of ngrok.

### systemd service

```bash
sudo nano /etc/systemd/system/knowledgebot.service
```

```ini
[Unit]
Description=KnowledgeBot Slack + Jira + Zendesk
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/projects/knowledgebot
ExecStart=/home/YOUR_USERNAME/projects/knowledgebot/venv/bin/python3 bot.py
Restart=on-failure
RestartSec=10
EnvironmentFile=/home/YOUR_USERNAME/projects/knowledgebot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable knowledgebot
sudo systemctl start knowledgebot
```

### Nginx reverse proxy

Replace ngrok with a proper subdomain:

```nginx
server {
    listen 80;
    server_name bot.yourcompany.com;

    location / {
        proxy_pass http://127.0.0.1:5003;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

---

## Switching AI providers

Change one line in `bot.py` or `.env`:

```python
# OpenAI (default)
OPENAI_MODEL = "gpt-4o-mini"

# Anthropic Claude
# pip install anthropic
# Change ask_ai() to use the Anthropic SDK

# Google Gemini
# pip install google-generativeai

# Local Ollama (free, private)
# Set OLLAMA_URL = "http://localhost:11434"
# Set OLLAMA_MODEL = "mistral"
```

Full switching guide in the [blog post](https://honeyindex.com/slack-jira-zendesk-ai-bot-knowledgebot/).

---

## Extending it

KnowledgeBot is designed to be extended. Each data source follows the same pattern:

1. Add a fetcher function (see `search_jira()` and `search_zendesk()` as examples)
2. Add keywords to `build_context()` to trigger your new fetcher
3. The AI handles formatting automatically

**Ideas for extensions:**
- GitHub — open PRs, recent commits, issue status
- Notion / Confluence — search internal docs and runbooks
- PagerDuty — on-call schedules and active incidents
- Slack message history — search past decisions
- Scheduled summaries — daily digest posted every morning

---

## Project structure

```
knowledgebot/
├── bot.py          ← main application
├── .env.example    ← credentials template
├── .env            ← your credentials (never commit this)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Requirements

```
flask
slack-sdk
requests
openai
python-dotenv
```

Install: `pip install -r requirements.txt`

---

## License

MIT — use it, modify it, deploy it. If you build something cool with it, [submit it to HoneyIndex Flows](https://honeyindex.com/flows/).

---

## Built by

[HoneyIndex](https://honeyindex.com) — a directory of real AI workflows built by practitioners.

Full build guide: [honeyindex.com/slack-jira-zendesk-ai-bot-knowledgebot](https://honeyindex.com/slack-jira-zendesk-ai-bot-knowledgebot/)
