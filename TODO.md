## TODOs:

- [ ] Figure out a way to scrape IMDB's rating-histogram scraping technique (potentially inside HTML)
- [ ] Ensure that if a title has one person credited with the writer and director role, the name appears on both bills
- [ ] pull `certificate`/`rating` from OMDB API and when wikidata ID or IMDB ID is missing, pull those from OMDB
- [ ] consider adding "to watchlist" to influence recommendation - from Letterboxd or IMDB - optional
- [ ] buzz_window is good, but I want to be able to state where I want something "buzzing" or not.
- [ ] consider adding "certificate/rating" filter to ensure movies are, as per US standards, at maximum of age rating
- [ ] consider creating a quarterly or monthly "wrapped" - like top movies, genres, themes, aesthetic - similar to spotify wrap
- [ ] Rotten Tomato links for each title can be potentially extracted from Wikidata Query SPARQL
- [ ] OMDb (omdb_awards_text and title_score) & Wikipedia (title_awards and detailed_plot) upsert.
- [ ] Candidate pool update cycle (new titles, updates to keywords, scores, plot, etc)
- [ ] Determine where the relationship links between tables in the current schema.sql file (update diagram accordingly)
