
def detect_quantity(user_msg):
    quantity = 1
    qty_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    msg_low_words = user_msg.lower().split()
    for word in msg_low_words:
        clean_word = word.strip("?,.!")
        if clean_word.isdigit():
            quantity = int(clean_word)
            break
        elif clean_word in qty_map:
            quantity = qty_map[clean_word]
            break
    return quantity

test_cases = [
    ("2 chicken briyani", 2),
    ("two chicken briyani", 2),
    ("chicken briyani", 1),
    ("give me one chicken briyani", 1),
    ("ten burgers please", 10),
    ("3 piece chicken", 3)
]

for msg, expected in test_cases:
    actual = detect_quantity(msg)
    print(f"Msg: '{msg}' | Expected: {expected} | Actual: {actual} | {'PASS' if actual == expected else 'FAIL'}")

def is_noise(text):
    special_chars = sum(1 for c in text if not c.isalnum() and c != ' ')
    if special_chars > 3:
        return True
    words = text.split()
    if all(len(w) < 3 for w in words):
        return True
    # NEW RULE: Reject if < 5 chars and entirely alpha (e.g. 'afbu')
    if len(text.strip()) < 5 and text.strip().isalpha():
        return True
    return False

noise_tests = [
    ("afbu", True),
    ("rice", True),
    ("pizza", False),
    ("mutton pizza", False),
    ("asdfghj", False), # passes noise filter, blocked by no-vowel gate instead
    ("a b c", True)
]

print("\nNoise Tests:")
for text, expected in noise_tests:
    actual = is_noise(text)
    print(f"Text: '{text}' | Expected: {expected} | Actual: {actual} | {'PASS' if actual == expected else 'FAIL'}")
