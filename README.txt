Questa cartella ospita i dati. Tre modalità, l'app usa la prima che trova:

1) DATABASE FLOCK (consigliato)
   data/
   ├── Belleville1/
   │   ├── availability.parquet
   │   └── unavailabilities.parquet
   ├── DampierreEnBurly3/
   └── ...
   Una sottocartella per impianto, due Parquet dentro. La libreria Flock è
   vendorizzata nel repo (cartella flock/).

2) ZIP dei CSV  -> data/<qualcosa>.zip  (oppure nella root del repo)

3) CSV sciolti  -> data/*.csv

reactors_metadata.csv (anagrafica reattori) resta sempre qui ed è versionato.
