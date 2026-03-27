from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

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

RECIPE_RULES = [
    {
        "name": "Veggie Omelet",
        "needs_any": ["eggs"],
        "needs_optional": ["spinach", "cheese", "onion"],
        "description": "Use up eggs with any extra vegetables before they go bad.",
    },
    {
        "name": "Fried Rice",
        "needs_any": ["rice"],
        "needs_optional": ["eggs", "spinach", "onion", "carrot"],
        "description": "Great for using leftover rice and random vegetables.",
    },
    {
        "name": "Pasta Bowl",
        "needs_any": ["pasta"],
        "needs_optional": ["spinach", "tomato", "cheese"],
        "description": "Quick meal for using produce that is close to expiring.",
    },
    {
        "name": "Smoothie",
        "needs_any": ["banana", "milk", "yogurt"],
        "needs_optional": ["berries", "spinach"],
        "description": "Easy way to use fruit before it spoils.",
    },
]


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


def get_suggestions() -> list:
    active_names = {
        item["name"].strip().lower()
        for item in pantry_items
        if not item["used"]
    }

    suggestions = []

    for recipe in RECIPE_RULES:
        has_required = any(item in active_names for item in recipe["needs_any"])
        optional_matches = [
            item for item in recipe["needs_optional"]
            if item in active_names
        ]

        if has_required or len(optional_matches) >= 2:
            required_matches = [
                item for item in recipe["needs_any"]
                if item in active_names
            ]
            suggestions.append(
                {
                    "name": recipe["name"],
                    "description": recipe["description"],
                    "matches": optional_matches + required_matches,
                }
            )

    if not suggestions and active_names:
        suggestions.append(
            {
                "name": "Use-First Meal",
                "description": "Build a quick meal around the items closest to expiring.",
                "matches": list(active_names)[:3],
            }
        )

    return suggestions[:3]


@app.get("/")
def home(request: Request):
    items = [serialize_item(item) for item in pantry_items if not item["used"]]
    items.sort(key=lambda x: x["days_left"])

    context = {
        "items": items,
        "summary": get_summary(),
        "suggestions": get_suggestions(),
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
):
    next_id = max([item["id"] for item in pantry_items], default=0) + 1

    pantry_items.append(
        {
            "id": next_id,
            "name": name.strip(),
            "category": category.strip(),
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
    items = [serialize_item(item) for item in pantry_items if not item["used"]]
    items.sort(key=lambda x: x["days_left"])

    return JSONResponse(
        {
            "items": items,
            "summary": get_summary(),
            "suggestions": get_suggestions(),
        }
    )