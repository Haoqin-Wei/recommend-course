"""
Mock data for the initial demo.
Replace with real database queries in data/db.py when ready.

Data here reflects a small subset of UCI course catalog to demonstrate
the recommendation flow defined in SKILL.md.
"""

# ── Course Catalog ───────────────────────────────────────
COURSES = [
    {
        "course_id": "ICS31",
        "title": "Introduction to Programming",
        "department": "ICS",
        "units": 4,
        "description": "Introduction to fundamental concepts of programming.",
        "prerequisites": [],
        "ge_category": None,
        "major_requirement": ["Computer Science", "Informatics", "Data Science"],
    },
    {
        "course_id": "ICS32",
        "title": "Programming with Software Libraries",
        "department": "ICS",
        "units": 4,
        "description": "Construction of programs for problems and computing environments more varied than in ICS 31.",
        "prerequisites": ["ICS31"],
        "ge_category": None,
        "major_requirement": ["Computer Science", "Informatics", "Data Science"],
    },
    {
        "course_id": "ICS33",
        "title": "Intermediate Programming",
        "department": "ICS",
        "units": 4,
        "description": "Intermediate-level language features and programming concepts.",
        "prerequisites": ["ICS32"],
        "ge_category": None,
        "major_requirement": ["Computer Science", "Data Science"],
    },
    {
        "course_id": "ICS46",
        "title": "Data Structure Implementation and Analysis",
        "department": "ICS",
        "units": 4,
        "description": "Fundamental data structures and algorithms.",
        "prerequisites": ["ICS33"],
        "ge_category": None,
        "major_requirement": ["Computer Science", "Data Science"],
    },
    {
        "course_id": "CS161",
        "title": "Design and Analysis of Algorithms",
        "department": "CS",
        "units": 4,
        "description": "Techniques for efficient algorithm design.",
        "prerequisites": ["ICS46"],
        "ge_category": None,
        "major_requirement": ["Computer Science"],
    },
    {
        "course_id": "CS122A",
        "title": "Introduction to Data Management",
        "department": "CS",
        "units": 4,
        "description": "Introduction to databases and data management.",
        "prerequisites": ["ICS32"],
        "ge_category": None,
        "major_requirement": ["Computer Science", "Data Science"],
    },
    {
        "course_id": "IN4MATX43",
        "title": "Introduction to Software Engineering",
        "department": "IN4MATX",
        "units": 4,
        "description": "Concepts, methods, and tools for developing large-scale software.",
        "prerequisites": ["ICS32"],
        "ge_category": None,
        "major_requirement": ["Informatics", "Computer Science"],
    },
    {
        "course_id": "STATS67",
        "title": "Introduction to Probability and Statistics",
        "department": "STATS",
        "units": 4,
        "description": "Introduction to probability, statistical methods, and data analysis.",
        "prerequisites": [],
        "ge_category": "GE-III",
        "major_requirement": ["Computer Science", "Data Science"],
    },
    {
        "course_id": "WRITING39C",
        "title": "Argument and Research",
        "department": "WRITING",
        "units": 4,
        "description": "Argument and research-based writing.",
        "prerequisites": [],
        "ge_category": "GE-Ib",
        "major_requirement": [],
    },
    {
        "course_id": "ANTHRO2A",
        "title": "Introduction to Sociocultural Anthropology",
        "department": "ANTHRO",
        "units": 4,
        "description": "Survey of sociocultural anthropology.",
        "prerequisites": [],
        "ge_category": "GE-IV",
        "major_requirement": [],
    },
]

# ── Sections & Schedules (Fall 2025 demo) ────────────────
SECTIONS = [
    {"course_id": "ICS31",      "section": "A", "term": "Fall 2025", "instructor": "Kay, R.",      "days": "MWF",  "time": "10:00-10:50", "location": "DBH 1500",   "seats_open": 20},
    {"course_id": "ICS32",      "section": "A", "term": "Fall 2025", "instructor": "Thornton, A.", "days": "TuTh", "time": "11:00-12:20", "location": "ICS 174",    "seats_open": 5},
    {"course_id": "ICS33",      "section": "A", "term": "Fall 2025", "instructor": "Pattis, R.",   "days": "MWF",  "time": "14:00-14:50", "location": "PSLH 100",   "seats_open": 30},
    {"course_id": "ICS46",      "section": "A", "term": "Fall 2025", "instructor": "Thornton, A.", "days": "TuTh", "time": "14:00-15:20", "location": "EH 1200",    "seats_open": 15},
    {"course_id": "ICS46",      "section": "B", "term": "Fall 2025", "instructor": "Shindler, M.", "days": "MWF",  "time": "10:00-10:50", "location": "SSH 100",    "seats_open": 0},
    {"course_id": "CS161",      "section": "A", "term": "Fall 2025", "instructor": "Goodrich, M.", "days": "TuTh", "time": "09:30-10:50", "location": "DBH 1500",   "seats_open": 25},
    {"course_id": "CS122A",     "section": "A", "term": "Fall 2025", "instructor": "Carey, M.",    "days": "TuTh", "time": "11:00-12:20", "location": "DBH 1100",   "seats_open": 40},
    {"course_id": "IN4MATX43",  "section": "A", "term": "Fall 2025", "instructor": "Ziv, H.",      "days": "MWF",  "time": "12:00-12:50", "location": "HSLH 100A",  "seats_open": 35},
    {"course_id": "STATS67",    "section": "A", "term": "Fall 2025", "instructor": "Stern, H.",    "days": "MWF",  "time": "09:00-09:50", "location": "PSLH 100",   "seats_open": 50},
    {"course_id": "WRITING39C", "section": "A", "term": "Fall 2025", "instructor": "Staff",        "days": "TuTh", "time": "14:00-15:20", "location": "HH 202",     "seats_open": 18},
    {"course_id": "ANTHRO2A",   "section": "A", "term": "Fall 2025", "instructor": "Douglas, B.",  "days": "MWF",  "time": "11:00-11:50", "location": "SSL 228",    "seats_open": 60},
]

