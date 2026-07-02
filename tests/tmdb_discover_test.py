from datetime import date
import requests
from cinesync.utils.net import force_ipv4
from cinesync.paths import DATA_DIR
from cinesync.config_loader import load_config

force_ipv4()
apikey = load_config()["apis"]["tmdb_api_key"]

content_type = "movie"  # "movie", "tv"

url = f"https://api.themoviedb.org/3/discover/{content_type}"

floor_year = date.today().year - 86

params = {
    "include_adult": "false",
    "with_original_language": "en",
    "vote_count.gte": 15,
    "sort_by": "vote_count.desc",
    "page": 501,
}

if content_type == "movie":
    params["include_video"] = "false"
    params["with_runtime.gte"] = 40
    params["primary_release_date.gte"] = f"{floor_year}-01-01"
elif content_type == "tv":
    params["first_air_date.gte"] = f"{floor_year}-01-01"
else:
    raise ValueError(f"content_type must be 'movie' or 'tv', got {content_type!r}")


headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {apikey}",
}

response = requests.get(url, headers=headers, params=params)

print(response.json())
