\# Speech Coach – Rapport de non-infériorité



\## 1. Contexte

\- Référence (A): app v7.6.0 | P3 3.0.0 | S4 4.2.0 | D2.1 2.1.0 | commit ...

\- Candidate (B): app v7.6.1 | P3 3.0.0 | S4 4.2.1 | D2.1 2.1.0 | commit ...

\- Changement: (ex: optimisation MFCC, refactor scoring, etc.)

\- Classe d’impact clinique: C1 (supposé neutre) / C2 (impact attendu)



\## 2. Population de test (Golden set)

\- Taille: N = ...

\- Langue: fr-FR

\- Répartition difficulté: facile/moyen/difficile (%, %, %)

\- Conditions: micro/BRUIT, etc. (si vous le mesurez)



\## 3. Métriques (primaires / secondaires)

\### Primaires (doivent passer)

1\) Corrélation score global A vs B (Pearson r)

2\) Taux d’accord sur la décision (si seuil) : ex. "réussi/à revoir"

3\) Drift distribution score (KS statistic ou Δmoyenne)



\### Secondaires (informatives)

\- Latence totale (TTS→résultat)

\- Taux d’échec ASR / retry

\- Jitter score (variance par répétition si applicable)



\## 4. Critères d’acceptation (non-infériorité)

\- r(score\_global\_A, score\_global\_B) ≥ 0.98

\- Δmoyenne(score\_global) ∈ \[-0.5 ; +0.5] (sur l’échelle score)

\- Accord décisionnel ≥ 99.0% (si binaire par seuil)

\- KS(score\_global) ≤ 0.08

\- Taux échec ASR: +0.2% max vs A

\- Latence: +10% max vs A (sauf si justifié)



\## 5. Résultats

\- r = ...

\- Δmoyenne = ...

\- Accord = ...

\- KS = ...

\- ASR fail Δ = ...

\- Latence Δ = ...



\## 6. Conclusion

\- Verdict: ACCEPTÉ / REFUSÉ

\- Si refus: rollback scoring/protocol ou montée MAJOR + note méthodologique.

\- Actions: ...



