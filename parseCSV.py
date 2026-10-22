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
    def __init__(self,kwargs=settings['kwargDefaults']):
        self.fileFormat='HOBOcsv' # Option to rename data columns, **only those following the timestamp(s)** due to stupid unpredictability of these files
        if kwargs != {}:
            self.dataNames = kwargs['dataNames'].copy()

    def read(self,fileName):
        print(f'Reading: {fileName}')
        with open(fileName,'rb') as f:
            for l in range(2):
                line = f.readline().decode('ascii',errors='ignore').strip('\r\n')
                if l == 0:
                    continue
                if '"' in line:
                    f.close()
                    self.dataTable = pd.read_csv(fileName,skiprows=1,header=[0],encoding_errors='replace')
                else:
                    # remove excessive commans, when quotes in header were not preserved
                    # One of (potentially infite) errors that must be fixed in these dubm headers 
                    line =  [l for l in line.split(',') if l.strip() != '']
                    self.dataTable = pd.read_csv(f,names=line)
        float_cols = self.dataTable.select_dtypes(include=["float64"]).columns
        self.dataTable[float_cols] = self.dataTable[float_cols].astype('float32')
        int_cols = self.dataTable.select_dtypes(include=["int64"]).columns
        self.dataTable[int_cols] = self.dataTable[int_cols].astype('uint32')
        self.dataTable.columns = [re.sub(r"[^a-zA-Z0-9#]", " ", h).replace('#','record') for h in self.dataTable.columns]
        if 'Date' and 'Time' in self.dataTable.columns:
            if self.dataTable['Time'].str.contains('PM').sum():
                breakpoint()
            index = pd.to_datetime(self.dataTable['Date'],yearfirst=True)+pd.to_timedelta(self.dataTable['Time'])
        else:
            date_time = self.dataTable.columns[self.dataTable.columns.str.contains('Date Time')][0]
            index = pd.to_datetime(self.dataTable[date_time],yearfirst=True)
        if not self.dataNames:
            self.dataTable.columns = pd.MultiIndex.from_tuples([(h,'','',str(t)) for h,t in self.dataTable.dtypes.items()],names=settings['columnNames'])
        else:
            # ugly hack to overwrite unpredictable column headers in these dumb csv files
            tmpNames = [(h,'','',str(t)) for h,t in self.dataTable.dtypes.items()]
            tsIx = max([i for i in range(len(tmpNames)) if 'time' in tmpNames[i][0].lower()])+1
            addNames = [self.dataNames[par] if par in self.dataNames else ['' for i in range(len(self.dataNames['variableName']))] if par != 'dataType' else [str(d) for d in self.dataTable.dtypes[tsIx+1:tsIx+1+len(self.dataNames['variableName'])].values] for par in settings['columnNames']]
            addNames = [tuple([addNames[j][i] for j in range(len(settings['columnNames']))]) for i in range(len(self.dataNames['variableName']))]
            tmpNames[tsIx:tsIx+len(self.dataNames['variableName'])]=addNames
            self.dataTable.columns = pd.MultiIndex.from_tuples(tmpNames,names=settings['columnNames'])
        self.dataTable.index = pd.Index(index,name=settings['indexName'])
        return(self.dataTable)

# T1 = time.time()
# tf = ['2026/20260930/20750527-SHSC.WSM.SGT.250718.csv','2025/20250718/20750528-SHSC.SSM.SGT.240720_250718.csv','2025/20250718/20750528-SHSC.SSM.SGT.csv']
# testFile='/mnt/e/data-dump/SCL/'
# for t in tf:
#     tmp = HOBOcsv().read(os.path.join(testFile,t))
#     print(tmp.head())
# print(time.time()-T1)