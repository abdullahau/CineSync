import requests
from cinesync.utils.net import force_ipv4
from cinesync.paths import DATA_DIR
from cinesync.config_loader import load_config

force_ipv4()
apikey = load_config()["apis"]["tmdb_api_key"]

content_type = "tv"  # "movie", "tv"

url = f"https://api.themoviedb.org/3/discover/{content_type}"

params = {
    "include_adult": "false",
    # "with_original_language": "en",
    "vote_count.gte": 10,
    "vote_average.gte": 6.5,
    "page": 1,
}

if content_type == "movie":
    params["include_video"] = "false"
    params["with_runtime.gte"] = 40
    params["sort_by"] = "primary_release_date.asc"
    # params["primary_release_date.gte"] = "1940-01-01"
else:
    params["sort_by"] = "first_air_date.asc"
    # params["first_air_date.gte"] = "1940-01-01"

headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {apikey}",
}

response = requests.get(url, headers=headers, params=params)

print(response.json())
