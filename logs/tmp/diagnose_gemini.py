import os
import sys
import requests
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def test_model(model_name, version="v1beta"):
    url = f"https://generativelanguage.googleapis.com/{version}/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": "Hello"}]}]
    }
    print(f"Testing {model_name} on {version}...")
    try:
        response = requests.post(url, json=payload, timeout=5)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            print("Success!")
            return True
        else:
            print(f"Error: {response.text}")
            return False
    except Exception as e:
        print(f"Exception: {e}")
        return False

if __name__ == "__main__":
    if not GEMINI_API_KEY:
        print("No API Key found in .env")
        sys.exit(1)
        
    models_to_try = [
        ("gemini-1.5-flash", "v1beta"),
        ("gemini-1.5-flash", "v1"),
        ("gemini-pro", "v1beta")
    ]
    
    for model, ver in models_to_try:
        if test_model(model, ver):
            print(f"Found working combination: {model} on {ver}")
            break
