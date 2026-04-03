# tools/mock_tools.py
#
# 对应 SKILL.md：Step 3 中列出的 6 类工具（possible_tools）
#
# 当前阶段：全部使用 mock 数据，不接真实 API。
# 每个函数的签名与返回结构已定义好，后续替换为真实实现时只需改函数体。
#
# 工具列表（来自 SKILL.md metadata.possible_tools）：
#   student_profile_tool      → get_student_profile()
#   course_catalog_tool       → get_course_catalog()
#   course_schedule_tool      → get_course_schedule()
#   prerequisite_tool         → get_prerequisites()
#   professor_rating_tool     → get_professor_ratings()
#   grade_distribution_tool   → get_grade_distribution()
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# 数据结构定义（工具返回值类型）
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CourseInfo:
    course_id: str           # 例如 "CS 161"
    title: str               # 课程名称
    units: int               # 学分
    description: str         # 课程描述
    prerequisites: list[str] = field(default_factory=list)
    ge_categories: list[str] = field(default_factory=list)   # GE 类别
    major_requirements: list[str] = field(default_factory=list)  # 满足的专业要求
    # TODO: 由开发者决定是否需要更多字段


@dataclass
class SectionInfo:
    section_id: str
    course_id: str
    instructor: str
    meeting_days: list[str]    # 例如 ["MWF"]
    meeting_time: str          # 例如 "10:00-10:50am"
    location: str
    enrolled: int
    capacity: int
    # TODO: 由开发者决定是否需要 waitlist、final_exam 等字段


@dataclass
class ProfessorRating:
    name: str
    rmp_score: float           # RMP 评分，满分 5.0
    difficulty: float          # 难度评分，满分 5.0
    review_summary: str        # 评论摘要（mock 数据中用占位文本）
    total_ratings: int
    # TODO: 由开发者决定是否需要 would_take_again 等字段


@dataclass
class GradeDistribution:
    course_id: str
    instructor: str
    term: str
    grade_counts: dict         # 例如 {"A": 30, "B": 20, "C": 10, ...}
    average_gpa: float
    # TODO: 由开发者决定历史给分率数据的来源格式（Zotistics API 结构）


# ─────────────────────────────────────────────────────────────────────────────
# Mock 数据（demo 阶段使用，生产环境替换为真实 API 调用）
# ─────────────────────────────────────────────────────────────────────────────

# ⚠️ 以下所有数据为虚构 mock 数据，仅用于验证 pipeline 通路

_MOCK_COURSES: dict[str, CourseInfo] = {
    "CS 161": CourseInfo(
        course_id="CS 161",
        title="Design and Analysis of Algorithms",
        units=4,
        description="[Mock] Algorithm design techniques.",
        prerequisites=["CS 122A", "ICS 46"],
        major_requirements=["CS Core"],
    ),
    "CS 171": CourseInfo(
        course_id="CS 171",
        title="Introduction to Artificial Intelligence",
        units=4,
        description="[Mock] Foundations of AI.",
        prerequisites=["CS 161"],
        major_requirements=["CS Elective"],
    ),
    "CS 175": CourseInfo(
        course_id="CS 175",
        title="Project in Artificial Intelligence",
        units=4,
        description="[Mock] AI project course.",
        prerequisites=["CS 171"],
        major_requirements=["CS Elective"],
    ),
    "ICS 31": CourseInfo(
        course_id="ICS 31",
        title="Introduction to Programming",
        units=4,
        description="[Mock] Intro to Python.",
        prerequisites=[],
        ge_categories=["II"],
    ),
}

_MOCK_SECTIONS: list[SectionInfo] = [
    SectionInfo("CS161-A", "CS 161", "Dr. Shindler",   ["MWF"], "10:00-10:50am", "DBH 1100", 80, 100),
    SectionInfo("CS161-B", "CS 161", "Dr. Dillencourt", ["TR"],  "2:00-3:20pm",  "ICS 174",  60, 80),
    SectionInfo("CS171-A", "CS 171", "Dr. Rina Dechter",["MWF"], "11:00-11:50am","ICS 174",  70, 90),
    SectionInfo("CS175-A", "CS 175", "Dr. Rina Dechter",["TR"],  "9:30-10:50am", "DBH 1200", 40, 50),
]

_MOCK_PROFESSOR_RATINGS: dict[str, ProfessorRating] = {
    "Dr. Shindler":    ProfessorRating("Dr. Shindler",    4.2, 3.8, "[Mock review summary]", 120),
    "Dr. Dillencourt": ProfessorRating("Dr. Dillencourt", 3.9, 3.5, "[Mock review summary]", 85),
    "Dr. Rina Dechter":ProfessorRating("Dr. Rina Dechter",4.5, 4.1, "[Mock review summary]", 200),
}

