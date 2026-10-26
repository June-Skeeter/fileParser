from datetime import datetime
import pandas as pd
import numpy as np
import struct
import json
import time
import os
import re

with open(os.path.join(os.path.split(__file__)[0],'templates','settings.json')) as f:
    settings = json.load(f)

def parseFrequency(text,debug=False):
    def split_digit(s):
        match = re.search(r"\d", s)
        if match:
            s = s[match.start():]
        return s 
    freqDict = {'MSEC':'ms','Usec':'us','Sec':'s','HR':'h','MIN':'min','T':'min'}
    freq = split_digit(text)
    for key,value in freqDict.items():
        freq = re.sub(key.lower(), value, freq, flags=re.IGNORECASE)
    freq = re.sub(r'[^a-zA-Z0-9.]','',freq)
    return(freq)

def to_numeric(s):
    try:
        if 'TIMESTAMP' in s.name:
            return(s)
        elif 'RECORD' in s.name:
            return(s.astype('<u4'))
        return(s.astype('<f4'))
    except ValueError:
        return s

class csiTable:
    def __init__(self,kwargs={}):
        self.kwargs = settings['kwargs'] | kwargs
        self.campbellBaseTime = 631152000.0

    def parseHeader(self,fileObject):
        # Read header and parse common parameters between formats
        def readHeaderLine(line):
            if type(line) == str:
                return(line.strip().replace('"','').split(','))
            else:
                return(line.decode('ascii').strip().replace('"','').split(','))
        self.headerRows = [readHeaderLine(fileObject.readline()) for l in range(self.headerRows)]
        if self.headerRows[0][0] != self.fileFormat:
            return
        self.stationName=self.headerRows[0][1]
        self.loggerModel=self.headerRows[0][2]
        self.serialNumber=self.headerRows[0][3]
        self.program=self.headerRows[0][5]

    def userProvidedColumns(self):
        breakpoint()

    def read(self,fileName):
        print(f'Reading: {fileName}')
        if self.fileFormat == 'TOA5':
            self.readTOA5(fileName)
        elif self.fileFormat == 'TOB3':
            self.readTOB3(fileName)
        elif self.fileFormat == 'MixedArray':
            self.readArray(fileName)
        self.setColumns()

        if self.dataTable.index.duplicated().sum():
            if self.kwargs['keepDuplicates'] is None or self.kwargs['keepDuplicates'] not in ['first','last',False,'shift']:
                exit((f'Warning: Duplicated timestamps in: {fileName}\n{self.dataTable.index[self.dataTable.index.duplicated(keep=False)].values}specify set kwargs["keepDuplicates"] to one of ["first","Last",False,"shift"] in order to proceed'))
            elif self.kwargs['keepDuplicates'] == 'shift':
                interval = self.dataTable.index.diff().median()
                cix = pd.Series(self.dataTable.index)
                dix = cix.duplicated().index
                for d in dix:
                    cix[cix>=cix[d]]+=interval
                self.dataTable.index = pd.Index(cix,name=settings['indexName'])
            else:
                print(f'Warning: Duplicated timestamps in: {fileName}\n{self.dataTable.index[self.dataTable.index.duplicated(keep=False)].values}')
                print(f"{self.dataTable.index.duplicated(keep=self.kwargs['keepDuplicates']).sum()} records will be dropped, kepp={self.kwargs['keepDuplicates']}")
                self.dataTable = self.dataTable.loc[~self.dataTable.index.duplicated(keep=self.kwargs['keepDuplicates'])].copy()
        return (self.dataTable)

    def setColumns(self):
        self.columns = {param:self.headerColumns[param] if param in self.headerColumns else ['' for i in self.headerColumns['variableName']]
            for param in settings['columnNames']
        }
        self.columns['dataType'] = [str(d) for d in self.dataTable.dtypes]
        if self.kwargs['columnHeaderOverwrite']:
            for ix,overwrite in self.kwargs['columnHeaderOverwrite'].items():
                if isinstance(ix,str):
                    ix = [i for i,v in enumerate(self.columns['variableName']) if v == ix][0]
                for key,value in overwrite.items():
                    self.columns[key][ix] = value
        self.dataTable.columns = pd.MultiIndex.from_tuples(
            [tuple([
                self.columns[param][i] for param in self.columns.keys()
            ]) for i,_ in enumerate(self.dataTable.columns)],
            names=settings['columnNames']
        )

