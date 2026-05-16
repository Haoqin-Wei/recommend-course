"""
Anteater API probe v2 — try multiple endpoint shapes to find the one
that returns actual grade counts (gradeACount etc).

Run:  python3 debug_grades_v2.py
"""
from __future__ import annotations

import json
import os
import sys

try:
    import requests
except ImportError:
    print("FATAL: requests not installed.", file=sys.stderr)
    sys.exit(1)


def load_env_key() -> str:
    key = os.environ.get("ANTEATER_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(".env") as f:
            for raw in f:
                line = raw.strip()
                if line.startswith("ANTEATER_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except FileNotFoundError:
        pass
    return ""


def probe_rest(label: str, path: str, params: dict, key: str) -> None:
    url = f"https://anteaterapi.com/v2/rest{path}"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    print(f"\n──── {label} ────────────────────────")
    print(f"GET {url}")
    print(f"params={params}")
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
    except requests.RequestException as e:
        print(f"FAILED: {e}")
        return
    print(f"status={r.status_code}  content-type={r.headers.get('content-type')}")
    # Show whether grade counts appear ANYWHERE in the body
    body = r.text
    has_grade_a = "gradeACount" in body
    has_avg_gpa = "averageGPA" in body
    print(f"has gradeACount in body: {has_grade_a}")
    print(f"has averageGPA in body:  {has_avg_gpa}")
    # Print first chunk
    try:
        parsed = r.json()
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    except ValueError:
        pretty = body
    print("first 1200 chars of body:")
    print(pretty[:1200])
    if len(pretty) > 1200:
        print(f"... (truncated; total {len(pretty)} chars)")


def probe_graphql(label: str, query: str, key: str) -> None:
    url = "https://anteaterapi.com/v2/graphql"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"} if key else {"Content-Type": "application/json"}
    print(f"\n──── {label} (GraphQL) ────────────────────────")
    print(f"POST {url}")
    print(f"query: {query.strip()[:200]}...")
    try:
        r = requests.post(url, headers=headers, json={"query": query}, timeout=15)
    except requests.RequestException as e:
        print(f"FAILED: {e}")
        return
    print(f"status={r.status_code}")
    body = r.text
    has_grade_a = "gradeACount" in body
    has_avg_gpa = "averageGPA" in body
    print(f"has gradeACount: {has_grade_a}")
    print(f"has averageGPA:  {has_avg_gpa}")
    try:
        parsed = r.json()
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    except ValueError:
        pretty = body
    print("first 1500 chars:")
    print(pretty[:1500])


if __name__ == "__main__":
    key = load_env_key()
    print(f"API key length: {len(key)}")

    # Try 4 REST endpoint variants for CS122A
    # We use CS122B not 122A here because 122A has only ancient data;
    # 122B has 2025 sections — more likely to find grade data.
    dept, num = "COMPSCI", "122B"

    probe_rest("variant 1: /grades/aggregate (what we tried before)",
               "/grades/aggregate",
               {"department": dept, "courseNumber": num}, key)

    probe_rest("variant 2: /grades/raw (PeterPortal v0 name)",
               "/grades/raw",
               {"department": dept, "courseNumber": num}, key)

    probe_rest("variant 3: /grades/aggregateByCourse",
               "/grades/aggregateByCourse",
               {"department": dept, "courseNumber": num}, key)

    probe_rest("variant 4: /grades/aggregateByOffering",
               "/grades/aggregateByOffering",
               {"department": dept, "courseNumber": num}, key)

    # GraphQL probes — try common field names
    probe_graphql("GraphQL: rawGrades by course",
                  """
                  query {
                    rawGrades(department: "COMPSCI", courseNumber: "122B") {
                      year
                      quarter
                      averageGPA
                      gradeACount
                      gradeBCount
                      gradeCCount
                      gradeDCount
                      gradeFCount
                    }
                  }
                  """, key)

    probe_graphql("GraphQL: aggregateGrades by course",
                  """
                  query {
                    aggregateGrades(department: "COMPSCI", courseNumber: "122B") {
                      gradeDistribution {
                        averageGPA
                        gradeACount
                        gradeBCount
                        gradeCCount
                        gradeDCount
                        gradeFCount
                      }
                    }
                  }
                  """, key)

    # Sanity: probe the GraphQL introspection to list available types
    probe_graphql("GraphQL introspection — Query type fields",
                  """
                  {
                    __schema {
                      queryType {
                        fields {
                          name
                          description
                        }
                      }
                    }
                  }
                  """, key)