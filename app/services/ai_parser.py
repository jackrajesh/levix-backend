import logging
import json
import re
from typing import Dict, Any, Optional, List
from ..core.ai_client import AIClient

logger = logging.getLogger("levix.ai_parser")

def ai_extract_products(tokens: str) -> Optional[List[str]]:
    """
    ONE SOURCE OF TRUTH: Uses AIClient survival rotation.
    """
    try:
        prompt = f"Fix spelling. Return only product names as JSON list.\nText: {tokens}"
        
        output = AIClient.generate_content(
            contents=prompt,
            config={'max_output_tokens': 100, 'temperature': 0.1, 'response_mime_type': 'application/json'}
        )
        
        if not output: return None
        
        # Robust Parse
        clean_output = output.replace("json", "").replace("`", "").strip()
        try:
            products = json.loads(clean_output)
            if isinstance(products, list):
                return [str(p).strip() for p in products if p]
        except:
            # Fallback regex parse if JSON fails
            clean_json = re.sub(r'\[|\]', '', clean_output).strip()
            return [p.strip().strip('"').strip("'") for p in clean_json.split(",") if p.strip()]
            
        return None
    except Exception as e:
        logger.error(f"FAIL_PROVIDER: ai_extract_products - {e}")
        return None

def parse_message_with_ai(message: str) -> Optional[Dict[str, Any]]:
    """
    Survival-hardened message parser.
    """
    prompt = (
        "Analyze for a retail shop and return STRICT JSON ONLY.\n"
        "Format: {\"intent\": \"check_product\", \"products\": [\"example\"], \"quantity\": 1}\n"
        f"Message: {message}"
    )

    try:
        output = AIClient.generate_content(
            contents=prompt,
            config={'max_output_tokens': 150, 'temperature': 0.1, 'response_mime_type': 'application/json'}
        )
        
        if not output: return None
        
        clean_output = output.replace("json", "").replace("`", "").strip()
        data = json.loads(clean_output)
        
        return {
            "intent": str(data.get("intent", "unknown")),
            "products": data.get("products") if isinstance(data.get("products"), list) else [],
            "quantity": int(data.get("quantity", 1)),
            "tone": "friendly"
        }
    except Exception as e:
        logger.error(f"FAIL_PROVIDER: parse_message_with_ai - {e}")
        return None

def generate_human_reply(data: list, user_message: str, tone: str = "friendly") -> Optional[str]:
    """
    Survival-hardened humanizer.
    """
    if not data: return None

    data_summary = "\n".join([f"{item['name']}: ₹{item['price']} ({item['status']})" for item in data])
    prompt = (
        "Rewrite naturally. Do not change product names or price.\n"
        f"DATA:\n{data_summary}\nTone: {tone} | Original: {user_message}"
    )

    try:
        output = AIClient.generate_content(contents=prompt)
        return output
    except Exception as e:
        logger.error(f"FAIL_PROVIDER: generate_human_reply - {e}")
        return None
