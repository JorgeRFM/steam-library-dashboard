import os
import requests
from urllib.parse import urlencode

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, session
from flask_cors import CORS

load_dotenv()

STEAM_API_KEY = os.getenv("STEAM_API_KEY")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-later")

CORS(app, supports_credentials=True)


@app.get("/")
def home():
    return jsonify({
        "status": "ok",
        "message": "Steam Library API is running"
    })


@app.get("/auth/steam")
def auth_steam():
    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": f"{BACKEND_URL}/auth/steam/callback",
        "openid.realm": BACKEND_URL,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }

    steam_login_url = "https://steamcommunity.com/openid/login?" + urlencode(params)
    return redirect(steam_login_url)


@app.get("/auth/steam/callback")
def auth_steam_callback():
    validation_params = request.args.to_dict()
    validation_params["openid.mode"] = "check_authentication"

    response = requests.post(
        "https://steamcommunity.com/openid/login",
        data=validation_params,
        timeout=15,
    )

    if "is_valid:true" not in response.text:
        return jsonify({"error": "Steam login validation failed"}), 401

    claimed_id = request.args.get("openid.claimed_id", "")
    steam_id = claimed_id.rstrip("/").split("/")[-1]

    session["steam_id"] = steam_id

    return redirect(f"{FRONTEND_URL}?steamid={steam_id}")


@app.get("/api/me")
def me():
    steam_id = session.get("steam_id")

    if not steam_id:
        return jsonify({"loggedIn": False})

    return jsonify({
        "loggedIn": True,
        "steamId": steam_id
    })


@app.get("/api/owned-games")
def owned_games():
    steam_id = request.args.get("steamid") or session.get("steam_id")

    if not steam_id:
        return jsonify({"error": "Missing steamid"}), 400

    if not STEAM_API_KEY:
        return jsonify({"error": "Missing STEAM_API_KEY"}), 500

    url = (
        "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
        f"?key={STEAM_API_KEY}"
        f"&steamid={steam_id}"
        "&include_appinfo=true"
        "&include_played_free_games=true"
        "&format=json"
    )

    response = requests.get(url, timeout=30)

    if response.status_code != 200:
        return jsonify({
            "error": "Steam API request failed",
            "statusCode": response.status_code,
            "details": response.text
        }), response.status_code

    return jsonify(response.json())


if __name__ == "__main__":
    app.run(debug=True, port=5000)