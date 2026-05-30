import json
import os
import sqlite3
import time

try:
    import psycopg
    from psycopg.rows import dict_row
    print("psycopg3 loaded successfully", flush=True)
except Exception as error:
    print(f"psycopg3 failed: {error}", flush=True)
    psycopg = None
    dict_row = None

from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, redirect, request, session, stream_with_context
from flask_cors import CORS
from howlongtobeatpy import HowLongToBeat

load_dotenv()

STEAM_API_KEY = os.getenv("STEAM_API_KEY")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/steam_catalog.db")
DATABASE_URL = os.getenv("DATABASE_URL")
DEFAULT_HIDDEN_GAME_NAMES = os.getenv("DEFAULT_HIDDEN_GAME_NAMES")


# Private local filter. Add Steam app IDs here through .env, for example:
# HIDDEN_APPIDS=123456,789012,1245620
HIDDEN_APPIDS = {
    int(appid.strip())
    for appid in os.getenv("HIDDEN_APPIDS", "").split(",")
    if appid.strip().isdigit()
}

# Global hidden-name filter.
# These names are hidden for everyone in the public/family view, even if the owner is not Jorge.
# You can add more from Render Environment using:
# HIDDEN_GAME_NAMES=Game One|Game Two|Game Three

def normalize_game_name(value):
    return " ".join(str(value or "").casefold().replace("’", "'").split())


HIDDEN_GAME_NAMES = {
    normalize_game_name(name)
    for name in os.getenv("HIDDEN_GAME_NAMES", "").split("|")
    if name.strip()
}

# Extra names can be provided in Render/local .env with a pipe separator.
# Pipe is safer than comma because some game titles include commas.
HIDDEN_GAME_NAMES.update({
    normalize_game_name(name)
    for name in os.getenv("HIDDEN_GAME_NAMES", "").split("|")
    if name.strip()
})


# Automatic privacy filter for Jorge's games only.
# This hides games that look adult/NSFW when Jorge is the owner.
# You can still add exact overrides in .env with HIDDEN_APPIDS.
NSFW_KEYWORDS = [
    "18+",
    "adult",
    "eroge",
    "hentai",
    "lewd",
    "mature",
    "nude",
    "nudity",
    "porn",
    "sex",
    "sexual",
    "uncensored",
    "visual novel",
    "dating sim",
    "dating",
    "romance",
    "waifu",
    "ecchi",
    "boys love",
    "girls love",
    "yuri",
    "yaoi",
]

NSFW_CATEGORY_KEYWORDS = [
    "adult",
    "mature",
    "nudity",
    "sexual content",
]

MY_STEAM_ID = "76561198108693270"

DEFAULT_FAMILY_IDS = [
    "76561198043475107",  # Diego
    "76561198388454419",  # Charly
    "76561198992948738",  # Didi
    "76561198138866290",  # Family member
    "76561198108693270",  # Jorge
    "76561198782767176",  # Family member
]

LOS_SANCHEZ_FAMILY = [
    steam_id.strip()
    for steam_id in os.getenv("FAMILY_IDS", ",".join(DEFAULT_FAMILY_IDS)).split(",")
    if steam_id.strip()
]

FAMILY_NAMES = {
    "76561198043475107": "Diego",
    "76561198388454419": "Charly",
    "76561198992948738": "Didi",
    "76561198138866290": "Family Member 4",
    "76561198108693270": "Jorge",
    "76561198782767176": "Family Member 6",
}

# Optional .env format:
# FAMILY_NAMES_JSON={"76561198043475107":"Diego","76561198388454419":"Charly"}
try:
    FAMILY_NAMES.update(json.loads(os.getenv("FAMILY_NAMES_JSON", "{}")))
except json.JSONDecodeError:
    print("Invalid FAMILY_NAMES_JSON. Using default family names.", flush=True)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-later")

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]

CORS(app, supports_credentials=True, origins=CORS_ORIGINS)

REQUEST_SLEEP_SECONDS = 0.5


def using_postgres():
    return bool(DATABASE_URL)


