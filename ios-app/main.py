from datetime import date, datetime
from pathlib import Path
import io
import json
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request, File, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from PIL import Image
import google.genai as genai
from supabase import create_client, Client

# Load environment variables from .env file
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# FastAPI setup
app = FastAPI(title="FoodSaver for Students")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-secret-change-me"),
    same_site="lax",
    https_only=False,
    max_age=14 * 24 * 60 * 60,  # 14 days
)

# Static file serving
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# -------------------------
# Env / Clients
# -------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_ANON_KEY in .env")

# Initialize the generative model with the API key directly
genai_client = genai.Client(api_key=GEMINI_API_KEY)

def make_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# -------------------------
# Auth helpers
# -------------------------
def get_session_tokens(request: Request) -> tuple[Optional[str], Optional[str]]:
    access_token = request.session.get("access_token")
    refresh_token = request.session.get("refresh_token")
    return access_token, refresh_token

def set_session_tokens(request: Request, access_token: str, refresh_token: str) -> None:
    request.session["access_token"] = access_token
    request.session["refresh_token"] = refresh_token

def clear_session_tokens(request: Request) -> None:
    request.session.clear()

def get_current_user(request: Request):
    access_token, refresh_token = get_session_tokens(request)
    if not access_token or not refresh_token:
        print("[AUTH] No session tokens found.")
        return None, None

    supabase = make_supabase()

    # Strategy 1: Try set_session (restores full auth state)
    try:
        print("[AUTH] Attempting set_session...")
        session_resp = supabase.auth.set_session(access_token, refresh_token)

        if session_resp and session_resp.session:
            new_access = session_resp.session.access_token
            new_refresh = session_resp.session.refresh_token
            if new_access != access_token or new_refresh != refresh_token:
                print("[AUTH] Tokens refreshed, updating session.")
                set_session_tokens(request, new_access, new_refresh)

            if session_resp.user:
                print(f"[AUTH] set_session succeeded for {session_resp.user.email}")
                return supabase, session_resp.user

    except Exception as e:
        print(f"[AUTH] set_session failed: {e}")

    # Strategy 2: Try get_user with the access token directly
    try:
        print("[AUTH] Trying get_user with access token directly...")
        supabase2 = make_supabase()
        user_response = supabase2.auth.get_user(access_token)
        if user_response and user_response.user:
            # The access token is still valid even if set_session failed
            # Set up postgrest auth so DB queries work
            supabase2.postgrest.auth(access_token)
            print(f"[AUTH] get_user succeeded for {user_response.user.email}")
            return supabase2, user_response.user
    except Exception as e2:
        print(f"[AUTH] get_user with token also failed: {e2}")

    # Both strategies failed — now clear the session
    print("[AUTH] All auth strategies failed. Clearing session.")
    clear_session_tokens(request)
    return None, None

def require_user(request: Request):
    supabase, user = get_current_user(request)
    if not user:
        return None, None
    return supabase, user

# -------------------------
# Pantry helpers
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
    exp = str(result["expiration_date"])
    result["days_left"] = days_until_expiration(exp)
    result["status"] = get_status_label(exp)
    return result

def get_active_items(supabase: Client, user_id: str) -> list[dict]:
    response = (
        supabase.table("pantry_items")
        .select("*")
        .eq("user_id", user_id)
        .eq("used", False)
        .order("expiration_date")
        .execute()
    )

    items = [serialize_item(item) for item in (response.data or [])]
    items.sort(key=lambda x: x["days_left"])
    return items

def get_summary(supabase: Client, user_id: str) -> dict:
    response = (
        supabase.table("pantry_items")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )

    all_items = response.data or []
    active_items = [item for item in all_items if not item["used"]]

    expiring_soon = [
        item for item in active_items
        if days_until_expiration(item["expiration_date"]) <= 2
    ]

    saved_count = len([
        item for item in all_items
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
            "description": "A quick one-pan meal that helps you use your most urgent ingredients first. It is a simple way to turn vegetables and other pantry items into something warm, filling, and easy for a busy night.",
            "matches": urgent_items[:3] if urgent_items else all_items[:3],
        },
        {
            "name": "Pantry Bowl",
            "description": "A flexible meal made from ingredients you already have at home, so you do not need much extra planning. It is a practical way to combine grains, produce, and protein into something easy and satisfying.",
            "matches": all_items[:3],
        },
        {
            "name": "Use-It-Up Scramble",
            "description": "A quick scramble that is perfect for combining ingredients that are close to expiring. It gives you an easy, low-effort meal while helping reduce food waste and clear out the fridge.",
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

    # Only send item names and days_left to save tokens
    simple_items = [{"name": item["name"], "days_left": item["days_left"]} for item in active_items]

    try:
        response = genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"""
Suggest exactly 3 simple student meals using these pantry items:
{json.dumps(simple_items)}

Return ONLY a JSON array in this exact format:
[
  {{
    "name": "Recipe name",
    "description": "A slightly detailed 1-2 sentence description that sounds natural, practical, and helpful. Do not make it too short or vague.",
    "matches": ["ingredient1", "ingredient2"]
  }}
]
"""
        )

        print(f"[SUGGESTIONS] Gemini response: {response.text[:200]}")
        parsed = json.loads(extract_json_block(response.text or ""))
        return parsed[:3] if parsed else fallback_suggestions(active_items)

    except Exception as e:
        print(f"[SUGGESTIONS] Gemini failed: {e}")
        return fallback_suggestions(active_items)

# -------------------------
# Auth routes
# -------------------------
@app.get("/login")
def login_page(request: Request):
    if get_current_user(request)[1]:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": request.query_params.get("error", ""),
            "message": request.query_params.get("message", ""),
        },
    )

