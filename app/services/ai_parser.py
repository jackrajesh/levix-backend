import os
import json
import re
from dotenv import load_dotenv
import google.generativeai as genai
from typing import Dict, Any, Optional, List

# 1. Load Environment Variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
print("[AI KEY LOADED]:", bool(GEMINI_API_KEY))

# 2. Configure Gemini Client
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY, transport='rest')
        model = genai.GenerativeModel("gemini-flash-latest")
    except Exception as e:
        print("[AI CONFIG ERROR]:", str(e))
else:
    model = None

def ai_extract_products(tokens: str) -> Optional[List[str]]:
    """
    Official SDK Extraction.
    """
    if not model or not tokens:
        return None

    try:
        print("[AI CALLED] ai_extract_products")
        # Use user-specified prompt style
        response = model.generate_content(
            f"Fix spelling. Return only product names as JSON list.\n{tokens}"
        )
        
        output = response.text.strip()
        print("[AI RAW OUTPUT]:", output)
        
        # Parse logic
        clean_output = output.replace("json", "").replace("`", "").strip()
        clean_json = re.sub(r'\[|\]', '', clean_output).strip()
        products = [p.strip().strip('"').strip("'") for p in clean_json.split(",") if p.strip()]
        
        if products:
            print(f"[AI EXTRACTION SUCCESS] Extracted: {products}")
            
        return products[:10]
    except Exception as e:
        print("[AI ERROR]:", str(e))
        return None

def parse_message_with_ai(message: str) -> Optional[Dict[str, Any]]:
    """
    Parses full message.
    """
    if not model or not message:
        return None

    prompt = (
        "Analyze for a retail shop and return STRICT JSON ONLY.\n\n"
        "Format:\n"
        "{\n"
        '  "intent": "check_product",\n'
        '  "products": ["example"],\n'
        '  "quantity": 1,\n'
        '  "tone": "friendly"\n'
        "}\n"
        "Rules: Convert product names only. No explanation."
    )

    try:
        print("[AI CALLED] parse_message_with_ai")
        response = model.generate_content(f"{prompt}\nMessage: {message}")
        output = response.text.strip()
        print("[AI RAW OUTPUT]:", output)
        
        clean_output = output.replace("json", "").replace("`", "").strip()
        data = json.loads(clean_output)
        
        return {
            "intent": str(data.get("intent", "unknown")),
            "products": data.get("products") if isinstance(data.get("products"), list) else [],
            "product": data.get("product", ""),
            "quantity": int(data.get("quantity", 1)),
            "tone": str(data.get("tone", "friendly"))
        }
    except Exception as e:
        print("[AI ERROR]:", str(e))
        return None

def generate_human_reply(data: list, user_message: str, tone: str = "friendly") -> Optional[str]:
    """
    Humanizes backend data.
    """
    if not model or not data:
        return None

    data_summary = ""
    for idx, item in enumerate(data):
        data_summary += f"{item['name']}: ₹{item['price']} ({item['status']})\n"

    prompt = (
        "Rewrite naturally. Do not change product names or price.\n"
        f"DATA:\n{data_summary}\nTone: {tone} | Original: {user_message}"
    )

    try:
        print("[AI CALLED] generate_human_reply")
        response = model.generate_content(prompt)
        output = response.text.strip()
        print("[AI RAW OUTPUT]:", output)
        return output
    except Exception as e:
        print("[AI ERROR]:", str(e))
        return None
