import os
import io
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File
from PIL import Image
import google.generativeai as genai

load_dotenv()

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
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))

        response1 = model.generate_content([
            "Extract the expiration date from this image. Return the date in MM-DD-YYYY format. Just return the Date, nothing else.",
            image
        ])

        response2 = model.generate_content([
            "Return the type of product. If you can't determine the type of product, return 'Unknown'. Just return the product type, nothing else.",
            image
        ])


        return {"expiration_date": response1.text.strip(), "product_type": response2.text.strip()}
    except Exception as e:
        return {"error": str(e)}

@app.post("/recipes/")
async def get_recipes(ingredients: list[str]):
    try:
        prompt = f"Name three recipes, along with links to the recipe website, that could be made from the available ingredients: {', '.join(ingredients)}. For the recipe, format it so each instruction is on a new line, make it look neat and easy to read."
        response = model.generate_content(prompt)
        return {"recipes": response.text.strip()}
    except Exception as e:
        return {"error": str(e)}