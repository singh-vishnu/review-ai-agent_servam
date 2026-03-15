import os
import json
import random
import sqlite3
import requests
from datetime import datetime
from typing import TypedDict, Literal

from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText

# Load env variables
load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")

# ---------------- SARVAM CALL ---------------- #

def call_sarvam(prompt: str):

    url = "https://api.sarvam.ai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {SARVAM_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "sarvam-105b",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0
    }

    response = requests.post(url, headers=headers, json=payload)

    result = response.json()

    return result["choices"][0]["message"]["content"]


# ---------------- DATABASE ---------------- #

conn = sqlite3.connect('reviews.db', check_same_thread=False)

conn.execute("""
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    email TEXT,
    review TEXT,
    sentiment TEXT,
    issue_type TEXT,
    tone TEXT,
    urgency TEXT,
    ticket_id TEXT,
    response TEXT,
    created_at DATETIME
)
""")

conn.commit()


def save_to_db(email, review, sentiment, diagnosis, ticket_id, response):

    conn.execute("""
        INSERT INTO reviews (email, review, sentiment, issue_type, tone, urgency, ticket_id, response, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        email,
        review,
        sentiment,
        diagnosis.get("issue_type"),
        diagnosis.get("tone"),
        diagnosis.get("urgency"),
        ticket_id,
        response,
        datetime.now()
    ))

    conn.commit()


# ---------------- EMAIL ---------------- #

def send_email(to_email, subject, body):

    msg = MIMEText(body)

    msg["Subject"] = subject
    msg["From"] = os.getenv("EMAIL_USER")
    msg["To"] = to_email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:

        server.login(
            os.getenv("EMAIL_USER"),
            os.getenv("EMAIL_PASSWORD")
        )

        server.send_message(msg)


# ---------------- AGENT STATE ---------------- #

class AgentState(TypedDict):

    review: str
    email: str
    name: str
    language: str

    sentiment: str
    diagnosis: dict

    ticket_id: str
    response: str

    history: list
    action_plan: dict


# ---------------- SENTIMENT ---------------- #

def analyze_sentiment(state: AgentState):

    prompt = f"""
Classify sentiment of this review.

Review: {state['review']}

Return only:
positive
or
negative
"""

    result = call_sarvam(prompt).strip().lower()

    return {"sentiment": result}


# ---------------- DIAGNOSIS ---------------- #

def diagnose_issue(state: AgentState):

    prompt = f"""
Analyze the issue in this review.

Review: {state['review']}

Return ONLY JSON in this format:

{{
"issue_type":"health/water/gas/electricity/roads/software/other",
"tone":"angry/frustrated/disappointed/calm",
"urgency":"low/medium/high"
}}
"""

    result = call_sarvam(prompt)

    try:
        diagnosis = json.loads(result)
    except:
        diagnosis = {
            "issue_type": "support",
            "tone": "frustrated",
            "urgency": "medium"
        }

    return {"diagnosis": diagnosis}


# ---------------- ACTION PLAN ---------------- #

def plan_action(state: AgentState):

    d = state["diagnosis"]

    # Decide which department should handle the issue
    if d["issue_type"] == "health":
        team = "health_department"
    elif d["issue_type"] == "water":
        team = "water_department"
    elif d["issue_type"] == "gas":
        team = "gas_agency"
    elif d["issue_type"] == "electricity":
        team = "electricity_board"
    elif d["issue_type"] == "roads":
        team = "public_works"
    elif d["issue_type"] == "software":
        team = "engineering"
    else:
        team = "support"

    # Decide priority
    if d["urgency"] == "high":
        priority = "P1"
    elif d["urgency"] == "medium":
        priority = "P2"
    else:
        priority = "P3"

    action = {
        "action_type": "create_ticket",
        "assignee_team": team,
        "priority": priority
    }

    return {"action_plan": action}


# ---------------- CREATE TICKET ---------------- #

def create_ticket(state: AgentState):

    ticket_id = f"TICKET-{random.randint(1000,9999)}"

    support_email = os.getenv("EMAIL_USER")

    diagnosis = state.get("diagnosis", {})
    action_plan = state.get("action_plan", {})

    issue_type = diagnosis.get("issue_type", "other")
    tone = diagnosis.get("tone", "unknown")
    urgency = diagnosis.get("urgency", "medium")

    team = action_plan.get("assignee_team", "support")
    priority = action_plan.get("priority", "P2")  # read directly from planner

    support_body = f"""
🎫 NEW TICKET: {ticket_id}

ASSIGNMENT:
-----------
Assigned Team: {team.upper()}
Priority: {priority}

CUSTOMER:
---------
Name: {state['name']}
Email: {state['email']}

ISSUE:
------
Type: {issue_type}
Tone: {tone}
Urgency: {urgency}

REVIEW:
-------
"{state['review']}"

Please forward this to the {team} team.
"""

    # Email to support team
    send_email(
        support_email,
        f"NEW SUPPORT TICKET: {ticket_id}",
        support_body
    )

    # Email to customer
    customer_body = f"""
Dear {state['name']},

Your feedback has been received and registered under ticket {ticket_id}.
Our team will review the matter.

Support Team
"""

    send_email(
        state["email"],
        f"Support Ticket Created: {ticket_id}",
        customer_body
    )

    return {"ticket_id": ticket_id}


# ---------------- RESPONSE ---------------- #
def generate_response(state: AgentState):

    prompt = f"""
You are an AI customer support assistant.

Customer Name: {state['name']}
Review: {state['review']}
Sentiment: {state['sentiment']}

Rules:

1. If review is English → start with "Dear {state['name']},"
2. If review is Hindi/Hinglish → start with "Namaste {state['name']},"

3. Body must follow same language style as review.
4. Do NOT promise timelines.
5. Keep response 80-120 words.

End exactly with:

Best Regards
Support Team
"""

    response = call_sarvam(prompt)

    # safety check
    if response is None:
        response = "Thank you for your feedback. Your complaint has been registered and will be reviewed by the relevant team."

    save_to_db(
        state["email"],
        state["review"],
        state["sentiment"],
        state.get("diagnosis", {}),
        state.get("ticket_id"),
        response
    )

    return {"response": response}


# ---------------- ROUTING ---------------- #

def route_sentiment(state: AgentState):

    if state["sentiment"] == "negative":
        return "negative"

    return "positive"


# ---------------- GRAPH ---------------- #

builder = StateGraph(AgentState)

builder.add_node("sentiment", analyze_sentiment)
builder.add_node("diagnose", diagnose_issue)
builder.add_node("plan", plan_action)
builder.add_node("ticket", create_ticket)
builder.add_node("respond", generate_response)

builder.add_edge(START, "sentiment")

builder.add_conditional_edges(
    "sentiment",
    route_sentiment,
    {
        "negative": "diagnose",
        "positive": "respond"
    }
)

builder.add_edge("diagnose", "plan")
builder.add_edge("plan", "ticket")
builder.add_edge("ticket", "respond")

builder.add_edge("respond", END)

agent = builder.compile()