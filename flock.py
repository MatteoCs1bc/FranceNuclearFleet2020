import duckdb
from pathlib import Path
import pyarrow.parquet as pq
import numpy as np
# PATCH (vendorizzazione nel repo):
# 1) import RELATIVO: 'from converter import ...' funziona solo se src/ è nel
#    sys.path; come package installato/vendorizzato va usato '.converter'.
# 2) import OPZIONALE: converter.py richiede 'alive_progress', che non è tra le
#    dipendenze dichiarate. Serve solo a build_database(), quindi non deve
#    impedire l'import di Flock (che ci serve in sola lettura).
try:
    from .converter import BuildParquetStructure
except Exception:  # noqa: BLE001
    BuildParquetStructure = None

class TableView:
    def __init__(self, flock,name):
        self._f=flock; self._n=name
        
    @property
    def columns(self): return self._f.get_columns()[self._n]
    
    def plants(self, *plants):
        """
        Se chiamato senza argomenti:
            db.availability.plants()
        restituisce la lista dei plant.

        Se chiamato con uno o più plant:
            db.availability.plants("A", "B")
            db.availability.plants(["A", "B"])
        aggiunge il filtro alla query.
        """

        # Nessun argomento -> restituisce la lista dei plant
        if len(plants) == 0:
            return sorted(
                self._f.con.execute(
                    f"SELECT DISTINCT plant FROM {self._n}"
                ).fetchdf()["plant"].tolist()
            )

        # Accetta sia una lista che argomenti multipli
        if len(plants) == 1 and isinstance(plants[0], (list, tuple, set)):
            plants = plants[0]

        self._plants = list(plants)
        return self
    
    def filter(self,expr): self._where=expr; return self
    
    def select(self,*cols): self._cols=cols; return self
    
    def limit(self,n): self._limit=n; return self
    
    def to_pandas(self):

        if hasattr(self, "_cols"):
            cols = list(self._cols)

            # Mantiene sempre la colonna plant
            if "plant" not in cols:
                cols.insert(0, "plant")

            # cols = ",".join(cols)
            cols = ",".join(f'"{c}"' for c in cols)
        else:
            cols = "*"

        query = f"SELECT {cols} FROM {self._n}"

        where = []

        if hasattr(self, "_plants"):
            plist = ",".join(f"'{p}'" for p in self._plants)
            where.append(f"plant IN ({plist})")

        if hasattr(self, "_where"):
            where.append(self._where)

        if where:
            query += " WHERE " + " AND ".join(where)

        if hasattr(self, "_limit"):
            query += f" LIMIT {self._limit}"

        return self._f.sql(query)

class Flock:
    def __init__(self,dirname):
        self.dirname=Path(dirname)
        self.con=duckdb.connect()
        self.update()
    
    def update(self):
        self.meta={}
        groups={}
        for p in self.dirname.glob("*/*.parquet"):
            plant=p.parent.name; table=p.stem
            groups.setdefault(table,[]).append((plant,p))
            self.meta.setdefault(table,None)
            if self.meta[table] is None:
                self.meta[table]=pq.ParquetFile(p).schema_arrow.names
        for t,files in groups.items():
            self.con.execute(f"drop view if exists {t}")
            union=" UNION ALL ".join([f"SELECT '{pl}' plant,* FROM read_parquet('{fp.as_posix()}')" for pl,fp in files])
            self.con.execute(f"create view {t} as {union}")
    
    def get_folders(self): return sorted([d.name for d in self.dirname.iterdir() if d.is_dir()])
    
    def get_tables(self): return sorted(self.meta)
    
    def get_columns(self): return self.meta
    
    def sql(self,q): return self.con.execute(q).fetchdf()
    query=sql
    
    def table(self,name): return TableView(self,name)
    
    def __getattr__(self,n):
        if n in self.meta: return TableView(self,n)
        raise AttributeError

    ######################

    def build_database(self):
        if BuildParquetStructure is None:
            raise ImportError(
                "build_database() richiede il modulo converter e "
                "'alive_progress' (pip install alive-progress)."
            )
        return BuildParquetStructure(self.dirname)
