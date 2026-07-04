import json
import requests
from cinesync.utils.net import force_ipv4
from cinesync.paths import DATA_DIR
from cinesync.config_loader import load_config

force_ipv4()
apikey = load_config()["apis"]["tmdb_api_key"]

content_type = "movie"  # "movie", "tv"
tmdb_id = 1122584

path = DATA_DIR / "tmdb_response_sample" / content_type

url = f"https://api.themoviedb.org/3/{content_type}/{tmdb_id}?append_to_response=keywords,credits,external_ids"

headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {apikey}",
}

response = requests.get(url, headers=headers)

with open(path / f"{tmdb_id}.json", "w", encoding="utf-8") as file:
    json.dump(response.json(), file, indent=4)
