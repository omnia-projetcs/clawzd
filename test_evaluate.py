import asyncio
import httpx
import json

async def run():
    async with httpx.AsyncClient() as client:
        resp = await client.post("http://127.0.0.1:8000/arena/evaluate", json={
            "prompt": "Quel est le capital de la France ?",
            "responses": {
                "test_id_1": "La capitale de la France est Paris."
            },
            "provider": "local",
            "model": ""
        }, timeout=30)
        print("Status:", resp.status_code)
        print("Response:", resp.text)

asyncio.run(run())
