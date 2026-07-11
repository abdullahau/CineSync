**Core goal**

Build a local, notebook/script-based recommendation system that learns me and my partner's movie/TV taste from Letterboxd ratings, then helps us both discover what to watch next — while doubling as a hands-on way to learn data science and ML/deep learning fundamentals.

**What the system needs to do**

1. **Capture rich metadata** per title — language, genre, director, writer, cast, year, theme/style, plot, production company, and critic reviews — not just a title and a rating.

2. **Visualize taste** — show clusters and patterns in what each of you individually enjoys, and where your tastes overlap or diverge.

3. **Generate recommendations across four distinct modes**, which can be mixed and filtered together:
   - *Personalized fit* — based on patterns in what you've each rated highly.
   - *Mood-based* — free-text query like "something surreal and slow" matched semantically against unwatched titles.
   - *Buzz/trending* — pulled from TMDB trending, Reddit discussion volume, and Letterboxd's popular lists. (Z-score each within its own source, average (or weight, if you find one source noisier — Reddit mention counts skew toward already-huge titles), and that's your `buzz_score`.)
   - *Left-field/novelty* — deliberately unlike your usual patterns, with a toggleable dial that ranges from "taste-adjacent stretch" to "totally outside your normal lane."
   - *recency* — controls how much weight your recent watch history carries when building the taste profile that personal-fit and novelty both depend on. Implemented as exponential decay with an adjustable half-life (a rating's influence halves every N days)

```python
recommend(mood="surreal political", novelty=0.7, min_critic_score=60,
          sort_by="novelty_score", buzz_window="weekly",
          recency_half_life="2w")
```

4. **Score "who'll like it more"** — a direct comparison between your predicted enjoyment and your wife's for any given title.

5. **Filter/sort by weighted critic and audience scores** — Letterboxd and Rotten Tomatoes critic scores weighted higher than RT audience and IMDb scores.

6. **Learn from real-world feedback** — as you watch, partially watch, or reject recommendations (for a specific reason like cast/pacing, or just "wrong vibe"), the system logs that and periodically retrains, so it actually improves rather than staying static.

**Important constraints and design decisions along the way**

- Works for 1 person, a couple, or a larger group — not hardcoded to two people.
- Covers both movies and TV shows (TV at series level only, not per-episode).
- Includes proper world cinema representation (Japanese, Hindi, Korean, French, etc.) via per-language candidate pulls, rather than letting global popularity sort bury them.
- Fully local — your own machine, SQLite for relational data, pandas for analysis, no cloud dependency.
- Structured as a phased learning progression (data collection → features → clustering → preference models → deep learning → recommendations → feedback loop), so each phase teaches a specific data science/ML concept rather than being a black box.

**Where things stand**
We've completed Phase 0: the project (named CineSync) has a locked-in database schema, a config file for people/API keys/weights, and a `uv`-based reproducible environment setup, all tested and verified working. Next up is Phase 1 — collecting and enriching the actual Letterboxd data.