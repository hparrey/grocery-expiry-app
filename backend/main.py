from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List
import json
import os
import io

from fastapi import FastAPI, Form, Request, File, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
import google.generativeai as genai
from supabase import create_client, Client


load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

res = supabase.table("test").insert({"name": "hello"}).execute()
print("Insert result:", res)

res2 = supabase.table("test").select("*").execute()
print("Select result:", res2)

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
print("API key loaded:", bool(api_key))

genai.configure(api_key=api_key)

model = genai.GenerativeModel("gemini-3-flash-preview")

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Backend is running"}

@app.post("/extract-date/")
async def extract_date(file: UploadFile = File(...)):
    try:
        if genai_client is None:
            return {"error": "Gemini API key not configured."}

        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))

        # Single call (faster + better)
        response = genai_client.generate_content([
            """Return ONLY JSON in this format:
            {
              "expiration_date": "MM-DD-YYYY",
              "product_type": "Dairy | Meat | Produce | Snack | Beverage | Frozen | Pantry | Unknown"
            }
            """,
            image
        ])

        text = (response.text or "").strip()

        # Try parsing JSON safely
        try:
            start = text.find("{")
            end = text.rfind("}")
            json_text = text[start:end + 1] if start != -1 else text
            parsed = json.loads(json_text)

            return {
                "expiration_date": parsed.get("expiration_date", ""),
                "product_type": parsed.get("product_type", "Unknown")
            }

        except Exception:
            return {"error": "Failed to parse Gemini response", "raw": text}

    except Exception as e:
        return {"error": str(e)}

# -------------------------
# Utility Functions
# -------------------------
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

# -------------------------
# Suggestions
# -------------------------
def fallback_suggestions(active_items: list[dict]) -> list[dict]:
    if not active_items:
        return []

    urgent_items = [item["name"] for item in active_items if item["days_left"] <= 2]
    all_items = [item["name"] for item in active_items]

    return [
        {
            "name": "Quick Stir Fry",
            "description": "Use your most urgent ingredients first.",
            "matches": urgent_items[:3] if urgent_items else all_items[:3],
        },
        {
            "name": "Pantry Bowl",
            "description": "Simple meal using what you already have.",
            "matches": all_items[:3],
        },
        {
            "name": "Use-It-Up Scramble",
            "description": "Combine items that are close to expiring.",
            "matches": urgent_items[:2] + all_items[:1] if urgent_items else all_items[:3],
        },
    ]

def extract_json_block(text: str) -> str:
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    start = text.find("[")
    end = text.rfind("]")

    if start != -1 and end != -1:
        return text[start:end + 1]

    return text

def get_ai_suggestions(active_items: list[dict]) -> list[dict]:
    if not active_items:
        return []

    if genai_client is None:
        return fallback_suggestions(active_items)

    try:
        response = genai_client.generate_content(
            f"""
Suggest exactly 3 simple student meals using:
{json.dumps(active_items)}

Return ONLY JSON array.
"""
        )

        parsed = json.loads(extract_json_block(response.text or ""))
        return parsed[:3] if parsed else fallback_suggestions(active_items)

    except Exception:
        return fallback_suggestions(active_items)

# -------------------------
# Routes
# -------------------------
@app.get("/")
def home(request: Request):
    items = get_active_items()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "items": items,
            "summary": get_summary(),
            "suggestions": get_ai_suggestions(items),
            "today": str(date.today()),
        },
    )

@app.post("/add")
def add_item(
    name: str = Form(...),
    category: str = Form(...),
    expiration_date: str = Form(...),
    custom_category: str = Form(""),
):
    if category.lower() == "other" and custom_category.strip():
        category = custom_category.strip()

    next_id = max([item["id"] for item in pantry_items], default=0) + 1

    pantry_items.append({
        "id": next_id,
        "name": name.strip(),
        "category": category.strip(),
        "expiration_date": expiration_date,
        "used": False,
    })

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

    return JSONResponse({
        "items": items,
        "summary": get_summary(),
        "suggestions": get_ai_suggestions(items),
    })