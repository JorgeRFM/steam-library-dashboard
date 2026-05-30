import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from dotenv import load_dotenv
from howlongtobeatpy import HowLongToBeat

load_dotenv()

STEAM_API_KEY = os.getenv("STEAM_API_KEY")
STEAM_ID = os.getenv("STEAM_ID")
STEAM_VANITY = os.getenv("STEAM_VANITY", "JrogrFRM")

CATALOG_PATH = "src/data/game_catalog.json"
USER_LIBRARY_PATH = "src/data/user_library.json"
FAMILY_LIBRARY_PATH = "src/data/family_library.json"
MERGED_OUTPUT_PATH = "src/data/games.json"

REQUEST_SLEEP_SECONDS = 0.8
HLTB_SLEEP_SECONDS = 1.0
MAX_RETRIES = 3


def load_json_file(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return {}

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError:
        print(f"Warning: {path} is invalid JSON. Starting empty.")
        return {}


def save_json_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def safe_fetch_json(url):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fetch_json(url)
        except urllib.error.HTTPError as error:
            if error.code == 429:
                wait_seconds = 10 * attempt
                print(f"Rate limited. Waiting {wait_seconds}s...")
                time.sleep(wait_seconds)
                continue

            print(f"HTTP error {error.code}: {url}")
            return None
        except Exception as error:
            print(f"Request failed: {error}")
            return None

    return None


def resolve_steam_id():
    if STEAM_ID:
        return STEAM_ID

    url = (
        "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/"
        f"?key={STEAM_API_KEY}"
        f"&vanityurl={urllib.parse.quote(STEAM_VANITY)}"
    )

    data = fetch_json(url)
    response = data.get("response", {})

    if response.get("success") != 1:
        raise RuntimeError(f"Could not resolve Steam vanity URL: {response}")

    return response["steamid"]


def fetch_owned_games(steam_id):
    url = (
        "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
        f"?key={STEAM_API_KEY}"
        f"&steamid={steam_id}"
        "&include_appinfo=true"
        "&include_played_free_games=true"
        "&format=json"
    )

    return fetch_json(url)


def fetch_store_details(appid):
    url = (
        "https://store.steampowered.com/api/appdetails"
        f"?appids={appid}"
        "&filters=basic,genres,metacritic,release_date,categories"
    )

    data = safe_fetch_json(url)

    if not data:
        return {}

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

    data = safe_fetch_json(url)

    if not data:
        return {
            "steamReviewSummary": "Unknown",
            "steamReviewPercent": None,
            "steamReviewTotal": None,
        }

    summary = data.get("query_summary", {})
    total_positive = summary.get("total_positive", 0)
    total_negative = summary.get("total_negative", 0)
    total_reviews = total_positive + total_negative

    percent = round((total_positive / total_reviews) * 100) if total_reviews > 0 else None

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
            time.sleep(HLTB_SLEEP_SECONDS)
            return {}

        best_result = max(results, key=lambda result: result.similarity)

        time.sleep(HLTB_SLEEP_SECONDS)

        return {
            "hltbId": getattr(best_result, "game_id", None),
            "hltbName": getattr(best_result, "game_name", cleaned_name),
            "mainStory": getattr(best_result, "main_story", None),
            "mainExtra": getattr(best_result, "main_extra", None),
            "completionist": getattr(best_result, "completionist", None),
            "similarity": getattr(best_result, "similarity", None),
        }

    except Exception as error:
        print(f"Could not fetch HLTB for {game_name}: {error}")
        time.sleep(HLTB_SLEEP_SECONDS)
        return {}


def get_genres(store_data):
    return [
        genre.get("description")
        for genre in store_data.get("genres", [])
        if genre.get("description")
    ]


def get_categories(store_data):
    return [
        category.get("description")
        for category in store_data.get("categories", [])
        if category.get("description")
    ]


def get_metacritic(store_data):
    metacritic = store_data.get("metacritic")
    return metacritic.get("score", "Unknown") if metacritic else "Unknown"


def format_hours(value):
    if value is None:
        return "Unknown"

    try:
        return f"{round(float(value), 1)}h"
    except (TypeError, ValueError):
        return "Unknown"


def catalog_needs_store_update(entry):
    return (
        not entry
        or entry.get("type") in [None, "", "Unknown"]
        or not entry.get("genres")
        or entry.get("releaseDate") in [None, "", "Unknown"]
    )


def catalog_needs_hltb_update(entry):
    return not entry or entry.get("avgBeat") in [None, "", "Unknown"]


def catalog_needs_review_update(entry):
    return (
        not entry
        or entry.get("steamReviewSummary") in [None, "", "Unknown"]
        or entry.get("steamReviewPercent") is None
        or entry.get("steamReviewTotal") is None
    )


def build_catalog_entry(game, existing_entry=None):
    appid = game["appid"]
    name = game.get("name", "Unknown")
    existing_entry = existing_entry or {}

    print(f"  Checking catalog data for {name}")

    if catalog_needs_store_update(existing_entry):
        print("    Updating Steam Store details")
        store_data = fetch_store_details(appid)

        genres = get_genres(store_data)
        categories = get_categories(store_data)
        metacritic = get_metacritic(store_data)
        release_date = store_data.get("release_date", {}).get("date", "Unknown")
    else:
        genres = existing_entry.get("genres", [])
        categories = existing_entry.get("categories", [])
        metacritic = existing_entry.get("metacritic", "Unknown")
        release_date = existing_entry.get("releaseDate", "Unknown")

    if catalog_needs_hltb_update(existing_entry):
        print("    Updating HowLongToBeat")
        hltb_data = fetch_hltb_details(name)
        avg_beat = format_hours(hltb_data.get("mainStory"))
        hltb = {
            "id": hltb_data.get("hltbId"),
            "name": hltb_data.get("hltbName"),
            "mainStory": hltb_data.get("mainStory"),
            "mainExtra": hltb_data.get("mainExtra"),
            "completionist": hltb_data.get("completionist"),
            "similarity": hltb_data.get("similarity"),
        }
    else:
        avg_beat = existing_entry.get("avgBeat", "Unknown")
        hltb = existing_entry.get("hltb", {})

    if catalog_needs_review_update(existing_entry):
        print("    Updating Steam reviews")
        review_data = fetch_steam_reviews(appid)
    else:
        review_data = {
            "steamReviewSummary": existing_entry.get("steamReviewSummary", "Unknown"),
            "steamReviewPercent": existing_entry.get("steamReviewPercent"),
            "steamReviewTotal": existing_entry.get("steamReviewTotal"),
        }

    type_value = ", ".join(genres[:2]) if genres else "Unknown"

    return {
        "appid": appid,
        "name": name,
        "type": type_value,
        "genres": genres,
        "categories": categories,
        "rating": review_data["steamReviewSummary"],
        "metacritic": metacritic,
        "avgBeat": avg_beat,
        "hltb": hltb,
        "steamReviewSummary": review_data["steamReviewSummary"],
        "steamReviewPercent": review_data["steamReviewPercent"],
        "steamReviewTotal": review_data["steamReviewTotal"],
        "releaseDate": release_date,
        "storeUrl": f"https://store.steampowered.com/app/{appid}",
        "image": f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg",
        "catalogUpdatedAt": datetime.now(timezone.utc).isoformat(),
    }


def build_user_library_entry(game):
    appid = game["appid"]
    playtime_hours = round(game.get("playtime_forever", 0) / 60, 1)

    return {
        "appid": appid,
        "name": game.get("name", "Unknown"),
        "source": "Owned",
        "owner": "Me",
        "playtime": f"{playtime_hours}h",
        "playtimeHours": playtime_hours,
        "status": "Backlog" if playtime_hours == 0 else "Played",
        "userUpdatedAt": datetime.now(timezone.utc).isoformat(),
    }


def build_family_library_entries(family_games):
    entries = []

    for game in family_games:
        appid = game["appid"]

        entries.append({
            "appid": appid,
            "name": game.get("name", "Unknown"),
            "source": "Steam Family",
            "owner": game.get("owner", "Family"),
            "playtime": "0.0h",
            "playtimeHours": 0,
            "status": "Backlog",
            "userUpdatedAt": datetime.now(timezone.utc).isoformat(),
        })

    return entries


def merge_catalog_and_user_library(catalog, user_library):
    merged_games = []

    for user_game in user_library:
        appid = str(user_game["appid"])
        catalog_game = catalog.get(appid, {})

        merged_games.append({
            **catalog_game,
            **user_game,
        })

    merged_games.sort(key=lambda game: game["name"].lower())

    return merged_games


def main():
    if not STEAM_API_KEY:
        raise RuntimeError("Missing STEAM_API_KEY")

    steam_id = resolve_steam_id()
    print(f"Using SteamID: {steam_id}")

    owned_data = fetch_owned_games(steam_id)
    owned_games = owned_data.get("response", {}).get("games", [])

    print(f"Found {len(owned_games)} owned games")

    catalog = load_json_file(CATALOG_PATH)
    family_games = load_json_file(FAMILY_LIBRARY_PATH)

    if isinstance(catalog, list):
        catalog = {str(game["appid"]): game for game in catalog}

    if not isinstance(catalog, dict):
        catalog = {}

    if not isinstance(family_games, list):
        family_games = []

    user_library = []

    for index, game in enumerate(owned_games, start=1):
        appid = game["appid"]
        cache_key = str(appid)
        name = game.get("name", "Unknown")

        print(f"[{index}/{len(owned_games)}] Processing owned game: {name}")

        existing_catalog_entry = catalog.get(cache_key)
        catalog[cache_key] = build_catalog_entry(game, existing_catalog_entry)

        user_library.append(build_user_library_entry(game))

    owned_appids = {game["appid"] for game in owned_games}
    family_entries = build_family_library_entries(family_games)

    for entry in family_entries:
        appid = entry["appid"]
        cache_key = str(appid)

        if appid in owned_appids:
            print(f"Skipping duplicate family game because you own it: {entry['name']}")
            continue

        print(f"Processing family game: {entry['name']}")

        existing_catalog_entry = catalog.get(cache_key)
        catalog[cache_key] = build_catalog_entry(entry, existing_catalog_entry)

        user_library.append(entry)

    merged_games = merge_catalog_and_user_library(catalog, user_library)

    save_json_file(CATALOG_PATH, catalog)
    save_json_file(USER_LIBRARY_PATH, user_library)
    save_json_file(MERGED_OUTPUT_PATH, merged_games)

    print(f"Saved catalog to {CATALOG_PATH}")
    print(f"Saved user library to {USER_LIBRARY_PATH}")
    print(f"Saved merged UI data to {MERGED_OUTPUT_PATH}")


if __name__ == "__main__":
    main()