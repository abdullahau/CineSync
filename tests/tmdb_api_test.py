import json
import os
import requests
from dotenv import load_dotenv
from net import force_ipv4

load_dotenv(".env")
force_ipv4()

url_movie = "https://api.themoviedb.org/3/movie/1083381?append_to_response=keywords,credits,external_ids"
url_series = "https://api.themoviedb.org/3/tv/95396?append_to_response=keywords,credits,external_ids"

headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {os.getenv('TMDB_API_KEY')}",
}

response = requests.get(url_movie, headers=headers)

with open("tests/tmdb_movies.json", "w", encoding="utf-8") as file:
    json.dump(response.json(), file, indent=4)
