import json
import os
import requests
from dotenv import load_dotenv
from net import force_ipv4

load_dotenv(".env")
force_ipv4()

url = "https://api.themoviedb.org/3/configuration"

headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {os.getenv('TMDB_API_KEY')}",
}

response = requests.get(url, headers=headers)

with open("tests/tmdb_config.json", "w", encoding="utf-8") as file:
    json.dump(response.json(), file, indent=4)
