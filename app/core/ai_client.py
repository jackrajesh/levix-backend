import os
import time
import logging
import requests
import json
from typing import Optional, List, Any, Dict

logger = logging.getLogger("levix.ai_client")

class AIClient:
    _client = None
    _status: str = "INITIALIZING"
    _is_initialized: bool = False
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SURVIVAL REGISTRY
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    _failed_models: Dict[str, float] = {}  # model_id -> cooldown_expiry
    _last_healthy_model: Optional[str] = None
    _cooldown_period = 300  # 5 Minutes (Mandatory)
    
    @classmethod
    def initialize(cls):
        """Registry Boot Sequence."""
        if cls._is_initialized: return
            
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            try:
                from google import genai
                cls._client = genai.Client(api_key=gemini_key)
                cls._status = "READY"
            except Exception as e:
                logger.error(f"BOOT_ERROR: Gemini - {e}")
                cls._status = "ERROR"

        # Startup Report
        pool = cls._get_priority_pool()
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("LEVIX AI STATUS REPORT")
        logger.info(f"Gemini Key: {'Loaded' if gemini_key else 'Missing'}")
        logger.info(f"OpenRouter Key: {'Loaded' if os.getenv('OPENROUTER_API_KEY') else 'Missing'}")
        logger.info(f"Providers Loaded: {len(pool)}")
        logger.info(f"Provider Order: { ' -> '.join(pool) }")
        logger.info(f"System Ready: {cls._status == 'READY'}")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        cls._is_initialized = True

    @classmethod
    def _get_priority_pool(cls) -> List[str]:
        """Survival Chain Construction."""
        pool = []
        if os.getenv("GEMINI_API_KEY"):
            pool.append("gemini-primary")
            
        or_models = os.getenv("OPENROUTER_MODELS", "google/gemini-2.0-flash-001,anthropic/claude-3-5-haiku,meta-llama/llama-3.1-8b-instruct:free")
        for m in or_models.split(","):
            if m.strip(): pool.append(m.strip())
            
        pool.append("local-engine")
        return pool

    @classmethod
    def generate_content(cls, contents: str, config: Dict[str, Any] = None, system_instruction: str = None) -> str:
        """ONE SOURCE OF TRUTH."""
        config = config or {}
        pool = cls._get_priority_pool()
        now = time.time()
        
        # Priority: Last healthy first
        if cls._last_healthy_model and cls._last_healthy_model in pool:
            if cls._failed_models.get(cls._last_healthy_model, 0) < now:
                pool.remove(cls._last_healthy_model)
                pool.insert(0, cls._last_healthy_model)

        all_errors = []
        for model_id in pool:
            if cls._failed_models.get(model_id, 0) > now: continue

            logger.info(f"TRY_PROVIDER: {model_id}")
            start_time = time.time()
            
            try:
                res = None
                if model_id == "gemini-primary":
                    res = cls._try_gemini(contents, config, system_instruction)
                elif model_id == "local-engine":
                    res = cls._try_local_engine(contents, config)
                else:
                    res = cls._try_openrouter(model_id, contents, config, system_instruction)
                
                if res:
                    elapsed = int((time.time() - start_time) * 1000)
                    cls._last_healthy_model = model_id
                    logger.info(f"PROVIDER_USED: {model_id} | SUCCESS ({elapsed}ms)")
                    return res
                
                raise Exception("Empty Response")
                    
            except Exception as e:
                err_msg = str(e)
                all_errors.append(f"[{model_id}]: {err_msg}")
                logger.warning(f"FAIL_PROVIDER: {model_id} ({err_msg[:80]})")
                logger.info(f"FAILOVER_USED: Switching to next provider in pool")
                
                if any(x in err_msg.lower() for x in ["429", "limit", "exhausted", "quota"]):
                    cls._failed_models[model_id] = now + cls._cooldown_period
                else:
                    cls._failed_models[model_id] = now + 60 

        logger.error(f"CHAIN_EXHAUSTED: All providers failed. Errors: {all_errors}")
        return cls._smart_commerce_fallback(contents, config.get("intent", "UNKNOWN"))

    @classmethod
    def _try_gemini(cls, contents: str, config: Dict[str, Any], system_instruction: str) -> Optional[str]:
        client = cls.get_client()
        if not client: return None
        
        try:
            from google.genai import types
            
            # Rebuild config to be strictly compliant with new SDK types
            # Note: response_mime_type should be 'application/json' (literal)
            gen_config = {
                'temperature': config.get('temperature', 0.1),
                'max_output_tokens': config.get('max_output_tokens', 500)
            }
            
            # Only add response_mime_type if specifically requested
            if config.get('response_mime_type') == 'application/json':
                gen_config['response_mime_type'] = 'application/json'
            
            # System instruction handling for new SDK
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    **gen_config
                )
            )
            return response.text.strip() if response.text else None
        except Exception as e:
            # Re-raise to let generate_content handle failover
            raise e

    @classmethod
    def _try_openrouter(cls, model_id: str, contents: str, config: Dict[str, Any], system_instruction: str) -> Optional[str]:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key: return None
        
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "HTTP-Referer": "https://levix.ai"}
        messages = []
        if system_instruction: messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": contents})

        payload = {"model": model_id, "messages": messages, "temperature": 0.1, "max_tokens": 500}
        if config.get("response_mime_type") == "application/json":
            payload["response_format"] = {"type": "json_object"}

        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, data=json.dumps(payload), timeout=15)
        
        logger.info(f"OPENROUTER RAW STATUS: {response.status_code}")
        logger.info(f"OPENROUTER RAW BODY: {response.text[:200]}")
        
        if not response.text.strip():
            return None
            
        if response.status_code == 200:
            try:
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.error(f"OPENROUTER JSON PARSE ERROR: {e}")
                return None
        raise Exception(f"OR_{response.status_code}")

    @classmethod
    def _try_local_engine(cls, message: str, config: Dict[str, Any]) -> Optional[str]:
        """LOCAL ENGINE: Recommendation logic without AI."""
        msg = message.lower()
        if "dinner" in msg or "recommend" in msg:
            return "Based on our menu, I'd suggest our specials! 😊 Shall I send your request to the shop owner?"
        return None

    @classmethod
    def _smart_commerce_fallback(cls, message: str, intent: str) -> str:
        """COMMERCE-SAFE FALLBACK."""
        msg = message.lower()
        if any(x in msg for x in ["recommend", "best", "dinner", "suggest", "dinner"]):
            return "Got it 😊 We'll help you choose the best option. Shall I send your request to the shop owner?"
        return "I couldn't find the exact item. Shall I send your request to the shop owner?"

    @classmethod
    def get_client(cls):
        if not cls._client: cls.initialize()
        return cls._client

    @classmethod
    def get_status_report(cls) -> str:
        active = cls._last_healthy_model or "None"
        now = time.time()
        failed_count = len([m for m, t in cls._failed_models.items() if t > now])
        return f"AI Status: {cls._status} | Active: {active} | Failed: {failed_count}"

# Auto-Boot
if not os.getenv("SKIP_AI_INIT"):
    AIClient.initialize()
