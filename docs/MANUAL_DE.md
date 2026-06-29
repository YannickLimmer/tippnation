# TippNation Anleitung

Diese Anleitung erklärt, wie du die App benutzt und wie die Punkte berechnet werden.

## App Benutzen

### Login

Wähle deinen Benutzernamen in der Seitenleiste, gib dein Passwort ein und klicke auf **Einloggen**. Mit **Ausloggen** beendest du deine Sitzung. Nur eingeloggte Spieler können Tipps speichern.

### Sprache

Über die Sprachauswahl in der Seitenleiste wechselst du zwischen Deutsch und Englisch.

### Lieblingsteam

Wähle dein Lieblingsteam vor Anpfiff des ersten Turnierspiels. Die Auswahl bleibt bis zum ersten Anpfiff verborgen und ist danach gesperrt.

Dein Lieblingsteam kann in jedem eigenen Spiel Zusatzpunkte bringen:

- Sieg: `FavoriteWin` Punkte
- Unentschieden: `3` Punkte
- Niederlage: `-6` Punkte
- Lieblingsteam spielt nicht mit: `0` Punkte

### Tab Tippen

Wähle ein Spieldatum. Für jedes Spiel an diesem Datum gibst du ein:

- Tore Team A
- Tore Team B
- Faktor

Begonnene Spiele sind gesperrt. Bis zum Anpfiff kannst du deinen Tipp ändern.

Die App zeigt außerdem den Tippstatus für das nächste Spiel: wer schon getippt hat und wer noch fehlt.

### Faktorbudget

Jedes Spiel steuert einen Faktorbeitrag zum gemeinsamen Tagesbudget bei. Jedes Spiel muss mindestens Faktor `1` behalten.

Für ein ausgewähltes Datum gilt:

```text
Tagesbudget = Summe(Faktorbeitrag aller Spiele an diesem Datum)
```

Der maximale Faktor für ein einzelnes Spiel ist:

```text
Tagesbudget - Summe(Faktoren aller anderen Spiele an diesem Datum)
```

Wenn der Rest des Tages das Budget schon verbraucht, wird der Faktor für ein Spiel auf `1` fixiert. Die App erzwingt das Budget direkt in den Reglern und noch einmal beim Speichern.

### Markt-Wahrscheinlichkeiten

Wenn verfügbar, hat jedes kommende Spiel eine ausklappbare Wahrscheinlichkeitsmatrix für genaue Ergebnisse. Sie basiert auf gespeicherten Betfair-Marktsnapshots. Vor dem Spiel ist sie als Information sichtbar; wenn ein Pre-Game-Snapshot fixiert wurde, wird sie auch für die Exotenpunkte verwendet.

### Tab Tipps

Tipps werden nach Anpfiff sichtbar. Die Tabelle zeigt pro sichtbarem Spiel und Spieler den Tipp in dieser Form:

```text
Ergebnis x Faktor
```

Vom Fallback-Skript erzeugte Tipps werden mit `(auto)` markiert.

Lieblingsteams werden angezeigt, nachdem die Auswahl gesperrt ist.

### Tab Statistik

Die Tabelle zeigt die Gesamtpunkte pro Spieler und nach Komponenten:

- `fbase`: Basispunkte nach Faktor und fixer Zusatzkomponente
- `exotic`: Exotenpunkte
- `favorite`: Lieblingsteam-Punkte
- `kanonenwilli`: Kanonenwilli-Punkte
- `final`: Gesamtpunkte

Der Tab zeigt außerdem Punkte pro Spiel und einen Verlauf der Gesamtpunkte.

### Tab Aufschlüsselung

Hier kannst du die Wertung im Detail prüfen:

- Spiel-Aufschlüsselung: alle Spieler für ein Spiel
- Spieler-Aufschlüsselung: alle Spiele eines Spielers
- Punkte-Zusammensetzung: Entwicklung der Punkte nach Komponente

Automatisch erzeugte Fallback-Tipps werden auch hier mit `(auto)` markiert.

### Tab Heatmaps

Wähle ein Spiel, einen Spieler und optional einen Gegner. Die Heatmap simuliert mögliche Ergebnisse von `0:0` bis `5:5` und zeigt die Punktedifferenz des Spielers gegen den Gegner.

### Tab Hilfe

Zeigt diese Anleitung.

### Tab Admin

