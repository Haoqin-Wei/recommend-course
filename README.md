# UCI Course Recommendation Assistant — Initial Demo

## Skill-to-Code Mapping

| SKILL.md Stage | Code Module | Description |
|---|---|---|
| Trigger / Non-trigger conditions | `modules/intent.py` | Classifies user message as course-related or not |
| Step 1: Gather key info | `modules/state.py` | Tracks session state (term, major, courses, prefs) |
| Step 2: Clarification | `modules/clarification.py` | Detects missing fields, generates clarifying questions |
| Step 3: Search knowledge base | `modules/query.py` + `data/db.py` | Queries mock data through a DB-access interface |
| Step 4: Organize & answer | `modules/answer.py` | Formats recommendations per SKILL.md answer structure |
| Step 5: Follow-up questions | `modules/followup.py` | Generates 2–3 contextual follow-up prompts |
| LLM integration | `llm/adapter.py` | Placeholder adapter for Claude Opus 4.6 |
| Frontend + dynamic schedule | `static/index.html` | Chat UI with left-side pending schedule panel |
| API layer | `routers/chat.py` | FastAPI router handling `/api/chat` |

## Project Structure

```
uci-course-advisor/
├── main.py                  # FastAPI entry point
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── routers/
│   │   ├── __init__.py
│   │   └── chat.py          # POST /api/chat
│   ├── modules/
│   │   ├── __init__.py
│   │   ├── intent.py        # Intent classification
│   │   ├── state.py         # Session state management
│   │   ├── clarification.py # Missing-info detection & question gen
│   │   ├── query.py         # Course/professor/schedule queries
│   │   ├── answer.py        # Answer formatting & structure
│   │   └── followup.py      # Follow-up question generation
│   ├── data/
│   │   ├── __init__.py
│   │   ├── db.py            # Database access interface (mock)
│   │   └── mock_data.py     # Static demo data
│   └── llm/
│       ├── __init__.py
│       └── adapter.py       # LLM adapter placeholder
├── static/
│   └── index.html           # Frontend (HTML + JS + CSS)
└── templates/               # Reserved for Jinja2 if needed
```

## How to Run

```bash
pip install fastapi uvicorn
cd uci-course-advisor
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000` in your browser.

## Implementation Order (Next Steps)

1. Replace mock data in `data/mock_data.py` with real UCI course database
2. Implement `data/db.py` with actual DB queries (SQLite → PostgreSQL)
3. Implement `llm/adapter.py` with Claude Opus 4.6 API calls
4. Replace rule-based intent classification with LLM-based classification
5. Add real prerequisite checking logic
6. Add real schedule conflict detection
7. Connect frontend schedule UI to backend state
8. Add authentication and per-user session persistence
