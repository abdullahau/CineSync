import json
import os
import requests
from dotenv import load_dotenv
from cinesync.utils.net import force_ipv4
from cinesync.paths import DATA_DIR

load_dotenv(".env")
force_ipv4()

content_type = "tv"  # "movie", "tv"
tmdb_id = 37680

path = DATA_DIR / "tmdb_response_sample" / content_type

url = f"https://api.themoviedb.org/3/{content_type}/{tmdb_id}?append_to_response=keywords,credits,external_ids"

headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {os.getenv('TMDB_API_KEY')}",
}

response = requests.get(url, headers=headers)

with open(path / f"{tmdb_id}.json", "w", encoding="utf-8") as file:
    json.dump(response.json(), file, indent=4)
