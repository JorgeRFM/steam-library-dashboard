import json
import urllib.request
from dotenv import load_dotenv
import os

load_dotenv()

STEAM_API_KEY = os.getenv("STEAM_API_KEY")
STEAM_ID = os.getenv("STEAM_ID")

url = (
    "https://api.steampowered.com/IFamilyGroupsService/GetFamilyGroupForUser/v1/"
    f"?key={STEAM_API_KEY}"
    f"&steamid={STEAM_ID}"
)

try:
    with urllib.request.urlopen(url) as response:
        data = json.load(response)

    print(json.dumps(data, indent=2))
except Exception as e:
    print(e)