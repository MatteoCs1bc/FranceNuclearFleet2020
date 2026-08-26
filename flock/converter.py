import pandas as pd
import os
from pathlib import Path
from alive_progress import alive_bar
import pickle

dirname = 'Parco Francese'


def BuildDictionary(dirname):
    Lfiles = os.listdir(dirname)

    dict_data = {}

    for ff in Lfiles:
        # print(ff)
        
        tag_avail = ff.split('-')[0]    
        # tag_avails.append(tag_avail)
        
        data = ff.split('data')[1].split(' ')[0][1:]
        # date.append(data)
        
        reattore = ff.split('_')[-1][:-4]
        # reactors.append(reattore)
        
        
        ora = ff.split('-')[-1].split(' ')[-1].split(reattore)[0][:-1]
        # start_time.append(ora)    
        
        df = pd.read_csv(os.path.join(dirname,ff))
        df['reattore'] = reattore
        df['avail/unavail'] = tag_avail
        df['data'] = data
        df['start_time'] = ora
        
        dict_data[ff[:-4]] = df
        
        filename = ff.replace('csv', 'parquet')
        df.to_parquet(os.path.join(os.getcwd(),'parquet',filename))

    #saving
    with open('parco_francese.pickle', 'wb') as file:
        pickle.dump(dict_data, file)

def BuildParquetStructure(dirname):

    Lfiles = os.listdir(dirname)

    with alive_bar(title='converting') as bar:
        for ff in Lfiles:
            
            # creo la cartella
            plant_name = ff.split('_')[-1].split('.')[0]
            plant_name = plant_name.replace(' ','_')
            
            parquet_path = Path("data/%s" %plant_name)
            parquet_path.mkdir(parents=True, exist_ok=True)
        
            df = pd.read_csv(os.path.join(dirname,ff))
            
            if 'Unavailabilities' in ff:
                df.to_parquet(os.path.join(parquet_path,'unavailabilities.parquet'))
        
            elif 'Availability' in ff:
                df.to_parquet(os.path.join(parquet_path,'availability.parquet'))
            
            bar()
