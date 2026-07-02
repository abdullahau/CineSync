import json
import requests
from cinesync.utils.net import force_ipv4
from cinesync.paths import DATA_DIR
from cinesync.config_loader import load_config

force_ipv4()
apikey = load_config()["apis"]["tmdb_api_key"]

url = "https://api.themoviedb.org/3/configuration"

headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {apikey}",
}

response = requests.get(url, headers=headers)

with open(DATA_DIR / "tmdb_config.json", "w", encoding="utf-8") as file:
    json.dump(response.json(), file, indent=4)
