"""
Smoke test for the new db.py.

Verifies that:
  1. Course lookup works via colloquial ID
  2. Department search returns reasonable results
  3. Term filter on search_courses respects terms_offered_json
  4. Sections lookup returns real data
  5. Prereq lookup works and returns colloquial IDs

Run from project root:
    PYTHONPATH=. python3 scripts/verify_db.py
"""

from app.data import db


def section(title):
    print(f"\n── {title} " + "─" * (60 - len(title)))


# ── 1. Single course ──
section("1. get_course_info('CS122A')")
c = db.get_course_info("CS122A")
if c:
    print(f"✅ title: {c['title']}")
    print(f"   units: {c['units']}")
    print(f"   department: {c['department']} ({c['department_name']})")
    print(f"   ge_categories: {c['ge_categories']}")
    print(f"   prereqs (colloquial form): {c['prerequisites']}")
    print(f"   restriction: {c['restriction'][:80]}...")
else:
    print("❌ NOT FOUND — is data/uci/courses.csv missing CS122A?")


# ── 2. Department search ──
section("2. search_courses(department='COMPSCI')")
results = db.search_courses(department="COMPSCI")
print(f"Found {len(results)} COMPSCI courses")
print(f"  First 5: {[r['course_id'] for r in results[:5]]}")


# ── 3. Department alias resolution ──
section("3. search_courses(department='ics') — alias resolution")
results = db.search_courses(department="ics")
print(f"Found {len(results)} I&C SCI courses")
print(f"  First 5: {[r['course_id'] for r in results[:5]]}")


# ── 4. Term filter ──
section("4. search_courses(term='Spring 2025', department='COMPSCI')")
results = db.search_courses(term="Spring 2025", department="COMPSCI")
print(f"Found {len(results)} COMPSCI courses with 'Spring 2025' in terms_offered_json")
if results:
    print(f"  First 5: {[r['course_id'] for r in results[:5]]}")


# ── 5. Sections for one course ──
section("5. get_sections('CS122A', 'Spring 2025')")
secs = db.get_sections("CS122A", "Spring 2025")
print(f"Found {len(secs)} sections")
for s in secs[:3]:
    print(f"  section {s['section']}: {s['instructor']} (term={s['term']})")
print("  (empty list is expected if CS122A wasn't actually offered Spring 2025)")


# ── 6. Sections without term filter ──
section("6. get_sections('CS122A')  — no term filter")
secs = db.get_sections("CS122A")
print(f"Found {len(secs)} total sections across all loaded terms")


# ── 7. Prereq check ──
section("7. check_prerequisites_met('CS122A', ['ICS33'])")
result = db.check_prerequisites_met("CS122A", ["ICS33"])
print(f"  met:     {result['met']}")
print(f"  missing: {result['missing']}")
print("  (Note: real CS122A is ICS33 OR EECS114, but Phase 2 uses flat AND.")
print("   Phase 3 will use prerequisite_tree_json for proper OR handling.)")


# ── 8. Major-as-dept fallback ──
section("8. search_courses(major_requirement='Computer Science')")
results = db.search_courses(major_requirement="Computer Science")
print(f"Found {len(results)} courses (should map to dept=COMPSCI)")
print(f"  First 5: {[r['course_id'] for r in results[:5]]}")


# ── 9. GE filter ──
section("9. search_courses(ge_category='GE-2')")
results = db.search_courses(ge_category="GE-2")
print(f"Found {len(results)} courses with GE-2")
print(f"  First 5: {[r['course_id'] for r in results[:5]]}")


# ── 10. Mock fallback for ratings (still mock until Phase 2.4) ──
section("10. get_professor_rating('CAREY, M.') — mock fallback")
rating = db.get_professor_rating("CAREY, M.")
print(f"  rating: {rating}")
print("  (None expected — mock_data uses different key format than real instructor names)")


print("\n✅ All paths exercised.")