@app.post("/signup")
def signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    try:
        supabase = make_supabase()
        result = supabase.auth.sign_up(
            {
                "email": email.strip(),
                "password": password,
            }
        )

        if result and result.session:
            set_session_tokens(
                request,
                result.session.access_token,
                result.session.refresh_token,
            )
            return RedirectResponse(url="/", status_code=303)

        return RedirectResponse(
            url="/login?message=Account created. Check your email to confirm before logging in.",
            status_code=303,
        )

    except Exception as e:
        return RedirectResponse(
            url=f"/login?error={str(e)}",
            status_code=303,
        )

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    try:
        supabase = make_supabase()
        result = supabase.auth.sign_in_with_password(
            {"email": email.strip(), "password": password},
        )

        if not result or not result.session:
            print("[LOGIN] sign_in_with_password returned no session.")
            return RedirectResponse(
                url="/login?error=Invalid login credentials",
                status_code=303,
            )

        print(f"[LOGIN] Login successful for {email.strip()}")
        set_session_tokens(request, result.session.access_token, result.session.refresh_token)

        # Verify tokens were stored
        print(f"[LOGIN] Session access_token stored: {'access_token' in request.session}")
        print(f"[LOGIN] Session refresh_token stored: {'refresh_token' in request.session}")

        return RedirectResponse(url="/", status_code=303)

    except Exception as e:
        print(f"[LOGIN] Exception during login: {e}")
        return RedirectResponse(url=f"/login?error={str(e)}", status_code=303)

@app.post("/logout")
def logout(request: Request):
    supabase, _ = get_current_user(request)
    try:
        if supabase:
            supabase.auth.sign_out()
    except Exception:
        pass

    clear_session_tokens(request)
    return RedirectResponse(url="/login?message=Logged out.", status_code=303)

# -------------------------
# Main app routes
# -------------------------
@app.get("/")
def home(request: Request):
    print(f"[HOME] Session keys: {list(request.session.keys())}")
    print(f"[HOME] Has access_token: {'access_token' in request.session}")

    supabase, user = require_user(request)
    if not user:
        print("[HOME] No authenticated user. Redirecting to /login.")
        return RedirectResponse(url="/login", status_code=303)

    print(f"[HOME] Rendering home for {user.email}")
    items = get_active_items(supabase, user.id)
    summary = get_summary(supabase, user.id)
    suggestions = get_ai_suggestions(items)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "items": items,
            "summary": summary,
            "suggestions": suggestions,
            "today": str(date.today()),
            "user_email": user.email,
        },
    )

@app.post("/add")
def add_item(
    request: Request,
    name: str = Form(...),
    category: str = Form(...),
    expiration_date: str = Form(...),
    custom_category: str = Form(""),
):
    supabase, user = require_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if category.lower() == "other" and custom_category.strip():
        category = custom_category.strip()

    supabase.table("pantry_items").insert(
        {
            "user_id": user.id,
            "name": name.strip(),
            "category": category.strip(),
            "expiration_date": expiration_date,
            "used": False,
        }
    ).execute()

    return RedirectResponse(url="/", status_code=303)

@app.post("/use/{item_id}")
def mark_used(request: Request, item_id: int):
    supabase, user = require_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    supabase.table("pantry_items").update(
        {"used": True}
    ).eq("id", item_id).eq("user_id", user.id).execute()

    return RedirectResponse(url="/", status_code=303)

@app.get("/api/items")
def api_items(request: Request):
    supabase, user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    items = get_active_items(supabase, user.id)

    return JSONResponse(
        {
            "items": items,
            "summary": get_summary(supabase, user.id),
            "suggestions": get_ai_suggestions(items),
            "user_email": user.email,
        }
    )
# Add this route to your main.py (put it after the auth routes and before the main app routes)

@app.post("/extract-date/")
async def extract_date(request: Request, file: UploadFile = File(...)):
    supabase, user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))

        response = genai_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                image,
                """Look at this image of a food product label. Extract the following:

1. The expiration date (look for "EXP", "EXPIRY DATE", "BEST BY", "BEST BEFORE", "USE BY", "SELL BY", or any date printed on the label).
   Return it in MM-DD-YYYY format.

2. The product type/category. Classify it as one of: Produce, Dairy, Protein, Grains, Frozen, Snacks, Beverages, Canned Goods, Condiments, or Other.

Return ONLY a JSON object in this exact format with no other text:
{"expiration_date": "MM-DD-YYYY", "product_type": "Category"}

If you cannot find an expiration date, use null for that field.
If you cannot determine the product type, use null for that field."""
            ]
        )

        result_text = response.text.strip()
        if result_text.startswith("```"):
            lines = result_text.splitlines()
            result_text = "\n".join(lines[1:-1]).strip()

        parsed = json.loads(result_text)
        return JSONResponse(parsed)

    except json.JSONDecodeError as e:
        print(f"[OCR] JSON parse error: {e}")
        return JSONResponse({"expiration_date": None, "product_type": None})
    except Exception as e:
        error_str = str(e)
        print(f"[OCR] Error: {error_str}")
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
            return JSONResponse(
                {"error": "AI rate limit reached. Please wait a minute and try again, or enter the date manually."},
                status_code=429,
            )
        return JSONResponse({"error": error_str}, status_code=500)