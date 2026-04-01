from typing import Optional

CUSTOMER_FILLER_WORDS = {
    # English
    "do", "you", "have", "any", "is", "are", "there", "available", "availability",
    "can", "i", "get", "give", "sell", "selling", "need", "want", "looking", "for",
    "please", "some", "a", "the", "today", "now", "still", "left", "stock",
    
    # Tamil Romanized Common
    "iruka", "irukaa", "irukka", "irukuma", "irukuma?", 
    "venuma", "venum", "venumaa", 
    "kedaikuma", "kidaikuma", 
    "kedaikutha", "kidaikutha", 
    "iruntha", "irunthaa", "irunthaal", 
    "sollunga", "solunga", 
    "iruka?", "venuma?",
    
    # Tamil Romanized Conversation
    "anna", "akka", "bro", "boss", "sir", "pls", "please",
    "inga", "irukinga", "irukeengala",
    "konjam", "oru", "oru packet", "oru piece",
    
    # Tamil Script
    "இருக்கா", "இருக்கு", "இருக்குமா", 
    "வேணுமா", "வேணும்", 
    "கிடைக்குமா", "கிடைக்குது", "கிடைக்குதா"
}

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
    
    reply = "LEVIX ⚡\n\n"
    
    price_val = ""
    if item.price is not None:
        price_val = int(item.price) if item.price % 1 == 0 else item.price
    price_str = f"💰 Price: ₹{price_val}" if price_val != "" else ""
    
    if state == "available":
        reply += f"{product_name_to_use} is available ✅\n"
        if price_str:
            reply += f"{price_str}\n"
        reply += "\nAnything else you need?"
    elif state == "low_stock":
        reply += f"{product_name_to_use} is available ⚠️\nOnly a few left\n"
        if price_str:
            reply += f"{price_str}\n"
        reply += "\nAnything else you need?"
    elif state == "out_of_stock":
        reply += f"{product_name_to_use} is currently out of stock ❌\nWe can notify you when it's back"
    elif state == "coming_soon":
        reply += f"{product_name_to_use} will be available soon ⏳\nStay tuned"
    elif state == "owner_check":
        reply += f"{product_name_to_use} requires confirmation from store 🧑‍💼\nChecking with owner, please wait...\n\nWe’ll update you shortly"
        
    return reply
