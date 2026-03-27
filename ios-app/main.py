from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List
import json
import os

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google import genai

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="FoodSaver for Students")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

pantry_items: List[dict] = [
    {
        "id": 1,
        "name": "Milk",
        "category": "Dairy",
        "expiration_date": str(date.today()),
        "used": False,
    },
    {
        "id": 2,
        "name": "Eggs",
        "category": "Protein",
        "expiration_date": str(date.today() + timedelta(days=3)),
        "used": False,
    },
    {
        "id": 3,
        "name": "Spinach",
        "category": "Produce",
        "expiration_date": str(date.today() + timedelta(days=2)),
        "used": False,
    },
]

genai_client = None
if os.getenv("GEMINI_API_KEY"):
    genai_client = genai.Client()


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def days_until_expiration(value: str) -> int:
    return (parse_date(value) - date.today()).days


def get_status_label(value: str) -> str:
    days = days_until_expiration(value)
    if days <= 0:
        return "eat-today"
    if days <= 2:
        return "soon"
    return "good"


def serialize_item(item: dict) -> dict:
    result = dict(item)
    result["days_left"] = days_until_expiration(item["expiration_date"])
    result["status"] = get_status_label(item["expiration_date"])
    return result


def get_summary() -> dict:
    active_items = [item for item in pantry_items if not item["used"]]
    expiring_soon = [
        item for item in active_items
        if days_until_expiration(item["expiration_date"]) <= 2
    ]
    saved_count = len([
        item for item in pantry_items
        if item["used"] and days_until_expiration(item["expiration_date"]) >= 0
    ])
    expired_count = len([
        item for item in active_items
        if days_until_expiration(item["expiration_date"]) < 0
    ])

    return {
        "total_items": len(active_items),
        "expiring_soon": len(expiring_soon),
        "saved_count": saved_count,
        "expired_count": expired_count,
    }


def get_active_items() -> list[dict]:
    items = [serialize_item(item) for item in pantry_items if not item["used"]]
    items.sort(key=lambda x: x["days_left"])
    return items


def fallback_suggestions(active_items: list[dict]) -> list[dict]:
    if not active_items:
        return []

    urgent_items = [item["name"] for item in active_items if item["days_left"] <= 2]
    all_items = [item["name"] for item in active_items]

    suggestions = [
        {
            "name": "Quick Stir Fry",
            "description": "A flexible meal idea using your most urgent ingredients first.",
            "matches": urgent_items[:3] if urgent_items else all_items[:3],
        },
        {
            "name": "Pantry Bowl",
            "description": "A simple bowl-style meal built around what you already have.",
            "matches": all_items[:3],
        },
        {
            "name": "Use-It-Up Scramble",
            "description": "A fast way to combine ingredients that are close to expiring.",
            "matches": urgent_items[:2] + all_items[:1] if urgent_items else all_items[:3],
        },
    ]

    return suggestions[:3]


def extract_json_block(text: str) -> str:
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    start = text.find("[")
    end = text.rfind("]")

    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]

    return text


def get_ai_suggestions(active_items: list[dict]) -> list[dict]:
    if not active_items:
        return []

    if genai_client is None:
        return fallback_suggestions(active_items)

    pantry_names = [item["name"] for item in active_items]
    urgent_items = [
        {
            "name": item["name"],
            "days_left": item["days_left"],
            "category": item["category"],
        }
        for item in active_items
        if item["days_left"] <= 2
    ]

    prompt = f"""
You are helping a college student use food before it expires.

Current pantry items:
{json.dumps(active_items, indent=2)}

Urgent items that expire soon:
{json.dumps(urgent_items, indent=2)}

Task:
Suggest exactly 3 easy recipe ideas that use the student's current pantry items.
Prioritize items expiring soon.
Keep recipes realistic, cheap, and student-friendly.
Do not invent complicated gourmet meals.
Do not include ingredients in "matches" unless they are actually in the pantry.

Return ONLY valid JSON in this exact format:
[
  {{
    "name": "Recipe name",
    "description": "1-2 sentence explanation",
    "matches": ["ingredient1", "ingredient2", "ingredient3"]
  }}
]
"""

    try:
        response = genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        raw_text = response.text or ""
        json_text = extract_json_block(raw_text)
        parsed = json.loads(json_text)

        clean_results = []
        pantry_lower = {name.lower() for name in pantry_names}

        for item in parsed:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name", "")).strip()
            description = str(item.get("description", "")).strip()
            matches = item.get("matches", [])

            if not isinstance(matches, list):
                matches = []

            filtered_matches = []
            for match in matches:
                match_str = str(match).strip()
                if match_str.lower() in pantry_lower:
                    filtered_matches.append(match_str)

            if name and description:
                clean_results.append(
                    {
                        "name": name,
                        "description": description,
                        "matches": filtered_matches[:5],
                    }
                )

        if clean_results:
            return clean_results[:3]

        return fallback_suggestions(active_items)

    except Exception as e:
        print("Gemini suggestion error:", e)
        return fallback_suggestions(active_items)


@app.get("/")
def home(request: Request):
    items = get_active_items()

    context = {
        "items": items,
        "summary": get_summary(),
        "suggestions": get_ai_suggestions(items),
        "today": str(date.today()),
    }

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=context,
    )


@app.post("/add")
def add_item(
    name: str = Form(...),
    category: str = Form(...),
    expiration_date: str = Form(...),
    custom_category: str = Form(""),
):
    final_category = category.strip()

    if final_category.lower() == "other" and custom_category.strip():
        final_category = custom_category.strip()

    next_id = max([item["id"] for item in pantry_items], default=0) + 1

    pantry_items.append(
        {
            "id": next_id,
            "name": name.strip(),
            "category": final_category,
            "expiration_date": expiration_date,
            "used": False,
        }
    )

    return RedirectResponse(url="/", status_code=303)


@app.post("/use/{item_id}")
def mark_used(item_id: int):
    for item in pantry_items:
        if item["id"] == item_id:
            item["used"] = True
            break

    return RedirectResponse(url="/", status_code=303)


@app.get("/api/items")
def api_items():
    items = get_active_items()

    return JSONResponse(
        {
            "items": items,
            "summary": get_summary(),
            "suggestions": get_ai_suggestions(items),
        }
    )