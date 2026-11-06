#!/usr/bin/env python
import os,glob
import eficiencia
from netCDF4 import Dataset
from datetime import datetime, timedelta
import  numpy as np
import gsw as g

def SaveMaremotermicClima(fecha, depth, lon, lat, temp, cadena):
	#AQUI SE GUARDA EL ARCHIVO TXT CON LOS DATOS PARA LUEGO IMPORTAR A LA BASE DE DATOS
    texto = open(cadena,'a')
    texto.write(str(fecha) + ',' + str(depth) + ',' + str(lon) + ',' + str(lat) + ',' + str(temp) + '\n')
    texto.close()

    print(fecha, depth, lat, lon, temp, 'Safe Record')

def CalculaCT(so, tp):
    return g.CT_from_pt(so, tp)

def Calculat(so, CT, lev):
    return g.t_from_CT(so,CT,lev)

def SearchLevel(l):
    out = ''
    if l == '0':
        out = '1m'
    else:
        if l == '1':
            out = '800m'
        else:
            if l == '2':
                out = '900m'
            else:
                out = '1000m'
    return out
#pp = 0
# 35 es 1000, 33 es 900 y 31 es 750
#dd 35, 33, 31
dd = {0, 1, 2, 3}
# AQUI SE PONE LA DIRECCION DEL ARCHIVO FUENTE

#print fileread

cadena = '/home/Alejandro/Carpeta de Trabajo/output/'

for h in range(2016,2026):
    fileread = Dataset('/home/Alejandro/Carpeta de Trabajo/' + str(h) + '.nc')
    for d in dd:
        for pp in range(0,365):
            so = fileread.variables['so'][pp,d,:]
            T = fileread.variables['thetao'][pp,d,:]
            lat = fileread.variables['latitude'][:]
            lon = fileread.variables['longitude'][:]
            depth = fileread.variables['depth'][d]
            hourss = fileread.variables['time'][pp]
            lat1 = []
            lon1 = []
            for q in range(0,45):
                lon1 = np.append(lon1, lon)
                for p in range(0,39):
                    lat1 = np.append(lat1, lat[q])
            #print fileread
            T = T.flatten()
            so = so.flatten()
            table = np.column_stack((lon1, lat1, T, so))
            date = datetime(1970, 1, 1, 00, 00, 00) + timedelta(days=hourss/86400)
            for row in table:
                CT = CalculaCT(float(row[3]), float(row[2]))
                t = Calculat(float(row[3]), CT, float(d))
                lv = SearchLevel(str(d))
                # fecha, depth, lon, lat, temp
                cadena1 = cadena + lv + 'CaribbeanMexico' + str(h) + '.txt'
                SaveMaremotermicClima(date, depth, row[0], row[1], t, cadena1)

    fileread.close()

