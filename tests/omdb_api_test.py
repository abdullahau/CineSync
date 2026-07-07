import json
import requests
from cinesync.utils.net import force_ipv4
from cinesync.paths import DATA_DIR
from cinesync.config_loader import load_config

force_ipv4()
path = DATA_DIR / "omdb_response_sample"
apikey = load_config()["apis"]["omdb_api_key"]

url = "http://www.omdbapi.com/"

imdb_id = "tt0363226"

params = {
    "apikey": apikey,
    "i": imdb_id,
    "plot": "full",
    "tomatoes": "true",
}

response = requests.get(url, params=params)

with open(path / f"{imdb_id}.json", "w", encoding="utf-8") as file:
    json.dump(response.json(), file, indent=4)
