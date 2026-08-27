# ⚛️ Nuclear Fleet Analyzer

Dashboard **Streamlit** per l'analisi del parco nucleare francese a partire dai
dati orari di [energygraph.info](https://energygraph.info): **capacity factor**,
**ramp up/down** e **indisponibilità**, per singolo reattore o in forma
**aggregata sulla flotta**.

> Sviluppato da **Matteo De Piccoli** — [Ci Sarà un Bel Clima](https://unbelclima.it/)
> · autore di *[Avete rotto l'atomo](https://www.peoplepub.it/pagina-prodotto/avete-rotto-l-atomo)*.


Il tratto distintivo: la curva di **capacità disponibile** non è nei dati grezzi —
viene **ricostruita** dagli eventi di indisponibilità e sovrapposta alla
produzione oraria, permettendo di distinguere il *capacity factor su nominale*
(quanto produce sul massimo teorico) dal *capacity factor su disponibile*
(quanto produce quando è dichiarato disponibile).

---

## 🚀 Quick start

```bash
git clone <il-tuo-repo>.git
cd nuclear-fleet-analyzer

python -m venv .venv && source .venv/bin/activate   # opzionale
pip install -r requirements.txt

streamlit run streamlit_app.py
```

L'app apre su `http://localhost:8501`.

### Caricare i dati

**L'app carica i dati da sola all'avvio** — nessun upload manuale. All'avvio cerca,
in ordine:

1. uno **ZIP** in `data/` (es. `data/nuclear_data.zip`),
2. uno ZIP nella root del repo,
3. i **CSV** sciolti in `data/`.

Basta committare lo ZIP dei CSV in `data/` e l'app lo trova. Se non c'è nulla,
compare un uploader di fallback nella sidebar (utile per provare un altro file
al volo).

> **Nota git:** la cartella `data/` è versionata apposta (vedi `.gitignore`), così
> lo ZIP finisce nel repo e su Streamlit Cloud viene clonato con l'app. Se i tuoi
> dati sono privati o oltre i 100 MB, scommenta le righe indicate in `.gitignore`
> per tornare a escluderli e usa l'upload manuale.

---

## 📁 Struttura repo

```
nuclear-fleet-analyzer/
├── streamlit_app.py        # entry point + UI (sidebar, viste, tab)
├── src/
│   ├── loader.py           # parsing CSV (unità miste GW/MW), zip/cartella
│   ├── availability.py     # ricostruzione capacità disponibile dagli eventi
│   ├── metrics.py          # KPI, slicing periodo, aggregazione, modulazione
│   ├── metadata.py         # anagrafica reattori + matching nomi
│   └── charts.py           # figure Plotly
├── data/
│   ├── reactors_metadata.csv   # anagrafica editabile (versionata)
│   └── *.csv               # i tuoi CSV produzione/eventi (git-ignored)
├── requirements.txt
├── .gitignore
└── README.md
```

Logica separata dalla UI: `src/` è testabile e riusabile senza Streamlit.

---

## 🎛️ Cosa puoi fare

### Modalità **Reattore singolo**
- **⏱️ Orario** — produzione vs capacità disponibile (con bande manutenzione/guasto),
  ramp orario, energia prodotta/disponibile, margine non usato
- **🔁 Load Following** — *il cuore dell'analisi*: quanto e quanto **spesso** il
  reattore modula mentre è in marcia (vedi sotto)
- **⚡ Capacity Factor** — CF annuale (nominale vs disponibile), stagionalità
  mensile, heatmap Anno×Mese, tabella mensile
- **🔀 Ramp** — distribuzione ramp up/down, percentili, pattern per ora del giorno
- **🔧 Indisponibilità** — timeline eventi, stagionalità, durata per tipo, dettaglio

### 🔁 Analisi Load Following

Il focus è **quanto realmente moduli il nucleare**, distinguendo il load-following
operativo (modulazione mentre il reattore è online) dai transitori di avvio/arresto
per ricarica. Metriche chiave, per reattore e per flotta:

- **Ripartizione del tempo** tra piena potenza (≥92%), load-following (20–92%),
  bassa/transitorio (3–20%) e fermo (<3%)
- **Frequenza delle rampe**: numero di eventi-rampa *online* per mese, su/giù
- **Giorni di load-following** e **cicli per giorno** (la letteratura EDF parla di
  ~2 cicli/giorno)
- **Firma giornaliera**: produzione media e rampe per ora del giorno — rende
  visibile l'avvallamento di mezzogiorno indotto dal fotovoltaico
- **Heatmap ora × mese**: *quando* nell'anno e nella giornata il reattore modula
- **Velocità delle rampe** confrontata col limite di letteratura (~20% Pnom/h)
- A livello flotta: **quanti reattori modulano contemporaneamente** nel tempo

**Benchmark di letteratura** (dalla bibliografia, usati come riferimento nell'app):

| Fonte | Parametro |
|-------|-----------|
| EDF — Morilhat et al. 2019 | Modulazione 20–100% Pnom in 30 min, **2 cicli/giorno**; 58 reattori, >30 anni |
| Jenkins/Argonne-MIT 2018 | Rampa max ~**20% Pnom/h**, min stabile 50% (15% FullFlex), 3 h stabili prima di ri-rampare; vincoli xeno-135 e burn-up |
| OECD/NEA — Lokhov 2011 | In baseload le variazioni si limitano alla regolazione di frequenza; il LF stressa combustibile e componenti |
| Göke/Wimmers 2025 | Flessibilità tecnicamente possibile ma anti-economica (serve CF ~90%) |

Sul parco reale i dati confermano bene la letteratura: es. **Belleville 1 (2024)**
modula nel ~46% dei giorni, range osservato 25–100% Pnom, ~1.2 cicli/giorno.

### Modalità **Aggregata (flotta)**
- **⏱️ Orario aggregato** — somma oraria produzione/disponibilità di N reattori
- **📊 Confronto** — ranking CF, heatmap Reattore×Mese, tabella riepilogo
  esportabile in CSV
- **🔀 Ramp flotta** — distribuzione e pattern aggregati
- **🏭 Modulazione & Anagrafica** — potenziale di modulazione per palier
  (scatter età↔velocità di ramp), boxplot per generazione, timeline vita
  operativa, età↔CF, tabella esportabile

### Anagrafica reattori
Ogni reattore è arricchito con **tipo** (tutti PWR in Francia), **palier**
(CP0/CP1/CP2 900 MW · P4/P'4 1300 MW · N4 1450 MW · EPR 1600 MW), **potenza
netta**, **anno di accensione** e **anni di esercizio**. Nella vista singola
compare un badge compatto; nella flotta i reattori sono confrontati per palier
per leggere il **potenziale di modulazione** (i 900 MW e gli N4/EPR sono
progettati per load-following più spinto).

I metadati vivono in `data/reactors_metadata.csv` — **editabile**: correggi anni,
potenze o aggiungi reattori senza toccare il codice. Gli anni sono le prime
connessioni alla rete (indicativi, da verificare). Fessenheim è marcato dismesso
nel 2020.

**Metriche di modulazione** (per reattore, nel periodo):
```
Velocità modulazione = 95° perc. di |ramp| / nominale ×100   (% Pnom/h)
Escursione giornaliera = media di (max−min giornaliero) / nom ×100 (% Pnom)
                         calcolata sui soli giorni "in marcia" (media > 20% nom)
N ramp significativi  = ore con |ramp| > 5% del nominale
```

> Sul parco reale la modulazione differenzia bene i palier: i **P'4** (Cattenom,
> Belleville, Golfech…) fanno il load-following più spinto (~21% di escursione
> giornaliera, ~9%/h di ramp), i vecchi **CP0** molto meno (~9% / ~1.5%/h).

### Selezione temporale
Preset (*ultimo anno / 6 mesi / mese / tutto*) o intervallo personalizzato.
La visualizzazione principale è sempre **oraria**.

---

## 🧮 Metodologia

**Capacità nominale** — stimata come 99.5° percentile della produzione oraria
(robusta agli outlier).

**Capacità disponibile** — ricostruita ora per ora: durante ogni evento di
indisponibilità *attivo*, la capacità è limitata al campo `value` (MW disponibili
dichiarati). Con eventi sovrapposti si prende il minimo; fuori dagli eventi vale
il nominale. Solo l'ultima versione pubblicata di ciascun evento viene usata.

```
CF su nominale   = Σ produzione / (nominale × ore)      → include i fermi
CF su disponibile = Σ produzione / Σ disponibile         → load factor
Fattore disponibilità = Σ disponibile / (nominale × ore)
Ramp rate (MW/h) = produzione(t) − produzione(t−1)
```

**Note sui dati grezzi**
- Le potenze usano unità miste (`1.31 GW`, `714 MW`) — normalizzate a MW.
- I valori negativi (es. `−42 MW`) sono reali: ausiliari che assorbono rete
  durante i fermi. Trattati come 0 per il CF.
- Valori oltre il 115% del nominale (rari errori di sorgente, es. `7000 MW`)
  vengono rimossi e interpolati per non falsare ramp e CF.

---

## ☁️ Deploy su Streamlit Community Cloud

1. Push del repo su GitHub.
2. Su [share.streamlit.io](https://share.streamlit.io) → *New app* → punta a
   `streamlit_app.py`.
3. Per i dati usa l'upload ZIP (Streamlit Cloud non ha filesystem persistente).

---

## 📊 Formato dati atteso

**Produzione** — `Availability_vs_production__..._<Reattore>.csv`
```
Time,production
2020-01-01 00:00:00,1.31 GW
2020-01-01 01:00:00,1.29 GW
```

**Indisponibilità** — `Unavailabilities__..._<Reattore>.csv`
```
update,id,version,start,end,type,status,value,reason
2025-01-31 08:11,199102,1,2025-02-02 07:00,2025-02-02 09:00,planned_maintenance,active,1194,...
```

Il nome reattore è estratto dal suffisso del filename (`..._Belleville_1.csv` →
`Belleville 1`) — è così che le due tipologie di file vengono accoppiate.

---

## 🗄️ Backend dati: CSV/ZIP oppure database Flock

L'app cerca i dati in quest'ordine e usa il **primo** che trova:

1. **Database Flock** (`data/` con una sottocartella per impianto) — usato solo se
   la libreria `flock` è importabile;
2. **ZIP** di CSV in `data/`, nella root, o ovunque nel repo;
3. **CSV** sciolti.

Il database Flock ha due chiavi — *impianto* × *tipo di tabella*
(`availability` / `unavailabilities`) — e viene letto così:

```python
db = Flock("data")
db.availability.plants("Belleville 1").to_pandas()
db.unavailabilities.plants("Belleville 1").to_pandas()
```

Il vantaggio principale non è tanto il *column pruning* (le tabelle hanno poche
colonne) quanto **evitare il parsing dei CSV a ogni cold start**: i tipi sono già
numerici, quindi niente conversione di stringhe come `"1.31 GW"`.

La libreria Flock è **vendorizzata** nel repo (cartella `flock/`), con due patch
rispetto all'originale, necessarie per farla funzionare come package:
`from converter import ...` → import **relativo**, e reso **opzionale** (il
converter richiede `alive_progress`, che non è tra le dipendenze e serve solo a
`build_database()`).

> **Non aggiungere `flock` a `requirements.txt`**: su PyPI esiste un pacchetto
> omonimo che è una libreria di *file locking*, diversa da questa. In
> `requirements.txt` ci sono solo le sue dipendenze (`duckdb`, `pyarrow`).
> Se Flock non è caricabile, l'app **ricade automaticamente su ZIP/CSV**.

### Nomi dei file CSV supportati

```
<Reattore> - Availability.csv          # es. "Belleville 1 - Availability.csv"
<Reattore> - Unavailabilities.csv      # tollera "-Unavailabilities" senza spazio
```
Sono supportati anche i vecchi nomi `Availability vs production (...)_<Reattore>.csv`.
I nomi vengono canonicalizzati: `Dampierre En Burly 3` → `Dampierre 3`,
`Nogent Sur Seine 1` → `Nogent 1`, `St Alban St Maurice 2` → `Saint-Alban 2`,
`CHOOZ B 1` → `Chooz 1`.

---

## 🌡️ Siccità e vincoli ambientali

Tab dedicato nella vista flotta (+ nota per singolo reattore) sulle indisponibilità
da **temperatura e portata dei fiumi, ondate di calore, siccità**.

**Metodo e suo limite.** Nei dati non esiste un'etichetta esplicita "siccità" o
"canicule" — cercandole non si trova nulla. Si usa la categoria
*"Causes externes liées à l'environnement / Environmental issues"* come **proxy**.
Il proxy regge perché mostra entrambe le firme attese:

- **stagionale**: ~76% degli eventi tra giugno e settembre, quasi zero in inverno;
- **geografica**: ~98% su impianti **fluviali o d'estuario** (Rodano, Mosa, Reno,
  Garonna, Loira); i costieri (Gravelines, Paluel, Penly, Flamanville) sono
  praticamente immuni.

Sul parco 2015–2026 la stima è di **~9,9 TWh persi** (~0,27% della produzione),
con anno peggiore il **2020** e Chooz (sulla Mosa, fiume di piccola portata) come
sito più colpito.

> La categoria include anche vincoli ambientali non climatici (alghe, detriti alle
> prese d'acqua): i numeri vanno letti come "vincoli ambientali", di cui caldo e
> magra dei fiumi sono la componente dominante estiva.

---

## ☀️ L'impronta del solare (coupling nucleare–rinnovabili)

Tab dedicato nella vista flotta: come è cambiata la **forma della giornata** del
parco francese al crescere del fotovoltaico. Ogni anno è normalizzato sulla propria
media (100 = media annua), così si confronta la forma e non il livello.

Il risultato, sul parco 2015–2026: **la curva si è ribaltata**.

| Anno | Divario mezzogiorno − notte |
|------|-----------------------------|
| 2015 | **+3,5** punti |
| 2020 | +2,0 |
| 2023 | +0,2 |
| 2025 | **−5,8** |
| 2026 | **−7,6** |

Fino al 2022 il nucleare francese produceva *più* nelle ore centrali che di notte.
Dal 2024 produce **meno**: il minimo giornaliero si è spostato dalla notte a
mezzogiorno, quando il fotovoltaico copre la domanda.

È la prova, ora per ora, che nucleare e rinnovabili **non sono alternativi**: la
convivenza è già in atto. *Quanto* possa spingersi lo dice il tab
**Capacità di modulazione** (~3,6 GW sostenibili al giorno contro un picco di ~18).

---

## 🔌 Quanto fotovoltaico regge il sistema

Tab che incrocia la modulazione oraria del nucleare con i dati solari francesi
(`data/solar_france.csv`, fonte RTE): capacità installata, quota di domanda
coperta, e **curtailment durante i prezzi negativi**.

| Anno | PV GW | Quota max | Tagliato | Calo nucleare a mezzogiorno |
|------|-------|-----------|----------|------------------------------|
| 2020 | 10,4 | 17,5% | 0,4% | −0,4 GW |
| 2022 | 16,1 | 27,5% | **0%** | −0,2 GW |
| 2023 | 19,5 | 30,4% | 1,5% | +0,8 GW |
| 2024 | 24,5 | 39,3% | 5,1% | +2,9 GW |
| 2025 | 30,4 | 47,3% | 8,8% | **+4,5 GW** |
| 2026* | 33,3 | 52,1% | 10,0% | **+4,5 GW** |

**Non esiste una "quota massima integrabile" universale**: il tetto non è fisico
ma di sistema, e si sposta con la flessibilità disponibile (accumuli,
interconnessioni, domanda spostabile).

Quello che i dati mostrano è **quando il margine attuale si esaurisce**: il calo
di mezzogiorno del nucleare ha raggiunto ~4,5 GW e ha smesso di crescere, mentre
la curtailment è salita al ~9–10%. Succede intorno ai **30 GW di PV**. Il valore
combacia con la modulazione sostenibile misurata indipendentemente (~3,6 GW/giorno):
il parco sta modulando quanto può reggere.

**Controprova, il 2022**: con metà parco fermo per la crisi corrosione e il PV già
a 16 GW, la curtailment è stata **zero**. Il vincolo non è il solare in sé, ma la
competizione per lo stesso spazio a mezzogiorno.

*2026 parziale. Dati solari annuali vs nucleari orari: legame forte ma correlativo.
La curtailment è misurata durante prezzi negativi, quindi riflette anche export,
vento e domanda.
