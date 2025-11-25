import os
from dotenv import load_dotenv
import requests
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
# SENDER_EMAIL = os.getenv("SERVER_EMAIL")

# def send_email(to_email, subject, message):
#     try:
#         """
#         Sends an email using SendGrid API.
#         """
#         print (SENDGRID_API_KEY , SENDER_EMAIL, subject , message)
#         url = "https://api.sendgrid.com/v3/mail/send"
#         headers = {
#                 "Authorization": f"Bearer {SENDGRID_API_KEY}",
#                 "Content-Type": "application/json"
#             }
#
#         data = {
#                 "personalizations": [{
#                     "to": [{"email": to_email}],
#                     "subject": subject
#                 }],
#                 "from": {"email": SENDER_EMAIL},
#                 "content": [{"type": "text/plain", "value": message}]
#             }
#
#         response = requests.post(url, headers=headers, json=data)
#         print(response.status_code, response.text)
#     except Exception as e:
#         print(f"Email sending error: {e}")
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import logging

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
def send_email_api(to_email: str, subject: str, html_content: str) -> bool:
    """
    Sends an email with HTML content using SMTP.

    Args:
        to_email: The recipient's email address
        subject: The email subject
        html_content: The HTML content of the email

    Returns:
        bool: True if the email was sent successfully, False otherwise
    """
    try:
        if not SENDER_EMAIL or not SENDER_PASSWORD:
            logger.error("SMTP sender email or password not configured")
            return False

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = SENDER_EMAIL
        message["To"] = to_email

        html_part = MIMEText(html_content, "html")
        message.attach(html_part)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(message)

        logger.info(f"Email sent successfully to {to_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False
