### Erklärung des Punktemechanismus für das Tippspiel

Willkommen bei unserem Tippspiel! Hier ist eine Aufschlüsselung, wie Punkte basierend auf deinen Vorhersagen berechnet werden.

#### Was du wissen musst

- **Vorhersagen**: Stelle sicher, dass du die Ergebnisse für beide Teams und den Spielausgang vorhersagst.
- **Favorit**: Wähle dein Favorit klug aus, da ihre Leistung deine Punkte erheblich beeinflussen kann.
- **Strategie**: Genauigkeiten bei Vorhersagen können dir Basispunkte einbringen, während unpopuläre Wetten dir helfen können, Exotenpunkte zu verdienen.

#### Wie die Punkte berechnet werden

1. **Favoriten-Bonus**:
    - Jeder Teilnehmer kann ein Favorit festlegen. Wenn dein Favorit gewinnt oder unentschieden spielt, verdienst du zusätzliche Punkte. Wenn sie verlieren, könntest du Punkte verlieren.
    - **Formel**: 
      $$
      \text{Favorit-Punkte} = 
      \begin{cases} 
      2  \times \text{Favorit-Faktor} & \text{wenn Favorit gewinnt} \\
      1  \times \text{Favorit-Faktor} & \text{wenn Favorit unentschieden spielt} \\
      -1 \times \text{Favorit-Faktor} & \text{wenn Favorit verliert}
      \end{cases}
      $$
      wobei $\text{Favorit-Faktor}$ von der Art des Spiels abhängt (Gruppenphase, Achtelfinale usw.).

2. **Basispunkte**:
    - **Richtiger Ausgang**: Verdiene 1 Punkt, wenn dein vorhergesagter Ausgang (Sieg, Niederlage oder Unentschieden) mit dem tatsächlichen Ausgang übereinstimmt. Wenn dies nicht der Fall ist, verlierst du einen Punkt.
    - **Nahe Vorhersage**: Verdiene 1 Punkt, wenn deine vorhergesagten Ergebnisse für beide Teams sehr nah an den tatsächlichen Ergebnissen liegen (innerhalb von 1 Tor).
    - **Richtiger Punkteunterschied**: Verdiene 1 Punkt, wenn der Unterschied zwischen den von dir vorhergesagten Punkten der gleiche ist wie der tatsächliche Punkteunterschied. Dies gilt nicht für Unentschieden.
    - **Exakte Ergebnisse**: Verdiene 2 Punkte, wenn du die exakten Ergebnisse für beide Teams vorhersagst. Verdiene einen zusätzlichen Punkt, wenn du die exakten Ergebnisse bei einem Unentschieden vorhersagst, da du keinen Punkt für den Punkteunterschied erhältst.
    - **Formel**:
      $$
      \text{Basis} = \Bigg(
      2 \times \text{Ausgang} + 
      \text{Nahe} + 
      \begin{cases}
      3 \times \text{Exakt}  &\text{bei Unentschieden}  \\
      \text{Punkte Diff.} +2 \times \text{Exakt} &\text{sonst}
      \end{cases}
      \Bigg) - 1
      $$
      wobei jede Bedingung als 1 wahr und 0 falsch bewertet wird.
3. **Faktor**:
    - **Skalierung**: Die Basispunkte werden mit dem Faktor für jedes Spiel multipliziert.
    - **Faktorbudget**: Ein Faktorbudget wird jedem Spieltag zugewiesen. Der Faktor kann frei auf die Spiele verteilt werden (mit einem Minimum von 1). Jedes Spiel stellt einen Faktor von $\text{FaktorBeitrag}$ für den Spieltag bereit, abhängig von der Art des Spiels (Gruppenphase, Achtelfinale usw.).

4. **Exotenpunkte**:
    - Du kannst zusätzliche Punkte basierend auf spezifischen Bedingungen verdienen, die mit den durchschnittlichen Punkteunterschieden in den Spielen zusammenhängen. Je näher deine Vorhersage mit diesen Bedingungen übereinstimmt, desto mehr Exotenpunkte verdienst du.
    - **Formel**: Punkte beziehen sich auf die Wette, Resultat auf das tatsächliche Ergebnis. Dann,
      $$
      \text{PunkteAbst} = |\text{ResultatTeamA} - \text{PunkteTeamA}| + |\text{ResultatTeamB} - \text{PunkteTeamB}|
      $$
      $$
      \text{PunkteDiff} = \text{PunkteTeamA} - \text{PunkteTeamB}
      $$
      $$
      \text{ResultatDiff} = \text{ResultatTeamA} - \text{ResultatTeamB}
      $$
      $$
      \text{AvPunkteAbst} = \text{Durchschnitt}(\text{PunkteAbst}), ~~~~ 
      \text{AvPunkteDiff} = \text{Durchschnitt}(\text{PunkteDiff})
      $$
      $$
      \text{Exoten Abst} =  [\text{AvPunkteAbst} - \text{PunkteAbst}|]_+   
      $$
      $$
      \text{Exoten Diff} = [|\text{AvPunkteDiff} - \text{ErgebnisDiff}| - |\text{ErgebnisDiff} - \text{PunkteDiff}|]_+ 
      $$
      $$
      \text{Exoten Punkte} = \text{Runde}\Big(\text{Exotenbonus} \frac{ \text{Exoten Abst} + \text{Exoten Diff}}{ 2 }\Big)
      $$
      wobei \text{Exotenbonus} das Gewicht der exotischen Punkte ist, abhängig von der Art des Spiels (Gruppenphase, Achtelfinale usw.).


5. **Kanonenwilli-Punkte**:

- Noch festzulegen

6. **Aspekte je nach Spieltypen**:
- **Die Faktoren**: Die Variablen $\text{Favorit-Faktor}$,  $\text{Exotenbonus}$, $\text{FaktorBeitrag}$ ändern sich während des Spiels.

    | Spieltyp    | Favorit-Faktor | Exotenbonus | FaktorBeitrag |
    |--------------|----------------------|-------------|----------------|
    | Gruppenphase  | 3                   | 3           | 3              |
    | Achtelfinale  | 6                   | 6           | 6              |
    | Viertelfinale| 6                   | 8           | 8              |
    | Halbfinale   | 8                   | 10          | 10             |
    | Um Platz drei    | 8                   | 10          | 10             |
    | Finale        | 10                   | 12          | 12             |


Indem du diese Regeln und Formeln verstehst, kannst du besser strategisieren und deine Punkte im Tippspiel maximieren. Viel Glück!
