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

# @dataclass(kw_only=True)
class csiTable:

    def __init__(self):
        self.campbellBaseTime = 631152000.0

    def parseHeader(self,fileObject):
        # Read header and parse common parameters between formats
        def readHeaderLine(line):
            if type(line) == str:
                return(line.strip().replace('"','').split(','))
            else:
                return(line.decode('ascii').strip().replace('"','').split(','))
        self.header = [readHeaderLine(fileObject.readline()) for l in range(self.headerRows)]
        if self.header[0][0] != self.fileFormat:
            return
        self.stationName=self.header[0][1]
        self.loggerModel=self.header[0][2]
        self.serialNumber=self.header[0][3]
        self.program=self.header[0][5]

    def read(self,fileName):
        print(f'Reading: {fileName}')
        if self.fileFormat == 'TOA5':
            self.readTOA5(fileName)
        elif self.fileFormat == 'TOB3':
            self.readTOB3(fileName)
        return (self.dataTable)

class TOA5(csiTable):

    def __init__(self):
        self.fileFormat = 'TOA5'
        self.headerRows = 4
        super().__init__()

    def readTOA5(self,fileName):
        with open(fileName,'r') as fileObject:
            self.parseHeader(fileObject)
            self.tableName = self.header[0][-1]
            def to_numeric(s):
                try:
                    if 'TIMESTAMP' in s.name:
                        return(s)
                    elif 'RECORD' in s.name:
                        return(s.astype('<u4'))
                    return(s.astype('<f4'))
                except ValueError:
                    return s
            self.dataTable = pd.read_csv(fileObject,names=self.header[1]).apply(to_numeric)
        self.dataTable.columns=pd.MultiIndex.from_tuples([(self.header[1][i],self.header[2][i],self.header[3][i],str(self.dataTable.dtypes.iloc[i])) for i in range(len(self.header[1]))],names=settings['columnNames'])
        self.dataTable.index = pd.to_datetime(self.dataTable[self.dataTable.columns[0]],format='ISO8601')
        self.dataTable.index.name = settings['indexName']


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

class TOB3(csiTable):
    def __init__(self,stepSize=1):#Stepsize can expedite reading if user only wants to know durration covered by TOB3 and/or extract headers
        self.fileFormat = 'TOB3'
        self.headerRows = 6
        self.headerSize = 12
        self.footerSize = 4
        self.stepSize=stepSize
        super().__init__()

    def readTOB3(self,fileName):
        self.fileSize = os.path.getsize(fileName)
        with open(fileName,'rb') as fileObject:
            self.parseHeader(fileObject)
            self.dataIntervalSeconds = pd.to_timedelta(parseFrequency(self.header[1][1])).total_seconds()
            self.frameSize = int(self.header[1][2])
            self.tableSize = int(self.header[1][3])
            self.validationStamp = int(self.header[1][4])
            self.compValidationStamp=(0xFFFF^self.validationStamp)
            self.frameResolution = pd.to_timedelta(parseFrequency(self.header[1][5])).total_seconds()
            self.nframes = int((self.fileSize-fileObject.tell())/self.frameSize)
            self.dtypes = self.translateTypes(self.header[5])
            self.recordSize = struct.calcsize('>'+self.byteMap)
            self.recordsPerFrame = int((self.frameSize-self.headerSize-self.footerSize)/self.recordSize)
            self.byteMap_Body = '>'+''.join([self.byteMap for r in range(self.recordsPerFrame)])
            self.readFrames(fileObject.read())

    def translateTypes(self,dtypes):
        csiTypeMap = {
                    'FP2':{'struct':'H','output':'<f4'},
                    'IEEE4B':{'struct':'f','output':'<f4'},
                    'IEEE8B':{'struct':'d','output':'<f8'},
                    'LONG':{'struct':'l','output':'<i8'},
                    'INT4':{'struct':'i','output':'<i4'},
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
        if len(index) == 0:
            self.dataTable = pd.DataFrame(
                data=data,
                index=pd.Index(index,name=settings['indexName']),
                columns=pd.MultiIndex.from_tuples([tuple([self.header[k][j] for k in range(2,6)]) for j in range(len(self.header[2]))],names=settings['columnNames'])
                )
        else:
            index = pd.DataFrame(index)
            index=pd.to_datetime(index[0]*1e9+index[1],unit='ns')
            self.dataTable = pd.DataFrame(
                data=data,
                index=pd.Index(index,name=settings['indexName']),
                columns=pd.MultiIndex.from_tuples([tuple([self.header[k][j] for k in range(2,6)]) for j in range(len(self.header[2]))],names=settings['columnNames'])
                )
            self.dataTable = self.dataTable.astype({c:self.dtypes[i] for i,c in enumerate(self.dataTable.columns)})
        
    def decodeFrame(self,chunk):
        frame = [struct.unpack('iii', chunk[:self.headerSize]),
                 struct.unpack(self.byteMap_Body, chunk[self.headerSize:-self.footerSize]),
                 struct.unpack('i',chunk[-self.footerSize:])[0]]
        frame[0] = [int((frame[0][0]+self.campbellBaseTime)),int((frame[0][1]*self.frameResolution)*1e9),frame[0][2]]
        if 'H' in self.byteMap_Body:
            frame[1] = self.decode_fp2(frame[1])
        npr = int(len(frame[1])/self.recordsPerFrame)
        frame[1] = [frame[1][i*npr:(i+1)*npr] for i in range(self.recordsPerFrame)]
        # True/False flag for valid frame
        # Adapted from https://github.com/ansell/camp2ascii/blob/cea750fb721df3d3ccc69fe7780b372d20a8160d/frame_read.c#L109
        
        footerValidation = (0xFFFF0000 & frame[2]) >> 16
        footerOffset = (0x000007FF & frame[2])
        frame[2] = (footerValidation == self.validationStamp)
        # For handling partial frames
        if frame[2] and footerOffset > 0:
            d = self.frameSize-(footerOffset+self.headerSize+self.footerSize)
            if d:
                offset = int(d/self.recordSize)
            else:
                offset = 0
        else:
            offset = self.recordsPerFrame
        index = [[int((frame[0][0]+frame[0][1]*1e-9+self.dataIntervalSeconds*i)//1),int((frame[0][1]+self.dataIntervalSeconds*i*1e9) % 1e9),frame[0][2]+i] for i in range(self.recordsPerFrame) if i<offset and frame[2]]
        data = [frame[1][i] for i in range(self.recordsPerFrame) if i < offset and frame[2]]
        return(index,data)
  
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
    
# T1 = time.time()
# testFile='/mnt/e/data-dump/SCL/2026/20260801/57840_Flux_CSFormat_33.dat'
# tmp = TOB3().read(testFile)
# print(time.time()-T1)