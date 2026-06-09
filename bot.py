#!/usr/bin/env python3
"""
KnowledgeBot — Slack + OpenAI + Jira + Zendesk
Ask questions in Slack, get answers from your knowledge base.
Mention @SuperBot in any channel to ask a question.
"""

import os
import json
import hmac
import hashlib
import time
import requests
import logging
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

load_dotenv()

# ── CONFIG ────────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN     = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
JIRA_URL            = os.getenv("JIRA_URL")
JIRA_EMAIL          = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN      = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT        = os.getenv("JIRA_PROJECT", "SCRUM")
ZENDESK_URL         = os.getenv("ZENDESK_URL")
ZENDESK_EMAIL       = os.getenv("ZENDESK_EMAIL")
ZENDESK_API_TOKEN   = os.getenv("ZENDESK_API_TOKEN")
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL        = "gpt-4o-mini"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
slack_client = WebClient(token=SLACK_BOT_TOKEN)

# Track processed events to avoid duplicates
processed_events = set()

# ── SLACK VERIFICATION ────────────────────────────────────────────────────────
def verify_slack_signature(request):
    timestamp = request.headers.get('X-Slack-Request-Timestamp', '')
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False
    sig_basestring = f"v0:{timestamp}:{request.get_data(as_text=True)}"
    my_signature = 'v0=' + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()
    slack_signature = request.headers.get('X-Slack-Signature', '')
    return hmac.compare_digest(my_signature, slack_signature)