# ── Professor Ratings (mock RMP-style) ───────────────────
PROFESSOR_RATINGS = {
    "Thornton, A.": {"overall": 4.8, "difficulty": 3.5, "would_take_again": 95, "top_tags": ["amazing lectures", "tough but fair", "clear grading"]},
    "Pattis, R.":   {"overall": 4.5, "difficulty": 4.0, "would_take_again": 88, "top_tags": ["very knowledgeable", "heavy workload", "great lecturer"]},
    "Kay, R.":      {"overall": 4.2, "difficulty": 2.5, "would_take_again": 90, "top_tags": ["approachable", "easy to follow", "helpful"]},
    "Goodrich, M.": {"overall": 4.6, "difficulty": 3.8, "would_take_again": 92, "top_tags": ["brilliant", "fast-paced", "interesting"]},
    "Carey, M.":    {"overall": 4.7, "difficulty": 3.2, "would_take_again": 93, "top_tags": ["engaging", "fair exams", "industry experience"]},
    "Shindler, M.": {"overall": 4.3, "difficulty": 3.9, "would_take_again": 85, "top_tags": ["organized", "tough exams", "helpful office hours"]},
    "Ziv, H.":      {"overall": 3.8, "difficulty": 2.8, "would_take_again": 75, "top_tags": ["easy grader", "lectures can be dry", "manageable workload"]},
    "Stern, H.":    {"overall": 4.0, "difficulty": 3.0, "would_take_again": 82, "top_tags": ["clear explanations", "standard stats course"]},
    "Douglas, B.":  {"overall": 4.1, "difficulty": 2.0, "would_take_again": 88, "top_tags": ["interesting content", "easy", "great GE"]},
    "Staff":        {"overall": None, "difficulty": None, "would_take_again": None, "top_tags": []},
}

# ── Grade Distributions (mock) ───────────────────────────
GRADE_DISTRIBUTIONS = {
    "ICS31":      {"avg_gpa": 3.1, "pct_A": 35, "pct_B": 30, "pct_C": 20, "pct_D_F": 15},
    "ICS32":      {"avg_gpa": 2.9, "pct_A": 28, "pct_B": 32, "pct_C": 22, "pct_D_F": 18},
    "ICS33":      {"avg_gpa": 2.7, "pct_A": 22, "pct_B": 30, "pct_C": 25, "pct_D_F": 23},
    "ICS46":      {"avg_gpa": 2.8, "pct_A": 25, "pct_B": 28, "pct_C": 25, "pct_D_F": 22},
    "CS161":      {"avg_gpa": 3.0, "pct_A": 30, "pct_B": 35, "pct_C": 20, "pct_D_F": 15},
    "CS122A":     {"avg_gpa": 3.2, "pct_A": 38, "pct_B": 30, "pct_C": 20, "pct_D_F": 12},
    "IN4MATX43":  {"avg_gpa": 3.4, "pct_A": 42, "pct_B": 32, "pct_C": 18, "pct_D_F": 8},
    "STATS67":    {"avg_gpa": 3.0, "pct_A": 32, "pct_B": 30, "pct_C": 22, "pct_D_F": 16},
    "WRITING39C": {"avg_gpa": 3.3, "pct_A": 40, "pct_B": 35, "pct_C": 20, "pct_D_F": 5},
    "ANTHRO2A":   {"avg_gpa": 3.5, "pct_A": 45, "pct_B": 30, "pct_C": 18, "pct_D_F": 7},
}

# ── Demo Student Profile ─────────────────────────────────
DEMO_STUDENT = {
    "student_id": "demo_001",
    "name": "Demo Student",
    "major": "Computer Science",
    "year": "Sophomore",
    "completed_courses": ["ICS31", "ICS32"],
    "selected_courses": ["ICS33"],   # currently enrolled
    "term": "Fall 2025",
}