def get_db_connection():
    if using_postgres():
        if psycopg is None:
            raise RuntimeError(
                "DATABASE_URL is configured, but psycopg is not installed or failed to load. "
                "Run: pip install 'psycopg[binary]'"
            )

        return psycopg.connect(
            DATABASE_URL,
            row_factory=dict_row,
        )

    database_dir = os.path.dirname(DATABASE_PATH)
    if database_dir:
        os.makedirs(database_dir, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def execute_query(connection, query, params=None):
    params = params or ()

    if using_postgres():
        query = query.replace("?", "%s")

    cursor = connection.cursor()
    cursor.execute(query, params)
    return cursor


def row_has_key(row, key):
    if not row:
        return False

    if isinstance(row, dict):
        return key in row

    return key in row.keys()


def init_db():
    connection = get_db_connection()

    if using_postgres():
        cursor = connection.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS games (
                appid INTEGER PRIMARY KEY,
                name TEXT,
                type TEXT,
                genres TEXT,
                categories TEXT,
                rating TEXT,
                metacritic TEXT,
                "avgBeat" TEXT,
                hltb TEXT,
                "steamReviewSummary" TEXT,
                "steamReviewPercent" INTEGER,
                "steamReviewTotal" INTEGER,
                "releaseDate" TEXT,
                "storeUrl" TEXT,
                image TEXT,
                "requiredAge" INTEGER DEFAULT 0,
                "contentDescriptors" TEXT,
                "privacyScanVersion" INTEGER DEFAULT 0,
                "updatedAt" TEXT
            )
            """
        )

        cursor.execute(
            """
            ALTER TABLE games
            ADD COLUMN IF NOT EXISTS "requiredAge" INTEGER DEFAULT 0
            """
        )
        cursor.execute(
            """
            ALTER TABLE games
            ADD COLUMN IF NOT EXISTS "contentDescriptors" TEXT
            """
        )
        cursor.execute(
            """
            ALTER TABLE games
            ADD COLUMN IF NOT EXISTS "privacyScanVersion" INTEGER DEFAULT 0
            """
        )
        cursor.execute(
            """
            ALTER TABLE games
            ADD COLUMN IF NOT EXISTS "updatedAt" TEXT
            """
        )

        connection.commit()
        cursor.close()
        connection.close()
        return

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            appid INTEGER PRIMARY KEY,
            name TEXT,
            type TEXT,
            genres TEXT,
            categories TEXT,
            rating TEXT,
            metacritic TEXT,
            avgBeat TEXT,
            hltb TEXT,
            steamReviewSummary TEXT,
            steamReviewPercent INTEGER,
            steamReviewTotal INTEGER,
            releaseDate TEXT,
            storeUrl TEXT,
            image TEXT,
            requiredAge INTEGER DEFAULT 0,
            contentDescriptors TEXT,
            privacyScanVersion INTEGER DEFAULT 0,
            updatedAt TEXT
        )
        """
    )

    existing_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(games)").fetchall()
    }

    if "requiredAge" not in existing_columns:
        connection.execute(
            "ALTER TABLE games ADD COLUMN requiredAge INTEGER DEFAULT 0"
        )

    if "contentDescriptors" not in existing_columns:
        connection.execute(
            "ALTER TABLE games ADD COLUMN contentDescriptors TEXT"
        )

    if "privacyScanVersion" not in existing_columns:
        connection.execute(
            "ALTER TABLE games ADD COLUMN privacyScanVersion INTEGER DEFAULT 0"
        )

    connection.commit()
    connection.close()

def row_to_game(row):
    if not row:
        return None

    return {
        "appid": row["appid"],
        "name": row["name"],
        "type": row["type"],
        "genres": json.loads(row["genres"] or "[]"),
        "categories": json.loads(row["categories"] or "[]"),
        "rating": row["rating"],
        "metacritic": row["metacritic"],
        "avgBeat": row["avgBeat"],
        "hltb": json.loads(row["hltb"] or "{}"),
        "steamReviewSummary": row["steamReviewSummary"],
        "steamReviewPercent": row["steamReviewPercent"],
        "steamReviewTotal": row["steamReviewTotal"],
        "releaseDate": row["releaseDate"],
        "storeUrl": row["storeUrl"],
        "image": row["image"],
        "requiredAge": row["requiredAge"] if row_has_key(row, "requiredAge") else 0,
        "contentDescriptors": json.loads(row["contentDescriptors"] or "{}") if row_has_key(row, "contentDescriptors") else {},
        "privacyScanVersion": row["privacyScanVersion"] if row_has_key(row, "privacyScanVersion") else 0,
        "catalogUpdatedAt": row["updatedAt"],
    }


def get_cached_game(appid):
    connection = get_db_connection()
    cursor = execute_query(
        connection,
        "SELECT * FROM games WHERE appid = ?",
        (appid,),
    )
    row = cursor.fetchone()
    cursor.close()
    connection.close()

    return row_to_game(row)


