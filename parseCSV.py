import pandas as pd
import numpy as np
import json
import time
import os
import re

with open(os.path.join(os.path.split(__file__)[0],'templates','settings.json')) as f:
    settings = json.load(f)

class HOBOcsv:
    # HOBO csv outputs have messy headers and inconsistent date formats
    # Can try to auto-parse, but best approach is to define explicitly
    def __init__(self,kwargs={}):
        self.kwargs = settings['kwargs'] | kwargs
        self.fileFormat='HOBOcsv' # Option to rename data columns, **only those following the timestamp(s)** due to stupid unpredictability of these files

    def read(self,fileName):
        print(f'Reading: {fileName}')
        with open(fileName,'rb') as f:
            for l in range(2):
                line = f.readline().decode('ascii',errors='ignore').strip('\r\n')
                if l == 0:
                    continue
                if '"' in line:
                    f.close()
                    self.dataTable = pd.read_csv(fileName,skiprows=1,header=[0],encoding_errors='replace',index_col=0)
                else:
                    # remove excessive commans, when quotes in header were not preserved
                    # One of (potentially infite) errors that must be fixed in these dubm headers 
                    line =  [l for l in line.split(',') if l.strip() != '']
                    self.dataTable = pd.read_csv(f,names=line,index_col=0)
        # datetime format is frustratingly inconsistent, sometimes split in two columns
        ix = [c for c in self.dataTable.columns if 'Date' in c or 'Time' in c]
        index = self.dataTable[ix].agg(' '.join,axis=1)
        self.dataTable = self.dataTable.drop(columns=ix)
        self.dataTable.index = pd.Index(pd.to_datetime(index,yearfirst=True),name=settings['indexName']).tz_localize(self.kwargs['timezone'])
        float_cols = self.dataTable.select_dtypes(include=["float64"]).columns
        self.dataTable[float_cols] = self.dataTable[float_cols].astype('float32')
        self.columns = {param:['' for i in range(self.dataTable.shape[1])] for param in settings['columnNames']}
        self.columns['variableName'] = list(self.dataTable.columns)
        self.columns['dataType'] = list(self.dataTable.dtypes.values)
        
        if self.kwargs['columnHeaderOverwrite']:
            for ix,overwrite in self.kwargs['columnHeaderOverwrite'].items():
                if isinstance(ix,str):
                    ix = [i for i,v in enumerate(self.columns['variableName']) if v == ix][0]
                for key,value in overwrite.items():
                    self.columns[key][ix] = value
        self.dataTable.columns = pd.MultiIndex.from_tuples(
            [tuple([
                self.columns[param][i] for param in self.columns.keys()
            ]) for i,_ in enumerate(self.columns['variableName'])],
            names=settings['columnNames']
        )
        # Drop text status columns
        self.dataTable = self.dataTable.loc[(self.dataTable=='Logged').sum(axis=1)==0].dropna(axis=1)
        return(self.dataTable)

# T1 = time.time()
# tf = ['2026/20260930/20750527-SHSC.WSM.SGT.250718.csv','2025/20250718/20750528-SHSC.SSM.SGT.240720_250718.csv','2025/20250718/20750528-SHSC.SSM.SGT.csv']
# testFile='/mnt/e/data-dump/SCL/'
# for t in tf:
#     tmp = HOBOcsv({'columnHeaderOverwrite':{0:{'variableName':'TS_5cm'},1:{'variableName':'TS_10cm'},2:{'variableName':'TS_50cm'},3:{'variableName':'TS_100cm'}}}).read(os.path.join(testFile,t))
#     print(tmp.head())
# print(time.time()-T1)
# breakpoint()