Admins können die Datenbank synchronisieren, Ergebnisse eintragen und Punkte neu berechnen.

## Punkteberechnung

Für jedes abgeschlossene Spiel ist die Gesamtwertung:

```text
final = fbase + exotic + favorite + kanonenwilli
```

## Basispunkte

Sei:

```text
score_a, score_b   = dein Tipp
result_a, result_b = echtes Ergebnis
score_diff         = score_a - score_b
result_diff        = result_a - result_b
score_dist         = |score_a - result_a| + |score_b - result_b|
```

Dann gilt:

```text
correct_outcome = 1 wenn Tendenz Sieg/Unentschieden/Niederlage stimmt, sonst 0
close_score     = 1 wenn score_dist <= 1, sonst 0
correct_diff    = 1 wenn score_diff == result_diff, sonst 0
exact_score     = 1 wenn score_a == result_a und score_b == result_b, sonst 0
```

Die Basispunkte sind:

```text
base = (2 * correct_outcome - 1)
     + close_score
     + correct_diff
     + 2 * exact_score
```

Die Tendenzkomponente ist also `+1` bei richtiger Tendenz und `-1` bei falscher Tendenz. Basispunkte können negativ sein.

## Faktor und fbase

Der Faktor multipliziert die Basispunkte. Danach werden fix `+3` addiert:

```text
fbase = base * factor + 3
```

Der Faktor wirkt also auf gute und schlechte Tipps: negative Basispunkte werden ebenfalls multipliziert.

## Exotenpunkte

Exotenpunkte belohnen Tipps, die gut sind und, falls Marktdaten vorhanden sind, laut Pre-Game-Quotenmodell eher unwahrscheinlich waren.

Jede Runde hat ein `ExoticWeight`. Die App nutzt marktbasierte Exotenpunkte, wenn für das Spiel eine fixierte Pre-Game-Wahrscheinlichkeitsmatrix vorhanden ist. Wenn kein nutzbarer Marktsnapshot existiert, nutzt sie eine reine Crowd-Methode.

### Nähe

Für jeden Tipp:

```text
score_dist = |score_a - result_a| + |score_b - result_b|
diff_dist  = |(score_a - score_b) - (result_a - result_b)|
```

Die App berechnet:

```text
closeness = 0.7 * max(1 - score_dist / 4, 0)
          + 0.3 * max(1 - diff_dist / 3, 0)
```

`closeness` ist hoch, wenn der Tipp nah am echten Ergebnis liegt.

### Marktbasierte Exotenpunkte

Das Marktmodell speichert Wahrscheinlichkeiten für genaue Ergebnisse. Für jeden Tipp vergleicht die App die tatsächliche Nähe mit der Nähe, die über die Ergebnisverteilung des Modells zu erwarten wäre.

Für einen Tipp:

```text
mu    = erwartete closeness unter den Markt-Ergebniswahrscheinlichkeiten
sigma = Standardabweichung dieser closeness
k     = tatsächliche closeness gegen das echte Ergebnis
```

Wenn `k < 0.35`, ist `market_score` gleich `0`. Sonst:

```text
z_score      = clamp((k - mu) / sigma, 0, 3)
market_score = z_score / 3
```

Zusätzlich vergleicht die App den Tipp mit der Gruppe:

```text
average_closeness = durchschnittliches k aller Tipps auf dieses Spiel
crowd_score       = max(k - average_closeness, 0) / (1 - average_closeness)
```

Die finalen marktbasierten Exotenpunkte:

```text
exotic = round(ExoticWeight * (0.6 * market_score + 0.4 * crowd_score))
```

### Fallback-Exotenpunkte

Wenn keine fixierten Markt-Wahrscheinlichkeiten vorhanden sind, nutzt die App die ältere Crowd-Wertung:

```text
average_score_diff = Durchschnitt(score_diff) über alle Tipps auf dieses Spiel
average_score_dist = Durchschnitt(score_dist) über alle Tipps auf dieses Spiel

exotic_diff = max(|average_score_diff - result_diff| - |result_diff - score_diff|, 0)
exotic_dist = max(average_score_dist - score_dist, 0)

exotic = int(ExoticWeight * (exotic_diff + exotic_dist) / 2)
```

## Quotenmodell