class TOA5(csiTable):
    def __init__(self,kwargs={}):
        self.fileFormat = 'TOA5'
        self.headerRows = 4
        super().__init__(kwargs)

    def readTOA5(self,fileName):
        with open(fileName,'r') as fileObject:
            self.parseHeader(fileObject)
            self.headerColumns = {
                'variableName':self.headerRows[1],
                'units':self.headerRows[2],
                'processing':self.headerRows[3]
            }
            self.tableName = self.headerRows[0][-1]
            self.dataTable = pd.read_csv(fileObject,names=self.headerColumns['variableName']).apply(to_numeric)
        self.dataTable.index = pd.Index(pd.to_datetime(self.dataTable[self.dataTable.columns[0]],format='ISO8601'),name=settings['indexName'])
        self.recordNumber = self.dataTable['RECORD']

class TOB3(csiTable):
    def __init__(self,kwargs={}):#Stepsize can expedite reading if user only wants to know durration covered by TOB3 and/or extract headers
        self.fileFormat = 'TOB3'
        self.headerRows = 6
        self.headerSize = 12
        self.footerSize = 4
        if 'stepSize' in kwargs:
            self.stepSize=kwargs['stepSize']
        else:
            self.stepSize = 1
        super().__init__(kwargs)

    def readTOB3(self,fileName):
        self.fileSize = os.path.getsize(fileName)
        with open(fileName,'rb') as fileObject:
            self.parseHeader(fileObject)
            self.headerColumns = {
                'variableName':self.headerRows[2],
                'dataTypes':self.translateTypes(self.headerRows[5]),
                'units':self.headerRows[3],
                'processing':self.headerRows[4]
            }
            self.dataIntervalSeconds = pd.to_timedelta(parseFrequency(self.headerRows[1][1])).total_seconds()
            self.frameSize = int(self.headerRows[1][2])
            self.tableSize = int(self.headerRows[1][3])
            self.validationStamp = int(self.headerRows[1][4])
            self.compValidationStamp=(0xFFFF^self.validationStamp)
            self.frameResolution = pd.to_timedelta(parseFrequency(self.headerRows[1][5])).total_seconds()
            self.nframes = int((self.fileSize-fileObject.tell())/self.frameSize)
            self.dtypes = self.translateTypes(self.headerRows[5])
            self.recordSize = struct.calcsize('>'+self.byteMap)
            self.recordsPerFrame = int((self.frameSize-self.headerSize-self.footerSize)/self.recordSize)
            self.byteMap_Body = '>'+''.join([self.byteMap for r in range(self.recordsPerFrame)])
            self.typeMap_Body = self.dtypes*self.recordsPerFrame
            index,data = self.readFrames(fileObject.read())
        if len(index) == 0:
            self.dataTable = pd.DataFrame()
            return
        index = pd.DataFrame(index,columns=['timestamp','RECORD'])
        self.recordNumber = index['RECORD']
        self.dataTable = pd.DataFrame(
            data=data,
            columns=self.headerColumns['variableName'],
            index=pd.Index(
                pd.to_datetime(index['timestamp'],unit='s'),
                name=settings['indexName']
                ),
        )
        self.dataTable.index=self.dataTable.index.round(f'{self.frameResolution}s')
        self.dataTable = self.dataTable.astype({c:d for c,d in zip(self.dataTable.columns,self.dtypes)},errors='ignore')

    def translateTypes(self,dtypes):
        csiTypeMap = {
                    'FP2':{'struct':'H','output':'float32'},
                    'IEEE4B':{'struct':'f','output':'float32'},
                    'IEEE8B':{'struct':'d','output':'float64'},
                    'LONG':{'struct':'l','output':'int64'},
                    'INT4':{'struct':'i','output':'int32'},
                    'ASCII':{'struct':'s','output':'str'},
                }
        self.byteMap = []
        pyTypes = []
        for value in dtypes:
            if value in csiTypeMap:
                self.byteMap.append(csiTypeMap[value]['struct'])
                pyTypes.append(csiTypeMap[value]['output'])
            elif type(value) is str and value.startswith('ASCII'):
                self.byteMap.append(value.strip('ASCII()') + csiTypeMap['ASCII']['struct'])
                pyTypes.append(csiTypeMap['ASCII']['output'])
        self.byteMap = ''.join(self.byteMap)
        return(pyTypes)

    def readFrames(self,fileObject,stepSize=1):
        lrec = struct.calcsize('iii')+struct.calcsize(self.byteMap_Body)+struct.calcsize('i')
        ct = 0
        data = []
        index = []
        T0 = time.time()
        for i in range(0,self.nframes,stepSize):
            cts = ct+lrec
            indices,rows  = self.decodeFrame(fileObject[ct:cts])
            ct = cts
            if indices == []:
                break
            for row,ix in zip(rows,indices):
                data.append(row)
                index.append(ix)
        return(index,data)
    
    def decodeFrame(self,chunk):
        # Adapted from https://github.com/ansell/camp2ascii/blob/cea750fb721df3d3ccc69fe7780b372d20a8160d/frame_read.c#L109
        def Header(chunk):
            Head = struct.unpack('iii', chunk)
            TS = np.dtype('float64').type(Head[0]+self.campbellBaseTime+Head[1]*self.frameResolution)
            RN = np.dtype('int32').type(Head[2])
            return([
                [TS+i*self.dataIntervalSeconds,RN+i]
                for i in range(self.recordsPerFrame)])
        def Body(chunk):
            body = [np.dtype((self.typeMap_Body)[i]).type(vx) for i,vx in enumerate(struct.unpack(self.byteMap_Body, chunk))]
            if 'H' in self.byteMap_Body:
                body = self.decode_fp2(body)
            npr = int(len(body)/self.recordsPerFrame)
            body = [body[i*npr:(i+1)*npr] for i in range(self.recordsPerFrame)]
            return(body)        
        def Footer(chunk):
            Footer = struct.unpack('i',chunk[-self.footerSize:])[0]
            # True/False flag for valid frame
            footerValidation = (0xFFFF0000 & Footer) >> 16
            footerOffset = (0x000007FF & Footer)
            return(footerValidation == self.validationStamp and footerOffset == 0)
        if Footer(chunk[-self.footerSize:]):
            return(Header(chunk[:self.headerSize]),Body(chunk[self.headerSize:-self.footerSize]))
        else:
            return([],[])
  
    def decode_fp2(self,Body):
        # adapted from: https://github.com/ansell/camp2ascii/tree/cea750fb721df3d3ccc69fe7780b372d20a8160d
        def FP2_map(int):
            sign = (0x8000 & int) >> 15
            exponent =  (0x6000 & int) >> 13 
            mantissa = (0x1FFF & int)       
            if exponent == 0: 
                Fresult=mantissa
            elif exponent == 1:
                Fresult=mantissa*1e-1
            elif exponent == 2:
                Fresult=mantissa*1e-2
            else:
                Fresult=mantissa*1e-3

            if sign != 0:
                Fresult*=-1
            return Fresult
        FP2_ix = [m.start() for m in re.finditer('H', self.byteMap_Body.replace('>','').replace('<',''))]
        Body = list(Body)
        for ix in FP2_ix:
            Body[ix] = FP2_map(Body[ix])
        return(Body)

    
