from typing import Optional
import re

CUSTOMER_FILLER_WORDS = {
    # English
    "hi", "hello", "do", "you", "have", "any", "is", "are", "there", "available", "availability",
    "can", "i", "get", "give", "take", "sell", "selling", "need", "want", "buy", "looking", "for",
    "please", "some", "a", "the", "today", "now", "still", "left", "stock",
    
    # Tamil Romanized Common
    "iruka", "irukaa", "irukka", "irukuma", "irukuma?", 
    "venuma", "venum", "venumaa", 
    "kedaikuma", "kidaikuma", 
    "kedaikutha", "kidaikutha", 
    "iruntha", "irunthaa", "irunthaal", 
    "sollunga", "solunga", 
    "iruka?", "venuma?", "venumaa?",
    
    # Hindi Romanized
    "chahiye", "hai", "kya", "mil", "jayega", "milega", "hai kya", "chaiye",
    
    # Tamil Romanized Conversation
    "anna", "akka", "bro", "boss", "sir", "pls", "please",
    "inga", "irukinga", "irukeengala", "vanganum",
    
    # Quantity words (to be removed)
    "rendu", "oru", "ek", "onnu", "two", "one", "piece", "packet", "kg", "gram",
}

def normalize_conversational_input(message: str) -> str:
    """
    Standardizes multilingual input for better intent and product detection.
    """
    msg = message.lower().strip()
    
    # Intent Triggers (transliterated)
    triggers = ["venum", "iruka", "chahiye", "hai kya", "chaiye", "irukka", "venuma"]
    
    # Simple normalization mappings
    msg = msg.replace("chahiye", "want")
    msg = msg.replace("hai kya", "is there")
    msg = msg.replace("venum", "need")
    
    # Clean punctuations
    msg = re.sub(r'[^\w\s]', ' ', msg)
    
    return msg.strip()

def filter_filler_words(message: str) -> str:
    """
    Strips multilingual customer filler phrases from a message string to isolate the product name.
    Handles exact multi-word fillers and single word fillers dynamically.
    """
    msg_lower = message.lower()
    
    # Handle specific multi-word phrases explicitly before splitting
    multi_word_fillers = ["oru packet", "oru piece"]
    for mw_filler in multi_word_fillers:
        msg_lower = msg_lower.replace(mw_filler, "")
        
    words = msg_lower.split()
    filtered_words = []
    
    for word in words:
        # Strip trailing punctuation for the comparison
        clean_word = word.strip("?,.!")
        if clean_word not in CUSTOMER_FILLER_WORDS and word not in CUSTOMER_FILLER_WORDS:
            filtered_words.append(word)
            
    filtered_message = " ".join(filtered_words)
    return filtered_message.strip()

def generate_reply(item, state: str, product_name: Optional[str] = None) -> str:
    """
    Generates a natural shop-style response message based on product state.
    States: available, low_stock, out_of_stock, coming_soon, owner_check.
    """
    product_name_to_use = product_name if product_name else item.name
    
    price_val = ""
    if item.price is not None:
        price_val = int(item.price) if item.price % 1 == 0 else item.price
    
    if state == "available":
        res = f"Yes, we have {product_name_to_use}! "
        if price_val:
            res += f"It is ₹{price_val}. "
        res += "Do you want to order?"
        return res
    elif state == "low_stock":
        res = f"Only few left for {product_name_to_use}. "
        if price_val:
            res += f"It is ₹{price_val}. "
        res += "Do you want it before it finishes?"
        return res
    elif state == "out_of_stock":
        return f"Sorry, {product_name_to_use} is out of stock now. I will message you when it is back!"
    elif state == "coming_soon":
        return f"{product_name_to_use} is coming soon! I will tell you."
    elif state == "owner_check":
        return f"Checking with the shop owner for {product_name_to_use}. Please wait 1 minute."
        
    return f"Yes, {product_name_to_use} is available. Do you want anything else?"
