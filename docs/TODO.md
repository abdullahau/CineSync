## TODOs:

- [ ] IMDb awards (https://www.imdb.com/title/<imdb_id>/awards) to enhance awards table
- [ ] Figure out how to sweep, store, and compute TMDB Popularity data over 90 day windows (store exponentially-weighted moving average baseline [EWMA] or maintain full popularity trajectory? Would we like to train a model on raw popularity curve? Could this help us predict popularity and tracking of new releases?)
- [ ] Ensure that if a title has one person credited with the writer and director role, the name appears on both bills
- [ ] pull `certificate`/`rating` from TMDB API.
- [ ] consider adding "certificate/rating" filter to ensure movies are, as per US standards, at maximum of age rating
- [ ] consider adding "to watchlist" to influence recommendation - from Letterboxd or IMDB - optional
- [ ] Track movie budget from IMDB?
- [ ] buzz_window is good, but I want to be able to state where I want something "buzzing" or not.
- [ ] consider creating a quarterly or monthly "wrapped" - like top movies, genres, themes, aesthetic - similar to spotify wrap
- [ ] Candidate pool update cycle (new titles, updates to keywords, scores, plot, etc)