def save_game_to_cache(game):
    connection = get_db_connection()

    if using_postgres():
        query = """
            INSERT INTO games (
                appid,
                name,
                type,
                genres,
                categories,
                rating,
                metacritic,
                "avgBeat",
                hltb,
                "steamReviewSummary",
                "steamReviewPercent",
                "steamReviewTotal",
                "releaseDate",
                "storeUrl",
                image,
                "requiredAge",
                "contentDescriptors",
                "privacyScanVersion",
                "updatedAt"
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(appid) DO UPDATE SET
                name = excluded.name,
                type = excluded.type,
                genres = excluded.genres,
                categories = excluded.categories,
                rating = excluded.rating,
                metacritic = excluded.metacritic,
                "avgBeat" = excluded."avgBeat",
                hltb = excluded.hltb,
                "steamReviewSummary" = excluded."steamReviewSummary",
                "steamReviewPercent" = excluded."steamReviewPercent",
                "steamReviewTotal" = excluded."steamReviewTotal",
                "releaseDate" = excluded."releaseDate",
                "storeUrl" = excluded."storeUrl",
                image = excluded.image,
                "requiredAge" = excluded."requiredAge",
                "contentDescriptors" = excluded."contentDescriptors",
                "privacyScanVersion" = excluded."privacyScanVersion",
                "updatedAt" = excluded."updatedAt"
        """
    else:
        query = """
            INSERT INTO games (
                appid,
                name,
                type,
                genres,
                categories,
                rating,
                metacritic,
                avgBeat,
                hltb,
                steamReviewSummary,
                steamReviewPercent,
                steamReviewTotal,
                releaseDate,
                storeUrl,
                image,
                requiredAge,
                contentDescriptors,
                privacyScanVersion,
                updatedAt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(appid) DO UPDATE SET
                name = excluded.name,
                type = excluded.type,
                genres = excluded.genres,
                categories = excluded.categories,
                rating = excluded.rating,
                metacritic = excluded.metacritic,
                avgBeat = excluded.avgBeat,
                hltb = excluded.hltb,
                steamReviewSummary = excluded.steamReviewSummary,
                steamReviewPercent = excluded.steamReviewPercent,
                steamReviewTotal = excluded.steamReviewTotal,
                releaseDate = excluded.releaseDate,
                storeUrl = excluded.storeUrl,
                image = excluded.image,
                requiredAge = excluded.requiredAge,
                contentDescriptors = excluded.contentDescriptors,
                privacyScanVersion = excluded.privacyScanVersion,
                updatedAt = excluded.updatedAt
        """

    params = (
        game["appid"],
        game["name"],
        game["type"],
        json.dumps(game.get("genres", [])),
        json.dumps(game.get("categories", [])),
        game.get("rating", "Unknown"),
        str(game.get("metacritic", "Unknown")),
        game.get("avgBeat", "Unknown"),
        json.dumps(game.get("hltb", {})),
        game.get("steamReviewSummary", "Unknown"),
        game.get("steamReviewPercent"),
        game.get("steamReviewTotal"),
        game.get("releaseDate", "Unknown"),
        game.get("storeUrl"),
        game.get("image"),
        game.get("requiredAge", 0),
        json.dumps(game.get("contentDescriptors", {})),
        game.get("privacyScanVersion", 2),
        datetime.now(timezone.utc).isoformat(),
    )

    cursor = connection.cursor()
    cursor.execute(query, params)
    connection.commit()
    cursor.close()
    connection.close()

def fetch_steam_owned_games(steam_id):
    print(f"Requesting Steam owned games for {steam_id}", flush=True)

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
        raise RuntimeError(response.text)

    return response.json().get("response", {}).get("games", [])


def fetch_store_details(appid):
    url = (
        "https://store.steampowered.com/api/appdetails"
        f"?appids={appid}"
        "&filters=basic,genres,metacritic,release_date,categories,content_descriptors"
    )

    response = requests.get(url, timeout=30)

    if response.status_code != 200:
        return {}

    data = response.json()
    app_data = data.get(str(appid), {})

    if not app_data.get("success"):
        return {}

    time.sleep(REQUEST_SLEEP_SECONDS)
    return app_data.get("data", {})


def fetch_steam_reviews(appid):
    url = (
        f"https://store.steampowered.com/appreviews/{appid}"
        "?json=1"
        "&language=all"
        "&purchase_type=all"
        "&num_per_page=0"
    )

    response = requests.get(url, timeout=30)

    if response.status_code != 200:
        return {
            "steamReviewSummary": "Unknown",
            "steamReviewPercent": None,
            "steamReviewTotal": None,
        }

    summary = response.json().get("query_summary", {})
    total_positive = summary.get("total_positive", 0)
    total_negative = summary.get("total_negative", 0)
    total_reviews = total_positive + total_negative

    percent = round((total_positive / total_reviews) * 100) if total_reviews else None

    time.sleep(REQUEST_SLEEP_SECONDS)

    return {
        "steamReviewSummary": summary.get("review_score_desc", "Unknown"),
        "steamReviewPercent": percent,
        "steamReviewTotal": total_reviews,
    }


def clean_game_name(name):
    replacements = [
        "™",
        "®",
        "Ⓡ",
        ": Definitive Edition",
        "Definitive Edition",
        "GOTY Edition",
        "Enhanced Edition",
        "Remastered",
        "Complete Edition",
    ]

    cleaned = name

    for replacement in replacements:
        cleaned = cleaned.replace(replacement, "")

    return cleaned.strip()


def fetch_hltb_details(game_name):
    cleaned_name = clean_game_name(game_name)

    try:
        results = HowLongToBeat().search(cleaned_name)

        if not results:
            return {}

        best_result = max(results, key=lambda result: result.similarity)

        return {
            "id": getattr(best_result, "game_id", None),
            "name": getattr(best_result, "game_name", cleaned_name),
            "mainStory": getattr(best_result, "main_story", None),
            "mainExtra": getattr(best_result, "main_extra", None),
            "completionist": getattr(best_result, "completionist", None),
            "similarity": getattr(best_result, "similarity", None),
        }

    except Exception as error:
        print(f"        HLTB lookup failed for {game_name}: {error}", flush=True)
        return {}


