import os
import json
import base64
import requests


def get_flume_connection() -> tuple[dict, str]:
    """Authenticate with Flume and return (headers, query_url).

    Reads credentials from env vars. Raises SystemExit on auth failure
    so callers don't need to handle the error path.
    """
    auth = requests.post(
        "https://api.flumetech.com/oauth/token",
        data={
            "grant_type": "password",
            "client_id": os.getenv("FLUME_CLIENT_ID"),
            "client_secret": os.getenv("FLUME_CLIENT_SECRET"),
            "username": os.getenv("FLUME_USERNAME"),
            "password": os.getenv("FLUME_PASSWORD"),
        }
    )
    auth_resp = auth.json()
    if auth.status_code != 200 or not auth_resp.get("data"):
        print(f"❌ Flume auth failed ({auth.status_code}): {auth_resp}")
        raise SystemExit(1)

    access_token = auth_resp["data"][0]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    user_id = json.loads(
        base64.urlsafe_b64decode(access_token.split(".")[1] + "==")
    )["user_id"]

    devices = requests.get(
        f"https://api.flumetech.com/users/{user_id}/devices", headers=headers
    ).json()
    type2 = [d for d in devices["data"] if d["type"] == 2]
    if not type2:
        print("❌ No Flume water monitor device (type 2) found on this account")
        raise SystemExit(1)
    device_id = type2[0]["id"]
    query_url = f"https://api.flumetech.com/users/{user_id}/devices/{device_id}/query"

    return headers, query_url
