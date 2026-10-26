import json, re, glob, unicodedata, collections
import pandas as pd, numpy as np
from shapely.geometry import Polygon, Point, MultiPolygon
from shapely.ops import polygonize, unary_union
from shapely.geometry import LineString
def norm(s):
    s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode().upper()
    s=re.sub(r'[^A-Z0-9 ]',' ',s)
    rep={'AVENIDA':'','AVDA':'','AV':'','CALLE':'','PASAJE':'','PJE':'','PJ':'','GENERAL':'','GRAL':'','GRAL':'','DOCTOR':'','DR':'','PRESIDENTE':'','PDTE':'','PTE':'','CAPITAN':'','CAP':'','SANTA':'STA','SAN':'S','PROFESOR':'','PROF':'','ALMIRANTE':'','ALM':'','MONSENOR':'','MONS':'','CORONEL':'','CRL':'','DE':'','DEL':'','LA':'','LAS':'','LOS':'','EL':'','Y':'','LATERAL':'','CAMINO':'','PASEO':'','LIBERTADOR':'','BERNARDO':''}
    t=[rep.get(w,w) for w in s.split()]
    return ' '.join(w for w in t if w)
# boundaries
NAME2C={'Santiago':13101,'Ñuñoa':15105,'Providencia':15103,'Las Condes':15108,'Vitacura':15160,'La Florida':15128,'San Miguel':16106,'Estación Central':14157}
B={}
for e in json.load(open('osm_bnd.json'))['elements']:
    lines=[LineString([(p['lon'],p['lat']) for p in m['geometry']]) for m in e['members'] if m['type']=='way' and m.get('role')=='outer' and m.get('geometry')]
    polys=list(polygonize(unary_union(lines)))
    B[NAME2C[e['tags']['name']]]=unary_union(polys)
print({k:round(v.area*1e4,1) for k,v in B.items()})
# osm addresses
rows=[]
for e in json.load(open('osm_addr.json'))['elements']:
    t=e['tags']; lat=e.get('lat') or e.get('center',{}).get('lat'); lon=e.get('lon') or e.get('center',{}).get('lon')
    m=re.match(r'\d+',t['addr:housenumber'].strip())
    if not m or lat is None: continue
    rows.append((norm(t['addr:street']),int(m.group()),lat,lon))
O=pd.DataFrame(rows,columns=['st','num','lat','lon']).drop_duplicates(['st','num','lat','lon'])
def comuna_of(lon,lat):
    p=Point(lon,lat)
    for c,g in B.items():
        if g.contains(p): return c
    return None
O['c']=[comuna_of(a,b) for a,b in zip(O.lon,O.lat)]
O=O[O.c.notna()]; O['c']=O.c.astype(int)
print('osm addr in 8c',len(O), O.c.value_counts().to_dict())
O=O.groupby(['c','st','num'],as_index=False)[['lat','lon']].median()
O.to_parquet('osm_addr_8c.parquet')
# catastro buildings
cat='/workspace/work/sii_join/cat/'
N=pd.concat([pd.read_csv(f,sep='|',header=None,names=['c','mz','pr','dir'],usecols=range(4),dtype=str,encoding='latin1') for f in glob.glob(cat+'BRTMPCATASN_2026_2_*')])
for k in ['c','mz','pr']:N[k]=N[k].astype(int)
N['dir']=N.dir.str.strip()
m=N.dir.str.extract(r'^(.*?)\s+(\d+)\b')
N['st']=m[0].map(lambda x: norm(x) if isinstance(x,str) else None); N['num']=pd.to_numeric(m[1],errors='coerce')
N['dp']=N.dir.str.contains(r'\b(?:DP|DEPTO|DPTO|DEP)\b')
cs=pd.read_parquet('/workspace/work/sii_join/catastro_8c.parquet')[['c','mz','pr','m2_H','anio']]
N=N.merge(cs,on=['c','mz','pr'],how='left')
D=N[N.dp & N.m2_H.notna() & N.num.notna()].copy(); D['num']=D.num.astype(int)
D.to_parquet('cat_deptos.parquet')
Bd=D.groupby(['c','mz','st','num']).agg(n=('pr','size'),m2med=('m2_H','median'),anio=('anio','median')).reset_index()
Bd=Bd.merge(O,on=['c','st','num'],how='left')
# manzana consistency: drop geolocations > 400 m from manzana median
g=Bd[Bd.lat.notna()].groupby(['c','mz'])[['lat','lon']].median().rename(columns={'lat':'mlat','lon':'mlon'})
Bd=Bd.merge(g,on=['c','mz'],how='left')
d=np.hypot((Bd.lat-Bd.mlat)*111000,(Bd.lon-Bd.mlon)*93000)
Bd.loc[d>400,['lat','lon']]=np.nan
Bd.to_parquet('cat_buildings.parquet')
w=Bd.groupby('c').apply(lambda x: pd.Series({'edif':len(x),'geo_edif':x.lat.notna().mean(),'deptos':x.n.sum(),'geo_deptos':x.n[x.lat.notna()].sum()/x.n.sum()}))
print(w)
