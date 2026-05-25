# app/data/policies.py
"""
UCI academic policies, hardcoded from catalogue + registrar.
Last verified: 2026-05-19 from sources listed at bottom of file.
"""
from __future__ import annotations

UNIT_LIMITS = {
    "undergrad": {
        "min_per_quarter": 12,
        "max_initial": 18,        # 初始 enrollment 限制
        "max_open": 20,           # WebReg 重开后
        "max_petition": None,     # >20 看个案
        "ics_max_petition": 26,
        "summer_session_default": 10,
        "summer_session_ics_petition": 14,
    },
    "grad": {
        "min_per_quarter": 8,
        "max_per_quarter": 16,
    },
}

DEGREE_REQUIREMENTS = {
    "min_units": 180,
    "min_gpa": 2.0,
    "min_residence_units_of_final_45": 36,
}

CLASS_LEVEL = [  # ordered
    ("freshman",  0,    45),
    ("sophomore", 45,   90),
    ("junior",    90,   135),
    ("senior",    135,  float("inf")),
]

PASS_NO_PASS = {
    "max_avg_units_per_quarter": 4,
    "good_standing_required": True,
}

ACADEMIC_CALENDAR = {
    "2025-2026": {
        "fall":   {"quarter_begin": "2025-09-22", "instruction_begin": "2025-09-25",
                   "instruction_end": "2025-12-05", "quarter_end": "2025-12-12"},
        "winter": {"quarter_begin": "2026-01-02", "instruction_begin": "2026-01-05",
                   "instruction_end": "2026-03-13", "quarter_end": "2026-03-20"},
        "spring": {"quarter_begin": "2026-03-25", "instruction_begin": "...",
                   "instruction_end": "...",       "quarter_end": "2026-06-12"},
        "summer": {"session_1": ("2026-06-22", "2026-07-29"),
                   "session_2": ("2026-08-03", "2026-09-09"),
                   "ten_week":  ("2026-06-22", "2026-08-28")},
    },
}

SOURCES = {  # 给 LLM 引用 + 你自己核对
    "academic_regulations": "https://catalogue.uci.edu/informationforadmittedstudents/academicregulationsandprocedures/",
    "registration": "https://catalogue.uci.edu/informationforadmittedstudents/registrationandotherprocedures/",
    "bachelor_requirements": "https://catalogue.uci.edu/informationforadmittedstudents/requirementsforabachelorsdegree/",
    "academic_calendar": "https://catalogue.uci.edu/academiccalendar/academiccalendar.pdf",
    "registrar_calendar": "https://www.reg.uci.edu/navigation/calendars.html",
    "ics_policies": "https://ics.uci.edu/academics/undergrad/ics-course-enrollment-policies/",
    "extra_units_petition": "https://uu.uci.edu/current-students/policies-and-procedures/extra-units-petition-process/",
}
