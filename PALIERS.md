# I *paliers* del parco nucleare francese

Un **palier** (in francese "gradino", "livello") è una **serie standardizzata di
reattori** costruiti con lo stesso progetto. Invece di progettare ogni centrale da
zero, la Francia ha costruito i suoi reattori in poche famiglie quasi identiche:
questo ha ridotto costi e tempi e ha reso il parco relativamente omogeneo.

Tutti i reattori francesi sono **PWR** (reattori ad acqua pressurizzata): non
esistono BWR. La differenza che conta, quindi, non è il *tipo* ma il **palier** —
cioè la generazione di progetto, con la sua potenza e le sue capacità operative.

---

## Le famiglie, in ordine cronologico

### 900 MW — la prima ondata (fine anni '70 – '80)

| Palier | Anni | Siti principali | Note |
|--------|------|-----------------|------|
| **CP0** | 1977–79 | Fessenheim, Bugey | I primissimi; Fessenheim chiuso nel 2020 |
| **CP1** | 1980–85 | Tricastin, Gravelines, Dampierre, Blayais | La serie più numerosa (18 unità) |
| **CP2** | 1981–87 | Chinon, Cruas, Saint-Laurent | Variante con lievi modifiche impiantistiche |

I 900 MW sono i reattori più vecchi ma, essendo più piccoli e con margini di
progetto ampi, storicamente hanno fatto molto **load-following**.

### 1300 MW — la seconda ondata (anni '80 – '90)

| Palier | Anni | Siti principali | Note |
|--------|------|-----------------|------|
| **P4** | 1984–86 | Paluel, Saint-Alban, Flamanville 1-2 | Prima serie da 1300 MW |
| **P'4** | 1986–93 | Cattenom, Belleville, Nogent, Penly, Golfech | Layout impiantistico rivisto |

I 1300 MW sono i "cavalli da tiro" del parco e, nei dati, risultano tra i più
attivi nella modulazione quotidiana.

### 1450 MW — N4 (fine anni '90)

| Palier | Anni | Siti | Note |
|--------|------|------|------|
| **N4** | 1996–99 | Chooz, Civaux | Le "barre grigie" (*grey rods*) permettono variazioni di potenza più fini e rapide |

### 1600 MW — EPR (Gen III+)

| Palier | Anni | Siti | Note |
|--------|------|------|------|
| **EPR** | 2024– | Flamanville 3 | Progettato per flessibilità, ma con pochi dati storici |

---

## Perché il palier conta per la modulazione

La capacità di un reattore di **variare potenza** (load-following) dipende dal
progetto:

- **Sistemi di controllo**: le barre grigie degli N4 consentono manovre più fini
  senza perturbare troppo la distribuzione di potenza nel nocciolo.
- **Margini termici**: i 900 MW hanno margini che rendono le manovre meno critiche.
- **Vincoli fisici comuni a tutti i PWR**: l'**xeno-135** (un prodotto di fissione
  che assorbe neutroni) crea transitori che limitano quanto in fretta e quante
  volte si può ri-manovrare; il **burn-up** del combustibile riduce la flessibilità
  verso fine ciclo; la **fatica del cladding** limita il numero totale di cicli.

Per questo, confrontare i reattori **per blocco di palier** (come fa l'app nel tab
"Confronto per palier") è il modo corretto di leggere le performance: si mettono a
confronto generazioni con la stessa fisica di base, non mele con pere.

---

## In una riga

> Il palier dice *di che generazione* è un reattore. In Francia tutti sono PWR, ma
> un CP1 del 1982 e un N4 del 1997 modulano in modo diverso — ed è questa la chiave
> per capire i limiti di flessibilità del nucleare.

---

*Nota: gli anni indicati sono le prime connessioni alla rete, indicativi. L'elenco
completo con potenze e anni è in `data/reactors_metadata.csv`, editabile.*
