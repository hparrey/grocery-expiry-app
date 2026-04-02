# FoodSaver for Students

A simple mobile-first hackathon MVP built with FastAPI.

## How to run

1. Open this folder in VS Code
2. Create a virtual environment
3. Install requirements
4. Start the app

### Mac
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### Windows
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Then open:
http://127.0.0.1:8000

## Demo flow
- Add grocery items
- See what expires soon
- Mark an item as used
- Show meal suggestions
- Show how many items were saved from waste
