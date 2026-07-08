# ⚛️ Nuclear Fleet Analyzer

Dashboard **Streamlit** per l'analisi del parco nucleare francese a partire dai
dati orari di [energygraph.info](https://energygraph.info): **capacity factor**,
**ramp up/down** e **indisponibilità**, per singolo reattore o in forma
**aggregata sulla flotta**.

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

Due modi:

1. **Upload ZIP** — zippa tutti i CSV e caricali dall'interfaccia.
2. **Cartella locale** — metti i CSV in `./data/` e nella sidebar scegli
   *"Cartella locale ./data"* (comodo in sviluppo, niente re-upload).

I CSV in `data/` sono git-ignorati.

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
- **⚡ Capacity Factor** — CF annuale (nominale vs disponibile), stagionalità
  mensile, heatmap Anno×Mese, tabella mensile
- **🔀 Ramp** — distribuzione ramp up/down, percentili, pattern per ora del giorno
- **🔧 Indisponibilità** — timeline eventi, stagionalità, durata per tipo, dettaglio

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
Escursione (swing)    = (p95 − p5 produzione) / nominale ×100 (% Pnom)
N ramp significativi  = ore con |ramp| > 5% del nominale
```

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