_MOCK_GRADE_DATA: list[GradeDistribution] = [
    GradeDistribution("CS 161", "Dr. Shindler",    "2024 Fall", {"A": 25, "B": 30, "C": 20, "D": 5, "F": 2}, 3.1),
    GradeDistribution("CS 161", "Dr. Dillencourt", "2024 Fall", {"A": 30, "B": 28, "C": 15, "D": 4, "F": 1}, 3.3),
    GradeDistribution("CS 171", "Dr. Rina Dechter","2024 Fall", {"A": 40, "B": 25, "C": 10, "D": 2, "F": 1}, 3.6),
]


# ─────────────────────────────────────────────────────────────────────────────
# Tool 函数实现（mock 版本）
# ─────────────────────────────────────────────────────────────────────────────

def get_student_profile(user_id: str) -> Optional[dict]:
    """
    student_profile_tool：获取专业、年级、已选课程、已修课程。

    Args:
        user_id: 学生 ID 或会话 ID。

    Returns:
        dict with keys: major, year, selected_courses, completed_courses
        或 None（找不到该学生）

    TODO: 替换为真实 UCI 学生系统 API 调用。
    """

    # Mock：返回固定的示例学生数据
    # TODO: 替换为真实 API 调用
    _MOCK_PROFILES = {
        "demo_user": {
            "major": "Computer Science",
            "year": "junior",
            "selected_courses": ["CS 161"],
            "completed_courses": ["ICS 31", "ICS 32", "ICS 33", "ICS 45C", "ICS 46"],
        }
    }
    return _MOCK_PROFILES.get(user_id)


def get_course_catalog(
    term: str,
    major: Optional[str] = None,
    filters: Optional[dict] = None,
) -> list[CourseInfo]:
    """
    course_catalog_tool：获取课程基础信息，支持按学期、专业筛选。

    Args:
        term:    学期，例如 "2025 Spring"。
        major:   专业过滤（可选）。
        filters: 额外过滤条件（可选），例如 {"ge_category": "II", "units": 4}。

    Returns:
        list[CourseInfo]: 符合条件的课程列表。

    TODO: 替换为 UCI WebSoc API 或本地课程数据库查询。
    """

    # Mock：忽略 term/major/filters 直接返回所有 mock 课程
    # TODO: 替换为真实数据源查询
    return list(_MOCK_COURSES.values())


def get_course_schedule(
    course_ids: list[str],
    term: str,
) -> list[SectionInfo]:
    """
    course_schedule_tool：获取课程 section、meeting time 及冲突信息。

    Args:
        course_ids: 要查询的课程 ID 列表。
        term:       学期。

    Returns:
        list[SectionInfo]: 对应课程的所有 section 信息。

    TODO: 替换为 UCI WebSoc Schedule of Classes API。
    """

    # Mock：按 course_id 过滤返回
    # TODO: 替换为真实 API
    return [s for s in _MOCK_SECTIONS if s.course_id in course_ids]


def get_prerequisites(course_id: str) -> list[str]:
    """
    prerequisite_tool：获取某门课程的先修课要求。

    Args:
        course_id: 课程 ID，例如 "CS 161"。

    Returns:
        list[str]: 先修课 ID 列表。空列表表示无先修要求。

    TODO: 替换为真实课程先修数据（WebSoc 或本地 catalog）。
    """

    course = _MOCK_COURSES.get(course_id)
    if course:
        return course.prerequisites
    # TODO: 处理课程不存在的情况
    return []


def get_professor_ratings(
    instructor_names: list[str],
) -> list[ProfessorRating]:
    """
    professor_rating_tool：获取教授 RMP 评分与评论摘要。

    Args:
        instructor_names: 教授姓名列表。

    Returns:
        list[ProfessorRating]: 对应教授的评分信息。

    TODO: 替换为 Rate My Professor API 或爬虫数据。
    """

    # Mock：按姓名查找
    # TODO: 替换为真实 RMP 数据源
    result = []
    for name in instructor_names:
        if name in _MOCK_PROFESSOR_RATINGS:
            result.append(_MOCK_PROFESSOR_RATINGS[name])
    return result


def get_grade_distribution(
    course_id: str,
    instructor: Optional[str] = None,
    term: Optional[str] = None,
) -> list[GradeDistribution]:
    """
    grade_distribution_tool：获取课程历史给分率 / GPA 分布。

    Args:
        course_id:   课程 ID。
        instructor:  教授姓名（可选，过滤特定教授）。
        term:        学期（可选，过滤特定学期）。

    Returns:
        list[GradeDistribution]: 历史给分率数据列表。

    TODO: 替换为 Zotistics API 或爬取数据。
    """

    # Mock：按 course_id 过滤，可选按 instructor / term 进一步过滤
    # TODO: 替换为真实 Zotistics 数据
    results = [g for g in _MOCK_GRADE_DATA if g.course_id == course_id]
    if instructor:
        results = [g for g in results if g.instructor == instructor]
    if term:
        results = [g for g in results if g.term == term]
    return results
