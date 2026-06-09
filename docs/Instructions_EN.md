# TippNation Guide

This guide explains how to use the app and how points are calculated.

## Using the App

### Login

Select your username in the sidebar, enter your password, and click **Login**. Use **Logout** when you are done. Only logged-in players can save bets.

### Language

Use the sidebar language selector to switch between English and German.

### Favorite Team

Pick your favorite team before the first tournament match starts. Favorite picks are hidden until the first match has started and are locked afterwards.

Your favorite can score extra points in every match it plays:

- Win: `FavoriteWin` points
- Draw: `3` points
- Loss: `-6` points
- Favorite not involved in the match: `0` points

### Bets Tab

Choose a match date. For each match on that date, enter:

- Team A score
- Team B score
- Factor

Started matches are locked. You can edit a match until kickoff.

The app also shows the next-match submission status, including who has already submitted and who is still missing.

### Factor Budget

Each match contributes a factor amount to the selected date's shared budget. Every match must keep at least factor `1`.

For one selected date:

```text
Daily factor budget = sum(FactorContribution for all matches on that date)
```

The maximum factor for one match is:

```text
Daily factor budget - sum(factors used by all other matches on that date)
```

So if the rest of the day has already used the budget, a match's factor control becomes fixed at `1`. The app enforces the budget in the sliders and again when you submit.

### Market Score Probabilities

When available, each upcoming match has a collapsible market probability grid. It shows model probabilities for exact scores, based on stored Betfair market snapshots. These probabilities are informational before kickoff and are also used for exotic scoring if a pre-game snapshot is available.

### Entries Tab

Bets become visible after kickoff. The table shows each visible match and each player's submitted bet in the form:

```text
score x factor
```

Favorite teams are shown after favorite picks are locked.

### Stats Tab

The standings show total points by player and by component:

- `fbase`: base score after factor and flat bonus
- `exotic`: exotic points
- `favorite`: favorite-team points
- `kanonenwilli`: Kanonenwilli points
- `final`: total

The tab also shows points by match and a running points chart.

### Breakdown Tab

Use this tab to inspect scoring in detail:

- Match breakdown: all players for one match
- User breakdown: one player's match-by-match scoring
- Points composition: how that player's score developed by component

### Heatmaps Tab

Pick a match, a player, and optionally an opponent. The heatmap simulates possible results from `0:0` to `5:5` and shows the player's point difference against the opponent.

### Help Tab

Shows this guide.

### Admin Tab

Admins can sync the database, enter results, and recompute stored points.

## Scoring

For each completed match, the final score is:

```text
final = fbase + exotic + favorite + kanonenwilli
```

## Base Points

Let:

```text
score_a, score_b   = your bet
result_a, result_b = actual result
score_diff         = score_a - score_b
result_diff        = result_a - result_b
score_dist         = |score_a - result_a| + |score_b - result_b|
```

Then:

```text
correct_outcome = 1 if your win/draw/loss tendency is correct, otherwise 0
close_score     = 1 if score_dist <= 1, otherwise 0
correct_diff    = 1 if score_diff == result_diff, otherwise 0
exact_score     = 1 if score_a == result_a and score_b == result_b, otherwise 0
```

Base points are:

```text
base = (2 * correct_outcome - 1)
     + close_score
     + correct_diff
     + 2 * exact_score
```

That means the outcome component is `+1` for a correct tendency and `-1` for a wrong tendency. Base points can be negative.

## Factor and fbase

The factor multiplies the base score. Then a flat `+3` is added:

```text
fbase = base * factor + 3
```

The factor is therefore powerful for both good and bad bets: it multiplies negative base scores too.

## Exotic Points

Exotic points reward predictions that are both good and, when market data exists, relatively unlikely according to the pre-game odds model.

Each round has an `ExoticWeight`. The app uses market-based exotic scoring when a locked pre-game probability grid exists for the match. If no usable market snapshot exists, it falls back to a crowd-based method.

### Closeness

For every player bet:

```text
score_dist = |score_a - result_a| + |score_b - result_b|
diff_dist  = |(score_a - score_b) - (result_a - result_b)|
```

The app computes:

```text
closeness = 0.7 * max(1 - score_dist / 4, 0)
          + 0.3 * max(1 - diff_dist / 3, 0)
```

`closeness` is high when the bet is near the real result.

### Market-Based Exotic Scoring

The market model stores probabilities for exact scores. For each bet, the app compares the bet's actual closeness against the closeness that would be expected across the model's score grid.

For one bet:

```text
mu    = expected closeness under the market score probabilities
sigma = standard deviation of that closeness
k     = actual closeness against the real result
```

If `k < 0.35`, `market_score` is `0`. Otherwise:

```text
z_score      = clamp((k - mu) / sigma, 0, 3)
market_score = z_score / 3
```

The app also compares the bet with the crowd:

```text
average_closeness = average k for all player bets on this match
crowd_score       = max(k - average_closeness, 0) / (1 - average_closeness)
```

Final market-based exotic points:

```text
exotic = round(ExoticWeight * (0.6 * market_score + 0.4 * crowd_score))
```

### Fallback Exotic Scoring

If no locked market probabilities are available, the app uses the older crowd-only scoring:

```text
average_score_diff = average(score_diff) over all bets on the match
average_score_dist = average(score_dist) over all bets on the match

exotic_diff = max(|average_score_diff - result_diff| - |result_diff - score_diff|, 0)
exotic_dist = max(average_score_dist - score_dist, 0)

exotic = int(ExoticWeight * (exotic_diff + exotic_dist) / 2)
```

## Odds Model

The odds model is built from stored Betfair markets. Streamlit Cloud only reads stored odds; odds refreshes are run externally and written to the database.

The model uses these market types when available:

- Match odds
- Correct score
- Over/under 2.5 goals
- Alternative total goals
- Both teams to score
- Over/under 0.5 goals
- Asian handicap

For each runner, the app estimates an implied probability from the best back/lay prices:

```text
mid_price = average(best_back, best_lay)
raw_probability = 1 / mid_price
```

The probabilities are normalized within each market. The app then fits two independent Poisson goal rates:

```text
lambda_team_a
lambda_team_b
```

It chooses the lambdas that minimize weighted squared error between market probabilities and model probabilities. More liquid markets get more weight. The fitted Poisson model produces the exact-score probability grid used for the UI and for market-based exotic scoring. The UI displays the most relevant low-score range; the stored model keeps a wider score grid for scoring.

Before a match starts, the latest pre-game snapshot is locked. Scoring uses that locked pre-game snapshot, not odds that move after kickoff.

## Favorite Points

Favorite points are added only when your favorite team plays in the match:

```text
favorite =
  FavoriteWin   if favorite wins
  3             if favorite draws
  -6            if favorite loses
  0             if favorite is not involved
```

## Kanonenwilli

![Kanonenwilli](data/figs/Bullet_Bill.png)

Kanonenwilli is a comeback mechanic. It is assigned automatically and deterministically by the app.

Before each match, the app looks at the standings from previous completed matches. Players near the bottom can receive a Kanonenwilli value with a seeded random chance. The target is usually one of places 4 to 8 in the current standings. The assigned value is the number of points needed to catch that target, never below `0`.

Kanonenwilli points are only paid if the player gets the match outcome right:

```text
kanonenwilli_points = assigned_kanonenwilli if correct_outcome else 0
```

The first match has no prior standings, so Kanonenwilli is `0`.

## Round Settings

| Round | FavoriteWin | Factor contribution | ExoticWeight |
|---|---:|---:|---:|
| Group stage | 6 | 3 | 6 |
| Round of 32 | 10 | 5 | 10 |
| Round of 16 | 12 | 6 | 12 |
| Quarterfinal | 12 | 8 | 16 |
| Semifinal | 16 | 10 | 20 |
| Third place | 16 | 10 | 20 |
| Final | 20 | 12 | 24 |

For knockout matches decided by penalties, TippNation represents the result as the score after 120 minutes plus one goal for the shootout winner.