# ── JIRA FUNCTIONS ────────────────────────────────────────────────────────────
def search_jira(query, max_results=5):
    """Search Jira issues using text search."""
    try:
        auth = (JIRA_EMAIL, JIRA_API_TOKEN)
        # Search by text in project
        jql = f'project = {JIRA_PROJECT} AND text ~ "{query}" ORDER BY updated DESC'
        url = f"{JIRA_URL}/rest/api/3/search/jql"
        params = {
            'jql': jql,
            'maxResults': max_results,
            'fields': 'summary,status,assignee,description,priority,created,updated,comment'
        }
        resp = requests.get(url, auth=auth, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            issues = []
            for issue in data.get('issues', []):
                fields = issue.get('fields', {})
                # Extract description text
                desc = ''
                desc_field = fields.get('description')
                if desc_field and isinstance(desc_field, dict):
                    for block in desc_field.get('content', []):
                        for inline in block.get('content', []):
                            if inline.get('type') == 'text':
                                desc += inline.get('text', '')
                desc = desc[:300] if desc else 'No description'

                # Extract latest comment
                comments = fields.get('comment', {}).get('comments', [])
                latest_comment = ''
                if comments:
                    last = comments[-1]
                    body = last.get('body', {})
                    if isinstance(body, dict):
                        for block in body.get('content', []):
                            for inline in block.get('content', []):
                                if inline.get('type') == 'text':
                                    latest_comment += inline.get('text', '')
                    latest_comment = latest_comment[:200]

                issues.append({
                    'key': issue.get('key'),
                    'summary': fields.get('summary', ''),
                    'status': fields.get('status', {}).get('name', 'Unknown'),
                    'assignee': fields.get('assignee', {}).get('displayName', 'Unassigned') if fields.get('assignee') else 'Unassigned',
                    'priority': fields.get('priority', {}).get('name', 'None') if fields.get('priority') else 'None',
                    'description': desc,
                    'latest_comment': latest_comment,
                    'url': f"{JIRA_URL}/browse/{issue.get('key')}"
                })
            return issues
        else:
            logger.error(f"Jira error: {resp.status_code} {resp.text}")
            return []
    except Exception as e:
        logger.error(f"Jira exception: {e}")
        return []

def get_jira_issue(issue_key):
    """Get a specific Jira issue by key."""
    try:
        auth = (JIRA_EMAIL, JIRA_API_TOKEN)
        url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}"
        resp = requests.get(url, auth=auth, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        logger.error(f"Jira get issue error: {e}")
        return None

def get_recent_jira_issues(max_results=10):
    """Get recently updated issues."""
    try:
        auth = (JIRA_EMAIL, JIRA_API_TOKEN)
        jql = f'project = {JIRA_PROJECT} ORDER BY updated DESC'
        url = f"{JIRA_URL}/rest/api/3/search/jql"
        params = {
            'jql': jql,
            'maxResults': max_results,
            'fields': 'summary,status,assignee,priority,updated'
        }
        resp = requests.get(url, auth=auth, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            issues = []
            for issue in data.get('issues', []):
                fields = issue.get('fields', {})
                issues.append({
                    'key': issue.get('key'),
                    'summary': fields.get('summary', ''),
                    'status': fields.get('status', {}).get('name', 'Unknown'),
                    'assignee': fields.get('assignee', {}).get('displayName', 'Unassigned') if fields.get('assignee') else 'Unassigned',
                })
            return issues
        return []
    except Exception as e:
        logger.error(f"Jira recent issues error: {e}")
        return []

# ── ZENDESK FUNCTIONS ─────────────────────────────────────────────────────────
def search_zendesk(query, max_results=5):
    """Search Zendesk tickets."""
    try:
        auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
        url = f"{ZENDESK_URL}/api/v2/search.json"
        params = {
            'query': f'type:ticket {query}',
            'per_page': max_results,
            'sort_by': 'updated_at',
            'sort_order': 'desc'
        }
        resp = requests.get(url, auth=auth, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            tickets = []
            for ticket in data.get('results', []):
                tickets.append({
                    'id': ticket.get('id'),
                    'subject': ticket.get('subject', ''),
                    'status': ticket.get('status', ''),
                    'priority': ticket.get('priority', 'normal'),
                    'description': ticket.get('description', '')[:300],
                    'created_at': ticket.get('created_at', ''),
                    'url': f"{ZENDESK_URL}/agent/tickets/{ticket.get('id')}"
                })
            return tickets
        else:
            logger.error(f"Zendesk error: {resp.status_code} {resp.text}")
            return []
    except Exception as e:
        logger.error(f"Zendesk exception: {e}")
        return []

def get_recent_zendesk_tickets(max_results=10):
    """Get recent open tickets."""
    try:
        auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
        url = f"{ZENDESK_URL}/api/v2/tickets.json"
        params = {'per_page': max_results, 'sort_by': 'updated_at', 'sort_order': 'desc'}
        resp = requests.get(url, auth=auth, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            tickets = []
            for ticket in data.get('tickets', []):
                tickets.append({
                    'id': ticket.get('id'),
                    'subject': ticket.get('subject', ''),
                    'status': ticket.get('status', ''),
                    'priority': ticket.get('priority', 'normal'),
                })
            return tickets
        return []
    except Exception as e:
        logger.error(f"Zendesk recent error: {e}")
        return []

# ── CONTEXT BUILDER ───────────────────────────────────────────────────────────
def build_context(question):
    """Fetch relevant data from Jira and Zendesk based on the question."""
    question_lower = question.lower()
    context = {}

    # Determine what to fetch
    fetch_jira = any(w in question_lower for w in [
        'jira', 'ticket', 'issue', 'bug', 'feature', 'task', 'sprint',
        'backlog', 'story', 'epic', 'pr', 'open', 'closed', 'status',
        'assignee', 'blocked', 'progress', 'done', 'todo'
    ])

    fetch_zendesk = any(w in question_lower for w in [
        'zendesk', 'support', 'customer', 'complaint', 'request',
        'help', 'contact', 'ticket', 'user', 'problem', 'issue'
    ])

    # If question mentions specific issue key (e.g. SCRUM-123)
    import re
    issue_keys = re.findall(r'[A-Z]+-\d+', question.upper())
    if issue_keys:
        for key in issue_keys:
            issue = get_jira_issue(key)
            if issue:
                context[f'jira_issue_{key}'] = issue
        fetch_jira = False  # Already fetched specific issue

    # Fetch based on keywords
    if fetch_jira or (not fetch_zendesk and not issue_keys):
        jira_results = search_jira(question)
        if jira_results:
            context['jira_issues'] = jira_results
        else:
            # Fall back to recent issues
            context['jira_recent'] = get_recent_jira_issues(5)

    if fetch_zendesk:
        zendesk_results = search_zendesk(question)
        if zendesk_results:
            context['zendesk_tickets'] = zendesk_results
        else:
            context['zendesk_recent'] = get_recent_zendesk_tickets(5)

    # If nothing specific matched, fetch both
    if not context:
        context['jira_recent'] = get_recent_jira_issues(5)
        context['zendesk_recent'] = get_recent_zendesk_tickets(5)

    return context

# ── AI QUERY ──────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are KnowledgeBot (SuperBot), an AI assistant integrated into a team's Slack workspace.
You have access to real data from Jira and Zendesk.

When answering:
- Be concise and direct — this is a Slack message, not a report
- Use the actual data provided — ticket numbers, statuses, assignees
- Format for Slack: use *bold* for emphasis, bullet points with •
- If you find relevant tickets or issues, mention them with their IDs
- Keep responses under 300 words
- If data is empty or unavailable, say so clearly and suggest where to look

You help the team answer questions like:
- "What's the status of the payment bug?"
- "Which tickets are blocked?"
- "Are there any unresolved customer complaints about search?"
- "What's assigned to [person]?"
- "Show me open tickets"
"""

def ask_ai(question, context):
    """Query OpenAI with question and context data."""
    context_str = json.dumps(context, indent=2, default=str)
    # Trim if too long
    if len(context_str) > 6000:
        context_str = context_str[:6000] + '... (truncated)'

    user_message = f"""Question from Slack: {question}

Data from Jira and Zendesk:
{context_str}

Answer the question using this data. Be concise and formatted for Slack."""

    try:
        resp = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {OPENAI_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'model': OPENAI_MODEL,
                'max_tokens': 500,
                'messages': [
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': user_message}
                ]
            },
            timeout=30
        )
        data = resp.json()
        if 'error' in data:
            return f"AI error: {data['error']['message']}"
        return data['choices'][0]['message']['content']
    except Exception as e:
        return f"Error querying AI: {str(e)}"

# ── SLACK RESPONSE ────────────────────────────────────────────────────────────
def send_slack_message(channel, text, thread_ts=None):
    """Send a message to Slack."""
    try:
        kwargs = {'channel': channel, 'text': text}
        if thread_ts:
            kwargs['thread_ts'] = thread_ts
        slack_client.chat_postMessage(**kwargs)
    except SlackApiError as e:
        logger.error(f"Slack error: {e.response['error']}")

def handle_question(question, channel, thread_ts=None):
    """Process a question and respond in Slack."""
    # Send thinking indicator
    send_slack_message(
        channel,
        "🔍 Searching Jira and Zendesk...",
        thread_ts
    )

    # Build context from data sources
    context = build_context(question)

    # Get AI answer
    answer = ask_ai(question, context)

    # Send answer
    send_slack_message(channel, answer, thread_ts)

# ── FLASK ROUTES ──────────────────────────────────────────────────────────────
@app.route('/slack/events', methods=['POST'])
def slack_events():
    data = request.json

    # URL verification challenge
    if data.get('type') == 'url_verification':
        return jsonify({'challenge': data['challenge']})

    # Verify signature
    # if not verify_slack_signature(request):
    #     return jsonify({'error': 'Invalid signature'}), 403

    # Handle events
    if data.get('type') == 'event_callback':
        event = data.get('event', {})
        event_id = data.get('event_id', '')

        # Avoid processing duplicate events
        if event_id in processed_events:
            return jsonify({'ok': True})
        processed_events.add(event_id)
        # Keep set from growing too large
        if len(processed_events) > 1000:
            processed_events.clear()

        event_type = event.get('type')

        # Handle app mentions (@SuperBot what is the status of SCRUM-1?)
        if event_type == 'app_mention':
            # Extract question — remove the bot mention
            text = event.get('text', '')
            # Remove <@BOTID> from message
            import re
            question = re.sub(r'<@[A-Z0-9]+>', '', text).strip()

            if question:
                channel = event.get('channel')
                thread_ts = event.get('thread_ts') or event.get('ts')

                # Process in background to avoid Slack timeout
                import threading
                thread = threading.Thread(
                    target=handle_question,
                    args=(question, channel, thread_ts)
                )
                thread.daemon = True
                thread.start()

        # Handle direct messages
        elif event_type == 'message' and event.get('channel_type') == 'im':
            # Ignore bot's own messages
            if event.get('bot_id'):
                return jsonify({'ok': True})

            text = event.get('text', '').strip()
            if text:
                channel = event.get('channel')
                thread_ts = event.get('ts')

                import threading
                thread = threading.Thread(
                    target=handle_question,
                    args=(text, channel, thread_ts)
                )
                thread.daemon = True
                thread.start()

    return jsonify({'ok': True})

@app.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'service': 'KnowledgeBot',
        'sources': ['Jira', 'Zendesk', 'OpenAI'],
        'jira_url': JIRA_URL,
        'zendesk_url': ZENDESK_URL
    })

@app.route('/')
def index():
    return '''
    <h2>KnowledgeBot is running</h2>
    <p>Mention @SuperBot in Slack to ask a question.</p>
    <p>Examples:</p>
    <ul>
        <li>@SuperBot what are the open bugs?</li>
        <li>@SuperBot show me recent support tickets</li>
        <li>@SuperBot what is the status of SCRUM-1?</li>
        <li>@SuperBot are there any blocked issues?</li>
    </ul>
    '''

if __name__ == '__main__':
    print("KnowledgeBot starting on port 5003...")
    print(f"Jira: {JIRA_URL}")
    print(f"Zendesk: {ZENDESK_URL}")
    print("Mention @SuperBot in Slack to ask questions")
    app.run(host='0.0.0.0', port=5003, debug=False)