def format_hours(value):
    if value is None:
        return "Unknown"

    try:
        return f"{round(float(value), 1)}h"
    except (TypeError, ValueError):
        return "Unknown"


def is_hidden_appid(appid):
    try:
        return int(appid) in HIDDEN_APPIDS
    except (TypeError, ValueError):
        return False


def is_hidden_game_name(name):
    normalized_name = normalize_game_name(name)

    return any(
        hidden_name in normalized_name or normalized_name in hidden_name
        for hidden_name in HIDDEN_GAME_NAMES
    )


def is_globally_hidden_game(game):
    """Hide exact manually listed games for every viewer/owner."""
    if not game:
        return False

    if is_hidden_appid(game.get("appid")):
        return True

    return is_hidden_game_name(game.get("name", ""))


def safe_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def text_has_any_keyword(text, keywords):
    normalized = str(text or "").lower()
    return any(keyword in normalized for keyword in keywords)


def is_nsfw_or_private_game(game):
    """Detect games Jorge does not want exposed in public family mode."""
    if not game:
        return False

    if is_globally_hidden_game(game):
        return True

    appid = game.get("appid")

    if is_hidden_appid(appid):
        return True

    if safe_int(game.get("requiredAge"), 0) >= 18:
        return True

    name = game.get("name", "")
    type_value = game.get("type", "")
    genres = " ".join(game.get("genres") or [])
    categories = " ".join(game.get("categories") or [])
    descriptors = game.get("contentDescriptors") or {}
    descriptor_ids = " ".join(str(value) for value in descriptors.get("ids", []) or [])
    descriptor_notes = " ".join(descriptors.get("notes", []) or [])
    text = f"{name} {type_value} {genres} {categories} {descriptor_ids} {descriptor_notes}"

    if text_has_any_keyword(text, NSFW_KEYWORDS):
        return True

    if text_has_any_keyword(categories, NSFW_CATEGORY_KEYWORDS):
        return True

    return False


def should_hide_for_public_view(game, owner_steam_id):
    """Hide manual global names for everyone, and Jorge's detected NSFW/private games."""
    if is_globally_hidden_game(game):
        return True

    return str(owner_steam_id) == MY_STEAM_ID and is_nsfw_or_private_game(game)


def should_hide_for_public_family(game, owner_steam_id):
    """Only hide Jorge's own NSFW/private games, not other family members' games."""
    return str(owner_steam_id) == MY_STEAM_ID and is_nsfw_or_private_game(game)


def should_refresh_privacy_data(catalog_game, owner_steam_id):
    """Re-check Jorge's cached games once so older SQLite rows get adult metadata."""
    if str(owner_steam_id) != MY_STEAM_ID:
        return False

    if not catalog_game:
        return False

    return safe_int(catalog_game.get("privacyScanVersion"), 0) < 2


def remove_private_jorge_ownership(games):
    """Remove Jorge-owned NSFW/private games from the final public family result.

    If another family member also owns the same game, keep the game visible but remove
    Jorge from the owners list, so it appears as that other member's copy.
    """
    filtered_games = []
    removed_count = 0

    for game in games:
        if is_globally_hidden_game(game):
            removed_count += 1
            continue

        owners = game.get("owners") or [{
            "name": game.get("owner", "Unknown"),
            "steamId": game.get("ownerSteamId"),
            "source": game.get("source", "Unknown"),
        }]

        has_private_jorge_owner = any(
            str(owner.get("steamId")) == MY_STEAM_ID
            for owner in owners
        ) and is_nsfw_or_private_game(game)

        if not has_private_jorge_owner:
            filtered_games.append(game)
            continue

        public_owners = [
            owner for owner in owners
            if str(owner.get("steamId")) != MY_STEAM_ID
        ]

        if not public_owners:
            removed_count += 1
            continue

        game = {**game}
        game["owners"] = public_owners
        game["ownerCount"] = len(public_owners)
        first_owner = public_owners[0]
        game["owner"] = first_owner.get("name", "Unknown")
        game["ownerSteamId"] = first_owner.get("steamId")
        game["source"] = first_owner.get("source", "Steam Family")
        filtered_games.append(game)

    if removed_count:
        print(
            f"Private/NSFW filter removed {removed_count} Jorge-owned game(s).",
            flush=True,
        )

    return filtered_games, removed_count


# Backward-compatible name used by older routes.
def remove_hidden_games(games):
    filtered_games, _ = remove_private_jorge_ownership(games)
    return filtered_games


