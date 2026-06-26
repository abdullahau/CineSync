import json
import os
import requests
from dotenv import load_dotenv
from cinesync.utils.net import force_ipv4
from cinesync.paths import DATA_DIR

load_dotenv(".env")
force_ipv4()

url = "https://api.themoviedb.org/3/configuration"

headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {os.getenv('TMDB_API_KEY')}",
}

response = requests.get(url, headers=headers)

with open(DATA_DIR / "tmdb_config.json", "w", encoding="utf-8") as file:
    json.dump(response.json(), file, indent=4)