class MixedArray(csiTable):
    def __init__(self,kwargs={'fileNameDef':None}):
        self.fileFormat = 'MixedArray'
        super().__init__(kwargs)
        if self.kwargs['fileNameDef'] is None or not os.path.isfile(self.kwargs['fileNameDef']):
            print(self.kwargs['fileNameDef'])
            exit('Give path to def file in kwargs as fileNameDef')
        self.readDEF(kwargs['fileNameDef'])


    def readDEF(self,fileNameDef):
        # self.sourceID = self.fileFormat+'_'+os.path.split(self.templateFile)[-1].split('.')[0]
        with open(fileNameDef,'r',encoding='utf-8-sig') as f:
            lines = f.readlines()
        Header,header = '',True
        Wiring,wiring = '',False
        Labels,labels = {},False
        tableID,Tables,tables,ntables = None,{},False,0
        for i,l in enumerate(lines):
            if 'Output_Table' in l or tables:
                tables = True
                if 'Output_Table' in l:
                    ntables += 1
                    tableID,self.dataIntervalSeconds = [m.strip() for m in l.split('Output_Table')]
                    self.dataIntervalSeconds = pd.to_timedelta(parseFrequency(self.dataIntervalSeconds)).total_seconds()
                    tableID = int(tableID)
                    Tables[tableID] = ''
                else:
                    Tables[tableID]  = Tables[tableID]+l
            elif 'Table Entries' in l:
                entries = True
            elif 'Labels' in l or labels:
                labels = True
                if 'Labels' not in l:
                    l = l.split()
                    if len(l):
                        if not l[0].isdigit():
                            sensor = '_'.join(l)
                        else:
                            Labels[l[1]]=sensor
            elif 'Wiring' in l or wiring:
                if 'Wiring' in l:
                    self.loggerModel = l.split('for ')[-1].rstrip('-\n')
                wiring = True
                Wiring = Wiring+l
            elif header:
                Header = Header+l
        for ID in Tables:
            # data = {param:[] for param in settings['columnNames']}
            self.headerColumns = {'variableName':[],
                                'dataType':[],
                                'units':[],
                                'processing':[]
                                }
            ix = 0
            for v in Tables[ID].split():
                if ix == 1:
                    if v == str(ID):
                        self.headerColumns['variableName'].append(f'ID_{v}')
                        self.headerColumns['dataType'].append('uint16')
                    else:
                        self.headerColumns['variableName'].append(v)
                        if v.endswith('TRM'):
                            self.headerColumns['dataType'].append('uint16')
                        else:
                            self.headerColumns['dataType'].append('float32')
                    operation = v.split('_')[-1]
                    if operation not in ['AVG','STD','MAX','MIN','TOT']:
                        operation = ''
                    r = v.rstrip(f'_{operation}').split('_')
                    if r[-1][0].isdigit():
                        r.pop(-1)
                    if len(r)>1:
                        unit = r[-1]
                    else:
                        unit = ''
                    self.headerColumns['units'].append(unit)
                    self.headerColumns['processing'].append(operation)
                ix += 1
                if ix ==3: ix = 0

    def readArray(self,fileName):
        self.dataTable = pd.read_csv(fileName,names = self.headerColumns['variableName'])
        self.dataTable.index = pd.Index(
            pd.to_datetime(
                self.dataTable['Year_RTM'].astype(str)+'-'+self.dataTable['Day_RTM'].astype(str),format='%Y-%j'
                )+pd.to_timedelta(
                    self.dataTable['Hour_Minute_RTM'].astype(str).str.zfill(4).str[:2]+':'+
                    self.dataTable['Hour_Minute_RTM'].astype(str).str.zfill(4).str[2:4]+':00'
                    ),
            name=settings['indexName'])
        self.dataTable = self.dataTable.astype({key:value for key,value in zip(self.headerColumns['variableName'],self.headerColumns['dataType'])})



# tmp = MixedArray({'fileNameDef':"/mnt/e/data-dump/SCL/2024/20240914/OverWinter.DEF"}).read(fileName="/mnt/e/data-dump/SCL/2025/20250414/WX_data.dat")
# testFile = "/mnt/e/data-dump/RDEC1/decompress/TOA5_79570.Flux_CSFormat_8.dat"
# tmp = TOA5().read(testFile)

# T1 = time.time()
testFile='/mnt/e/data-dump/SCL/2024/20240724/Flux_Data242.dat'
# testFile='/mnt/e/data-dump/SCL/2024/20240912/Flux_Data465.dat'
tmp = TOB3({'keepDuplicates':'shift'}).read(testFile)
# print(time.time()-T1)