def enrich_game(appid, name):
    print(f"        Fetching store details for {name}", flush=True)
    store_data = fetch_store_details(appid)

    print(f"        Fetching Steam reviews for {name}", flush=True)
    reviews = fetch_steam_reviews(appid)

    print(f"        Fetching HLTB for {name}", flush=True)
    hltb = fetch_hltb_details(name)

    genres = [
        genre.get("description")
        for genre in store_data.get("genres", [])
        if genre.get("description")
    ]

    categories = [
        category.get("description")
        for category in store_data.get("categories", [])
        if category.get("description")
    ]

    metacritic_data = store_data.get("metacritic")
    metacritic = metacritic_data.get("score", "Unknown") if metacritic_data else "Unknown"

    type_value = ", ".join(genres[:2]) if genres else "Unknown"
    required_age = safe_int(store_data.get("required_age"), 0)
    content_descriptors = store_data.get("content_descriptors") or {}

    game = {
        "appid": appid,
        "name": name,
        "type": type_value,
        "genres": genres,
        "categories": categories,
        "rating": reviews["steamReviewSummary"],
        "metacritic": metacritic,
        "avgBeat": format_hours(hltb.get("mainStory")),
        "hltb": hltb,
        "steamReviewSummary": reviews["steamReviewSummary"],
        "steamReviewPercent": reviews["steamReviewPercent"],
        "steamReviewTotal": reviews["steamReviewTotal"],
        "releaseDate": store_data.get("release_date", {}).get("date", "Unknown"),
        "storeUrl": f"https://store.steampowered.com/app/{appid}",
        "image": f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg",
        "requiredAge": required_age,
        "contentDescriptors": content_descriptors,
        "privacyScanVersion": 2,
        "catalogUpdatedAt": datetime.now(timezone.utc).isoformat(),
    }

    save_game_to_cache(game)
    return game


def merge_user_game(steam_game, catalog_game, source="Owned", owner="Me", owner_steam_id=None):
    appid = steam_game["appid"]
    playtime_hours = round((steam_game.get("playtime_forever", 0) / 60), 1)

    return {
        **catalog_game,
        "appid": appid,
        "name": steam_game.get("name") or catalog_game.get("name") or "Unknown",
        "source": source,
        "owner": owner,
        "ownerSteamId": owner_steam_id,
        "playtime": f"{playtime_hours}h",
        "playtimeHours": playtime_hours,
        "status": "Backlog" if playtime_hours == 0 else "Played",
    }


def enrich_steam_games(steam_games, source="Owned", owner="Me", owner_steam_id=None):
    enriched_games = []
    enriched_count = 0
    cached_count = 0

    for index, steam_game in enumerate(steam_games, start=1):
        appid = steam_game["appid"]
        name = steam_game.get("name", "Unknown")

        print(
            f"[{index}/{len(steam_games)}] Processing {name} ({appid}) for {owner}",
            flush=True,
        )

        catalog_game = get_cached_game(appid)

        if catalog_game and not should_refresh_privacy_data(catalog_game, owner_steam_id):
            print(f"    Cache hit: {name}", flush=True)
            cached_count += 1
        else:
            if catalog_game:
                print(f"    Refreshing privacy data: {name}", flush=True)
            else:
                print(f"    Cache miss, enriching: {name}", flush=True)
            catalog_game = enrich_game(appid, name)
            enriched_count += 1
            print(f"    Saved to SQLite: {name}", flush=True)

        enriched_games.append(
            merge_user_game(
                steam_game=steam_game,
                catalog_game=catalog_game,
                source=source,
                owner=owner,
                owner_steam_id=owner_steam_id,
            )
        )

    return enriched_games, cached_count, enriched_count


