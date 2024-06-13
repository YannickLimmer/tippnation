### Betting Game Points Mechanism Explained

Welcome to our betting game! Here's a breakdown of how points are calculated based on your predictions.

#### What You Need to Know

- **Predictions**: Make sure to predict the scores for both teams and the match outcome.
- **Favorite Team**: Choose your favorite team wisely, as their performance can significantly affect your points.
- **Strategy**: Accurate predictions can earn you base points, while unpopular bets can help you earn exotic points.

#### How Points are Calculated

1. **Favorite Team Bonus**:
    - Each participant can set a favorite team. If your favorite team wins or draws, you earn extra points. If they lose, you might lose points.
    - **Formula**: 
      $$
      \text{Favorite Points} = 
      \begin{cases} 
      2  \times \text{FavoriteFactor} & \text{if Favorite team wins} \\
      1  \times \text{FavoriteFactor} & \text{if Favorite team draws} \\
      -1 \times \text{FavoriteFactor} & \text{if Favorite team loses}
      \end{cases}
      $$
      where $\text{FavoriteFactor}$ is the depending on the type of game (group stage, round of 16, etc...).

2. **Base Points**:
    - **Correct Outcome**: Earn 1 points if your predicted outcome (win, loss, or draw) matches the actual outcome. If you fail to do so, you loose one point.
    - **Close Prediction**: Earn 1 point if your predicted scores for both teams are very close to the actual scores (within 1 goal).
    - **Correct Score Difference**: Earn 1 point if the difference between the scores you predicted is the same as the actual score difference. This is not available for draws.
    - **Exact Scores**: Earn 2 points if you predict the exact scores for both teams. Earn 1 extra point if you predict the exact scores in a draw, since you did not get the point for the score difference.
    - **Formula**:
      $$
      \text{Base} = \Bigg(
      2 \times \text{Outcome} + 
      \text{Close Score} + 
      \begin{cases}
      3 \times \text{Exact Score}  &\text{if Draw}  \\
      \text{Score Diff.} +2 \times \text{Exact Score} &\text{else}
      \end{cases}
      \Bigg) - 1
      $$
      where each condition is evaluated as 1 if true, 0 if false.
3. **Factor**:
    - **Scaling**: The base points are multiplied with the factor for each game.
    - **Factor Budget**: A factor budget is assigned to every match day. The factor can be distributed freely across games (with a minimum of 1). Every game, provides a factor of $\text{ProvidesFactor}$ to the match day, depending on the type of game (group stage, round of 16, etc...).

4. **Exotic Points**:
    - You can earn additional points based on specific conditions related to the average score differences in the matches. The closer your prediction aligns with these conditions, the more exotic points you earn.
    - **Formula**: Score refers to the bet, result to the actual result. Then,
      $$
      \text{ScoreDist} = |\text{ResultTeamA} - \text{ScoreTeamA}| + |\text{ResultTeamB} - \text{ScoreTeamB}|
      $$
      $$
      \text{ScoreDiff} = \text{ScoreTeamA} - \text{ScoreTeamB}, ~~~~ \text{ScoreDiff} = \text{ResultTeamA} - \text{ResultTeamB}
      $$
      $$
      \text{AvScoreDist} = \text{Average}(\text{ScoreDist}), ~~~~ 
      \text{AvScoreDiff} = \text{Average}(\text{ScoreDiff})
      $$
      $$
      \text{Exotic Dist} =  [\text{AvScoreDist} - \text{ScoreDist}|]_+   
      $$
      $$
      \text{Exotic Diff} = [|\text{AvScoreDiff} - \text{ResultDiff}| - |\text{ResultDiff} - \text{ScoreDiff}|]_+ 
      $$
      $$
      \text{Exotic Points} = \text{Round}\Big(\text{ExoticFactor} \frac{ \text{Exotic Dist} + \text{Exotic Diff}}{ 2 }\Big)
      $$
      where \text{ExoticFactor} is the weight associated with the exotic points, depending on the type of game (group stage, round of 16, etc...).


5. **Kanonenwilli Points**:

- TBD

6. **Aspects Depending on Game Types**:
- **The factors**: The variables $\text{FavoriteFactor}$,  $\text{ExoticFactor}$, $\text{ProvidesFactor}$ change throughout the game.

    | Game Type    | FavoriteFactor | ExoticFactor | ProvidesFactor |
    |--------------|----------------|--------------|----------------|
    | Group Stage  | 3              | 3            | 3              |
    | Round of 16  | 6              | 6            | 6              |
    | Quarter Final| 6              | 8            | 8              |
    | Semi-Final   | 8              | 10           | 10             |
    | For Third    | 8              | 10           | 10             |
    | Final        | 10             | 12           | 12             |


By understanding these rules and formulas, you can strategize better and maximize your points in the betting game. Good luck!
