import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

email_user = os.getenv("EMAIL_USER")
email_pass = os.getenv("EMAIL_PASS")

print(f"EMAIL_USER: {email_user}")
print(f"EMAIL_PASS: {'*' * len(email_pass) if email_pass else 'None'}")

msg = EmailMessage()
msg['Subject'] = 'Test Verification'
msg['From'] = f"Levix <{email_user}>"
msg['To'] = "levixsupport@gmail.com" # Send to itself to test

msg.set_content("This is a test.")

try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        # server.set_debuglevel(1)
        server.login(email_user, email_pass)
        server.send_message(msg)
    print("Success")
except Exception as e:
    print(f"Error: {e}")
