import logging
import httpx
import smtplib
from email.message import EmailMessage

from config import (
    TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET,
    LINKEDIN_ACCESS_TOKEN, LINKEDIN_AUTHOR_ID,
    MEDIUM_INTEGRATION_TOKEN, MEDIUM_AUTHOR_ID,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, NOTIFICATION_EMAIL,
    N8N_WEBHOOK_URL
)

logger = logging.getLogger("clawzd.social")

async def send_email(subject: str, body: str, to_email: str = None) -> dict:
    """Send an email using SMTP."""
    recipient = to_email or NOTIFICATION_EMAIL
    if not SMTP_HOST or not recipient:
        return {"error": "SMTP not configured or no recipient provided"}

    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = SMTP_USER or "clawzd@localhost"
        msg['To'] = recipient

        # Use run_in_executor to avoid blocking the event loop
        import asyncio
        loop = asyncio.get_running_loop()

        def _send():
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                if SMTP_USER and SMTP_PASSWORD:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)

        await loop.run_in_executor(None, _send)
        return {"status": "success", "message": f"Email sent to {recipient}"}
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        return {"error": str(e)}

async def post_to_twitter(text: str) -> dict:
    """Post a tweet using the Twitter v2 API via tweepy."""
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
        return {"error": "Twitter API credentials missing"}

    try:
        import tweepy
        import asyncio
        loop = asyncio.get_running_loop()

        def _post():
            client = tweepy.Client(
                consumer_key=TWITTER_API_KEY,
                consumer_secret=TWITTER_API_SECRET,
                access_token=TWITTER_ACCESS_TOKEN,
                access_token_secret=TWITTER_ACCESS_SECRET
            )
            response = client.create_tweet(text=text)
            return response.data

        result = await loop.run_in_executor(None, _post)
        return {"status": "success", "data": result}

    except ImportError:
        logger.warning("tweepy not installed. Simulating Twitter post.")
        return {"status": "simulated_success", "message": "Twitter post simulated (missing tweepy)", "text": text}
    except Exception as e:
        logger.error("Failed to post to Twitter: %s", e)
        return {"error": str(e)}

async def post_to_linkedin(text: str) -> dict:
    """Post to LinkedIn."""
    if not LINKEDIN_ACCESS_TOKEN or not LINKEDIN_AUTHOR_ID:
        return {"error": "LinkedIn API credentials missing"}

    try:
        url = "https://api.linkedin.com/v2/ugcPosts"
        headers = {
            "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json"
        }
        payload = {
            "author": LINKEDIN_AUTHOR_ID,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {
                        "text": text
                    },
                    "shareMediaCategory": "NONE"
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return {"status": "success", "data": resp.json()}

    except Exception as e:
        logger.error("Failed to post to LinkedIn: %s", e)
        return {"error": str(e)}

async def post_to_medium(title: str, content: str, tags: list = None, publish_status: str = "draft") -> dict:
    """Post an article to Medium."""
    if not MEDIUM_INTEGRATION_TOKEN:
        return {"error": "Medium API token missing"}

    try:
        async with httpx.AsyncClient() as client:
            # First, get the user ID if not provided
            author_id = MEDIUM_AUTHOR_ID
            if not author_id:
                user_resp = await client.get(
                    "https://api.medium.com/v1/me",
                    headers={"Authorization": f"Bearer {MEDIUM_INTEGRATION_TOKEN}"}
                )
                user_resp.raise_for_status()
                author_id = user_resp.json().get("data", {}).get("id")

            if not author_id:
                return {"error": "Could not retrieve Medium Author ID"}

            # Post the article
            url = f"https://api.medium.com/v1/users/{author_id}/posts"
            headers = {
                "Authorization": f"Bearer {MEDIUM_INTEGRATION_TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            payload = {
                "title": title,
                "contentFormat": "markdown",
                "content": content,
                "tags": tags or [],
                "publishStatus": publish_status
            }

            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return {"status": "success", "data": resp.json()}

    except Exception as e:
        logger.error("Failed to post to Medium: %s", e)
        return {"error": str(e)}

async def trigger_n8n_webhook(payload: dict) -> dict:
    """Send data to an n8n webhook."""
    if not N8N_WEBHOOK_URL:
        return {"error": "n8n webhook URL is not configured"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(N8N_WEBHOOK_URL, json=payload)
            resp.raise_for_status()
            try:
                data = resp.json()
            except Exception:
                data = resp.text
            return {"status": "success", "data": data}

    except Exception as e:
        logger.error("Failed to trigger n8n webhook: %s", e)
        return {"error": str(e)}