@app.get("/")
def home():
    return jsonify({
        "status": "ok",
        "message": "Steam Library API is running",
        "routes": [
            "/api/owned-games",
            "/api/library-enriched",
            "/api/library-enriched-stream",  # Auto-loads family when steamid == MY_STEAM_ID
            "/api/family-library-enriched",
        ],
        "database": "postgresql" if DATABASE_URL else "sqlite",
        "hiddenAppIdsConfigured": len(HIDDEN_APPIDS),
        "hiddenGameNamesConfigured": len(HIDDEN_GAME_NAMES),
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

    return redirect("https://steamcommunity.com/openid/login?" + urlencode(params))


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


@app.get("/api/owned-games")
def owned_games():
    steam_id = request.args.get("steamid") or session.get("steam_id")

    if not steam_id:
        return jsonify({"error": "Missing steamid"}), 400

    if not STEAM_API_KEY:
        return jsonify({"error": "Missing STEAM_API_KEY"}), 500

    games = fetch_steam_owned_games(steam_id)
    return jsonify({"response": {"games": games}})


@app.get("/api/library-enriched")
def library_enriched():
    steam_id = request.args.get("steamid") or session.get("steam_id")

    if not steam_id:
        return jsonify({"error": "Missing steamid"}), 400

    if not STEAM_API_KEY:
        return jsonify({"error": "Missing STEAM_API_KEY"}), 500

    steam_games = fetch_steam_owned_games(steam_id)

    print(f"Found {len(steam_games)} Steam games for {steam_id}", flush=True)

    enriched_games, cached_count, enriched_count = enrich_steam_games(
        steam_games=steam_games,
        source="Owned",
        owner="Me",
        owner_steam_id=steam_id,
    )

    enriched_games = remove_hidden_games(enriched_games)
    enriched_games.sort(key=lambda game: game["name"].lower())

    return jsonify({
        "steamId": steam_id,
        "familyEnabled": False,
        "hiddenGamesFiltered": len(HIDDEN_APPIDS),
        "totalGames": len(enriched_games),
        "cachedGames": cached_count,
        "newlyEnrichedGames": enriched_count,
        "games": enriched_games,
    })


def sse_event(event_name, payload):
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


@app.get("/api/library-enriched-stream")
def library_enriched_stream():
    steam_id = request.args.get("steamid") or session.get("steam_id")

    if not steam_id:
        return jsonify({"error": "Missing steamid"}), 400

    if not STEAM_API_KEY:
        return jsonify({"error": "Missing STEAM_API_KEY"}), 500

    @stream_with_context
    def generate():
        family_enabled = steam_id == MY_STEAM_ID
        steam_ids_to_scan = LOS_SANCHEZ_FAMILY if family_enabled else [steam_id]
        family_name = "Los Sanchez" if family_enabled else None

        all_games_by_appid = {}
        members = []
        total_cached_count = 0
        total_enriched_count = 0
        processed_games = 0
        total_games_to_process = 0

        try:
            yield sse_event("progress", {
                "stage": "connected",
                "message": "Connected to backend...",
                "percent": 1,
                "processedGames": 0,
                "totalGamesToProcess": 0,
                "currentMember": None,
                "currentGame": None,
                "cachedGames": 0,
                "newlyEnrichedGames": 0,
            })

            if family_enabled:
                print("Family stream mode enabled for Jorge", flush=True)
                start_message = "Loading Steam Family libraries..."
            else:
                print(f"Family stream mode disabled for {steam_id}. Loading only own library.", flush=True)
                start_message = "Loading your Steam library..."

            yield sse_event("progress", {
                "stage": "loading-members",
                "message": start_message,
                "percent": 2,
                "processedGames": 0,
                "totalGamesToProcess": 0,
                "currentMember": None,
                "currentGame": None,
                "cachedGames": 0,
                "newlyEnrichedGames": 0,
            })

            # First pass: load all available Steam libraries so we know the total.
            member_libraries = []

            for member_index, member_steam_id in enumerate(steam_ids_to_scan, start=1):
                owner_name = FAMILY_NAMES.get(member_steam_id, member_steam_id)

                yield sse_event("progress", {
                    "stage": "loading-member-library",
                    "message": f"Requesting Steam library for {owner_name}...",
                    "percent": 2,
                    "processedGames": 0,
                    "totalGamesToProcess": total_games_to_process,
                    "currentMember": owner_name,
                    "currentGame": None,
                    "cachedGames": total_cached_count,
                    "newlyEnrichedGames": total_enriched_count,
                })

                try:
                    steam_games = fetch_steam_owned_games(member_steam_id)
                except Exception as error:
                    print(
                        f"Could not load library for {owner_name} ({member_steam_id}): {error}",
                        flush=True,
                    )
                    members.append({
                        "steamId": member_steam_id,
                        "name": owner_name,
                        "loaded": False,
                        "gameCount": 0,
                        "error": str(error),
                    })
                    continue

                print(
                    f"Found {len(steam_games)} Steam games for {owner_name} ({member_steam_id})",
                    flush=True,
                )

                members.append({
                    "steamId": member_steam_id,
                    "name": owner_name,
                    "loaded": True,
                    "gameCount": len(steam_games),
                })

                total_games_to_process += len(steam_games)
                member_libraries.append({
                    "steamId": member_steam_id,
                    "name": owner_name,
                    "games": steam_games,
                })

                yield sse_event("progress", {
                    "stage": "member-library-loaded",
                    "message": f"Found {len(steam_games)} games for {owner_name}.",
                    "percent": 3,
                    "processedGames": 0,
                    "totalGamesToProcess": total_games_to_process,
                    "currentMember": owner_name,
                    "currentGame": None,
                    "cachedGames": total_cached_count,
                    "newlyEnrichedGames": total_enriched_count,
                })

            if total_games_to_process == 0:
                yield sse_event("complete", {
                    "steamId": steam_id,
                    "familyEnabled": family_enabled,
                    "familyName": family_name,
                    "members": members,
                    "totalGames": 0,
                    "ownedGames": 0,
                    "familyGames": 0,
                    "cachedGames": 0,
                    "newlyEnrichedGames": 0,
                    "games": [],
                })
                return

            # Second pass: enrich/cache each game and dedupe by appid.
            for member_library in member_libraries:
                member_steam_id = member_library["steamId"]
                owner_name = member_library["name"]
                steam_games = member_library["games"]
                is_requesting_user = member_steam_id == steam_id
                source = "Owned" if is_requesting_user else "Steam Family"
                owner = "Me" if is_requesting_user else owner_name

                for game_index, steam_game in enumerate(steam_games, start=1):
                    appid = steam_game["appid"]
                    name = steam_game.get("name", "Unknown")
                    processed_games += 1
                    percent = min(99, 3 + round((processed_games / total_games_to_process) * 96))

                    yield sse_event("progress", {
                        "stage": "processing-game",
                        "message": f"Processing {name} for {owner_name}...",
                        "percent": percent,
                        "processedGames": processed_games,
                        "totalGamesToProcess": total_games_to_process,
                        "currentMember": owner_name,
                        "currentGame": name,
                        "cachedGames": total_cached_count,
                        "newlyEnrichedGames": total_enriched_count,
                    })

                    catalog_game = get_cached_game(appid)

                    if catalog_game:
                        total_cached_count += 1
                        action = "Cache hit"
                    else:
                        action = "Enriching"

                        yield sse_event("progress", {
                            "stage": "enriching-game",
                            "message": f"Enriching {name}...",
                            "percent": percent,
                            "processedGames": processed_games,
                            "totalGamesToProcess": total_games_to_process,
                            "currentMember": owner_name,
                            "currentGame": name,
                            "cachedGames": total_cached_count,
                            "newlyEnrichedGames": total_enriched_count,
                        })

                        catalog_game = enrich_game(appid, name)
                        total_enriched_count += 1

                    if should_hide_for_public_view(catalog_game, member_steam_id):
                        print(
                            f"    Hidden from public family view: {name} ({appid})",
                            flush=True,
                        )
                        yield sse_event("progress", {
                            "stage": "game-hidden",
                            "message": f"Hidden private game from public family view.",
                            "percent": percent,
                            "processedGames": processed_games,
                            "totalGamesToProcess": total_games_to_process,
                            "currentMember": owner_name,
                            "currentGame": None,
                            "cachedGames": total_cached_count,
                            "newlyEnrichedGames": total_enriched_count,
                        })
                        continue

                    merged_game = merge_user_game(
                        steam_game=steam_game,
                        catalog_game=catalog_game,
                        source=source,
                        owner=owner,
                        owner_steam_id=member_steam_id,
                    )

                    if appid not in all_games_by_appid:
                        all_games_by_appid[appid] = merged_game
                    else:
                        existing_game = all_games_by_appid[appid]

                        owners = existing_game.get("owners", [])
                        if not owners:
                            owners = [{
                                "name": existing_game.get("owner", "Unknown"),
                                "steamId": existing_game.get("ownerSteamId"),
                                "source": existing_game.get("source", "Unknown"),
                            }]

                        if not any(owner_info.get("steamId") == member_steam_id for owner_info in owners):
                            owners.append({
                                "name": owner,
                                "steamId": member_steam_id,
                                "source": source,
                            })

                        existing_game["owners"] = owners
                        existing_game["ownerCount"] = len(owners)

                        # Prefer the requesting user's owned copy when duplicate exists.
                        if is_requesting_user:
                            merged_game["owners"] = owners
                            merged_game["ownerCount"] = len(owners)
                            all_games_by_appid[appid] = merged_game

                    yield sse_event("progress", {
                        "stage": "game-done",
                        "message": f"{action}: {name}",
                        "percent": percent,
                        "processedGames": processed_games,
                        "totalGamesToProcess": total_games_to_process,
                        "currentMember": owner_name,
                        "currentGame": name,
                        "cachedGames": total_cached_count,
                        "newlyEnrichedGames": total_enriched_count,
                    })

            all_games = list(all_games_by_appid.values())

            for game in all_games:
                if "owners" not in game:
                    game["owners"] = [{
                        "name": game.get("owner", "Unknown"),
                        "steamId": game.get("ownerSteamId"),
                        "source": game.get("source", "Unknown"),
                    }]
                game["ownerCount"] = len(game["owners"])

            all_games, private_filtered_count = remove_private_jorge_ownership(all_games)
            all_games.sort(key=lambda game: game["name"].lower())

            owned_games = sum(1 for game in all_games if game.get("source") == "Owned")
            family_games = sum(1 for game in all_games if game.get("source") == "Steam Family")

            yield sse_event("complete", {
                "steamId": steam_id,
                "familyEnabled": family_enabled,
                "familyName": family_name,
                "members": members,
                "hiddenAppIdsConfigured": len(HIDDEN_APPIDS),
                "hiddenGameNamesConfigured": len(HIDDEN_GAME_NAMES),
                "privateGamesFiltered": private_filtered_count,
                "totalGames": len(all_games),
                "ownedGames": owned_games,
                "familyGames": family_games,
                "cachedGames": total_cached_count,
                "newlyEnrichedGames": total_enriched_count,
                "games": all_games,
            })

        except Exception as error:
            print(f"Stream failed: {error}", flush=True)
            yield sse_event("progress", {
                "stage": "error",
                "message": str(error),
                "percent": 0,
                "processedGames": processed_games,
                "totalGamesToProcess": total_games_to_process,
                "currentMember": None,
                "currentGame": None,
                "cachedGames": total_cached_count,
                "newlyEnrichedGames": total_enriched_count,
            })
            yield sse_event("error", {
                "stage": "error",
                "message": str(error),
                "percent": 0,
            })

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/family-library-enriched")
def family_library_enriched():
    steam_id = request.args.get("steamid") or session.get("steam_id")

    if not steam_id:
        return jsonify({"error": "Missing steamid"}), 400

    if not STEAM_API_KEY:
        return jsonify({"error": "Missing STEAM_API_KEY"}), 500

    family_enabled = steam_id == MY_STEAM_ID
    steam_ids_to_scan = LOS_SANCHEZ_FAMILY if family_enabled else [steam_id]

    if family_enabled:
        print("Family mode enabled for Jorge", flush=True)
    else:
        print(f"Family mode disabled for {steam_id}. Loading only own library.", flush=True)

    all_games_by_appid = {}
    members = []
    total_cached_count = 0
    total_enriched_count = 0

    for member_steam_id in steam_ids_to_scan:
        owner_name = FAMILY_NAMES.get(member_steam_id, member_steam_id)
        is_requesting_user = member_steam_id == steam_id
        source = "Owned" if is_requesting_user else "Steam Family"
        owner = "Me" if is_requesting_user else owner_name

        print(f"Loading library for {owner_name} ({member_steam_id})", flush=True)

        try:
            steam_games = fetch_steam_owned_games(member_steam_id)
        except Exception as error:
            print(
                f"Could not load library for {owner_name} ({member_steam_id}): {error}",
                flush=True,
            )
            members.append({
                "steamId": member_steam_id,
                "name": owner_name,
                "loaded": False,
                "gameCount": 0,
                "error": str(error),
            })
            continue

        print(
            f"Found {len(steam_games)} Steam games for {owner_name} ({member_steam_id})",
            flush=True,
        )

        members.append({
            "steamId": member_steam_id,
            "name": owner_name,
            "loaded": True,
            "gameCount": len(steam_games),
        })

        enriched_games, cached_count, enriched_count = enrich_steam_games(
            steam_games=steam_games,
            source=source,
            owner=owner,
            owner_steam_id=member_steam_id,
        )

        total_cached_count += cached_count
        total_enriched_count += enriched_count

        for game in enriched_games:
            if should_hide_for_public_view(game, member_steam_id):
                print(
                    f"    Hidden from public family view: {game.get('name')} ({game.get('appid')})",
                    flush=True,
                )
                continue

            appid = game["appid"]

            if appid not in all_games_by_appid:
                all_games_by_appid[appid] = game
                continue

            existing_game = all_games_by_appid[appid]

            owners = existing_game.get("owners", [])
            if not owners:
                owners = [{
                    "name": existing_game.get("owner", "Unknown"),
                    "steamId": existing_game.get("ownerSteamId"),
                    "source": existing_game.get("source", "Unknown"),
                }]

            if not any(owner_info.get("steamId") == member_steam_id for owner_info in owners):
                owners.append({
                    "name": owner,
                    "steamId": member_steam_id,
                    "source": source,
                })

            existing_game["owners"] = owners
            existing_game["ownerCount"] = len(owners)

            # If the requesting user owns the game, prefer showing it as Owned.
            if is_requesting_user:
                game["owners"] = owners
                game["ownerCount"] = len(owners)
                all_games_by_appid[appid] = game

    all_games = list(all_games_by_appid.values())

    for game in all_games:
        if "owners" not in game:
            game["owners"] = [{
                "name": game.get("owner", "Unknown"),
                "steamId": game.get("ownerSteamId"),
                "source": game.get("source", "Unknown"),
            }]
        game["ownerCount"] = len(game["owners"])

    all_games, private_filtered_count = remove_private_jorge_ownership(all_games)
    all_games.sort(key=lambda game: game["name"].lower())

    return jsonify({
        "steamId": steam_id,
        "familyEnabled": family_enabled,
        "familyName": "Los Sanchez" if family_enabled else None,
        "members": members,
        "hiddenAppIdsConfigured": len(HIDDEN_APPIDS),
        "hiddenGameNamesConfigured": len(HIDDEN_GAME_NAMES),
        "privateGamesFiltered": private_filtered_count,
        "totalGames": len(all_games),
        "cachedGames": total_cached_count,
        "newlyEnrichedGames": total_enriched_count,
        "games": all_games,
    })


init_db()

if __name__ == "__main__":
    print(f"DATABASE_PATH = {os.path.abspath(DATABASE_PATH)}", flush=True)
    print(f"Database engine: {'PostgreSQL' if DATABASE_URL else 'SQLite'}", flush=True)
    print(f"Hidden AppIDs configured: {len(HIDDEN_APPIDS)}", flush=True)
    print(f"Hidden game names configured: {len(HIDDEN_GAME_NAMES)}", flush=True)
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
    )