Das Quotenmodell wird aus gespeicherten Betfair-Märkten gebaut. Streamlit Cloud liest nur gespeicherte Quoten; die Aktualisierung läuft extern und schreibt Snapshots in die Datenbank.

Das Modell nutzt diese Markttypen, wenn sie verfügbar sind:

- Match odds
- Correct score
- Over/under 2.5 goals
- Alternative total goals
- Both teams to score
- Over/under 0.5 goals
- Asian handicap

Für jeden Runner schätzt die App eine implizite Wahrscheinlichkeit aus den besten Back-/Lay-Preisen:

```text
mid_price = Durchschnitt(best_back, best_lay)
raw_probability = 1 / mid_price
```

Die Wahrscheinlichkeiten werden innerhalb jedes Marktes normalisiert. Danach passt die App zwei unabhängige Poisson-Torraten an:

```text
lambda_team_a
lambda_team_b
```

Die Lambdas werden so gewählt, dass der gewichtete quadratische Fehler zwischen Markt-Wahrscheinlichkeiten und Modell-Wahrscheinlichkeiten minimal ist. Märkte mit höherer Liquidität bekommen mehr Gewicht. Das angepasste Poisson-Modell erzeugt die genaue Ergebnisverteilung für die UI und die marktbasierten Exotenpunkte. Die UI zeigt den wichtigsten niedrigen Ergebnisbereich; das gespeicherte Modell behält für die Wertung ein breiteres Ergebnisraster.

Vor Anpfiff wird der letzte Pre-Game-Snapshot fixiert. Die Punktewertung nutzt diesen fixierten Snapshot, nicht Quotenbewegungen nach Anpfiff.

## Lieblingsteam-Punkte

Lieblingsteam-Punkte gibt es nur, wenn dein Lieblingsteam im Spiel beteiligt ist:

```text
favorite =
  FavoriteWin   wenn dein Lieblingsteam gewinnt
  3             wenn dein Lieblingsteam unentschieden spielt
  -6            wenn dein Lieblingsteam verliert
  0             wenn dein Lieblingsteam nicht beteiligt ist
```

## Kanonenwilli

![Kanonenwilli](Bullet_Bill.png)

Kanonenwilli ist ein Comeback-Mechanismus. Er wird automatisch und deterministisch von der App vergeben.

Vor jedem Spiel schaut die App auf die Tabelle aus den bereits abgeschlossenen Spielen. Nur die unteren vier Plätze sind für die Kanonenwilli-Ziehung berechtigt:

- Letzter Platz: `66%`
- Vorletzter Platz: `50%`
- Drittletzter Platz: `33%`
- Viertletzter Platz: `16%`

Die Ziehung ist zufällig, aber gesetzt, also für dasselbe Spiel und dieselbe Tabelle reproduzierbar. Wenn die Ziehung erfolgreich ist, ist das Ziel meistens einer der Plätze 4 bis 8 in der aktuellen Tabelle. Der vergebene Wert ist die Punktzahl, die nötig wäre, um dieses Ziel einzuholen, aber nie weniger als `0`.

Kanonenwilli-Punkte werden nur ausgezahlt, wenn die Tendenz des Tipps stimmt:

```text
kanonenwilli_points = assigned_kanonenwilli wenn correct_outcome, sonst 0
```

Im ersten Spiel gibt es noch keine vorherige Tabelle, also ist Kanonenwilli `0`.

## Rundeneinstellungen

| Runde | FavoriteWin | Faktorbeitrag | ExoticWeight |
|---|---:|---:|---:|
| Gruppenphase | 6 | 3 | 6 |
| Runde der letzten 32 | 12 | 6 | 11 |
| Achtelfinale | 14 | 7 | 13 |
| Viertelfinale | 14 | 9 | 17 |
| Halbfinale | 17 | 13 | 20 |
| Spiel um Platz drei | 17 | 12 | 20 |
| Finale | 21 | 14 | 24 |

Die K.o.-Einstellungen sind so skaliert, dass die maximal mögliche fbase-Kapazität, Lieblingsteam-Kapazität und Exoten-Kapazität der gesamten K.o.-Phase den jeweiligen Summen aus der Gruppenphase entsprechen. Spätere Runden bleiben dabei wichtiger.

Bei K.o.-Spielen, die im Elfmeterschießen entschieden werden, nutzt TippNation das Ergebnis nach 120 Minuten plus ein Tor für den Sieger des Elfmeterschießens.
