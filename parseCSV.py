import pandas as pd
import numpy as np
import json
import time
import os
import re

with open(os.path.join(os.path.split(__file__)[0],'templates','settings.json')) as f:
    settings = json.load(f)


def replace_hobo_garbage(text,unit_text = [(' C ','C')]):
    def set_unit(text,unit_text):
        unit = ''
        for u in unit_text:
            if u[0] in text:
                text.replace(u[0],'')
                unit = u[1]
        return((text,unit,'',''))
    pattern = r'"[^"]*"'
    text = text.replace('#','record')
    text = re.sub(r"LGR.*?,", ",", text)
    text = re.sub(r"SEN.*?,", ",", text)
    text = re.sub(pattern, lambda match: match.group(0).replace(",", " "), text)
    text =  re.sub(r"[^a-zA-Z0-9,]", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = text.replace(', ,',',')
    header = [set_unit(t,unit_text) for t in text.split(',')]
    return(header)

class HOBOcsv:
    # HOBO csv outputs have messy headers and inconsistent date formats
    # Can try to auto-parse, but best approach is to define explicitly
    def __init__(self):
        self.fileFormat='HOBOcsv'
        self.skiprows=2

    def read(self,fileName,header=None):
        print(fileName)
        with open(fileName,'rb') as f:
            for l in range(self.skiprows):
                line = f.readline().decode('ascii',errors='ignore')
                if l == 1:
                    header = replace_hobo_garbage(line)
        self.dataTable = pd.read_csv(fileName,skiprows=self.skiprows,header=None,encoding_errors='replace')
        float_cols = self.dataTable.select_dtypes(include=["float64"]).columns
        self.dataTable[float_cols] = self.dataTable[float_cols].astype('float32')
        int_cols = self.dataTable.select_dtypes(include=["int64"]).columns
        self.dataTable[int_cols] = self.dataTable[int_cols].astype('uint32')
        try:
            self.dataTable.columns = [h[0] for h in header]
        except:
            breakpoint()
        if 'Date' and 'Time' in self.dataTable.columns:
            index = pd.to_datetime(self.dataTable['Date']+'T'+self.dataTable['Time'],format='%y/%m/%dT%H:%M:%S')
        else:
            date_time = self.dataTable.columns[self.dataTable.columns.str.contains('Date Time')][0]
            index = pd.to_datetime(self.dataTable[date_time])

        self.dataTable.columns = pd.MultiIndex.from_tuples([(h[0],h[1],h[2],str(self.dataTable.dtypes[h[0]])) for h in header],names=settings['columnNames'])
        self.dataTable.index = pd.Index(index,name=settings['indexName'])
        return(self.dataTable)

# T1 = time.time()
# tf = ['2026/20260930/20750527-SHSC.WSM.SGT.250718.csv','2025/20250718/20750528-SHSC.SSM.SGT.240720_250718.csv','2025/20250718/20750528-SHSC.SSM.SGT.csv']
# testFile='/mnt/e/data-dump/SCL/'
# for t in tf:
#     tmp = HOBOcsv().read(os.path.join(testFile,t))
#     print(tmp.head())
# print(time.time()-T1)