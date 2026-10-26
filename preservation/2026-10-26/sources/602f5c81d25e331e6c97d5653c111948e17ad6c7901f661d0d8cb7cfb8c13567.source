import csv, re, numpy as np, pandas as pd
from rapidfuzz import fuzz
exec(open('geo.py').read().split('# boundaries')[0])
Bd=pd.read_parquet('cat_buildings.parquet')
CODE={'providencia':15103,'vitacura':15160,'la-florida':15128,'la_florida':15128,'estacion-central':14157,'estacion_central':14157,'san-miguel':16106,'san_miguel':16106,'santiago':13101,'las_condes':15108,'las-condes':15108,'nunoa':15105}
r=[x for x in csv.DictReader(open('ba.csv',encoding='utf-8-sig')) if x['published_stage']]
L=[]
for x in r:
    c=CODE.get(x['comuna'])
    f=lambda k:(float(x[k]) if x.get(k) not in (None,'') else np.nan)
    L.append(dict(src=x['source'],id=x['published_external_id'],c=c,atype=x['published_address_type'],street=x['published_street'],num=x['published_address_number'],
      lat=f('published_latitude'),lon=f('published_longitude'),util=f('published_useful_area_m2'),total=f('published_total_area_m2'),constr=f('published_constructed_area_m2'),
      age=f('published_age_years'),year=f('published_construction_year'),floor=f('published_floor')))
L=pd.DataFrame(L); L=L[L.c.notna()].copy(); L['c']=L.c.astype(int)
L['yr']=np.where(L.year.notna(),L.year,2026-L.age)
print('fichas en 8 comunas',len(L),L.src.value_counts().to_dict())
# A) address match (fuzzy street, same number)
def amatch(row):
    try:n=int(float(row.num))
    except:return None
    if not row.street: return None
    st=norm(row.street); cand=Bd[(Bd.c==row.c)&(Bd.num==n)]
    if cand.empty: return None
    sc=cand.st.map(lambda s: max(fuzz.token_set_ratio(s,st),fuzz.partial_ratio(s,st)) if s else 0)
    best=sc.idxmax()
    return best if sc[best]>=80 else None
L['b_addr']=L.apply(amatch,axis=1)
# B) coords -> nearest geolocated building
G=Bd[Bd.lat.notna()]
def near(row):
    if np.isnan(row.lat) or abs(row.lat)<1: return (None,np.nan)
    g=G[G.c==row.c]
    if g.empty: return (None,np.nan)
    d=np.hypot((g.lat-row.lat)*111000,(g.lon-row.lon)*93000)
    i=d.idxmin(); return (i,d[i])
nn=L.apply(near,axis=1); L['b_xy']=[a for a,b in nn]; L['d_xy']=[b for a,b in nn]
def get(i,k): return Bd.at[i,k] if i is not None and not pd.isna(i) else np.nan
for k in ['mz','anio','m2med','n','lat','lon']:
    L['A_'+k]=[get(i,k) for i in L.b_addr]; L['X_'+k]=[get(i,k) for i in L.b_xy]
L['d_addr_coords']=np.hypot((L.A_lat-L.lat)*111000,(L.A_lon-L.lon)*93000)
ex=L[L.atype=='exact']
print('\nA) direcciones exactas:',len(ex),' con edificio SII:',ex.b_addr.notna().sum())
a=L[L.b_addr.notna()]
print('   edad coincide ±3 años:', ((a.yr-a.A_anio).abs()<=3).sum(),'de',a.yr.notna().sum())
v=a[a.A_lat.notna()&a.lat.notna()]
print('\nB) validación coords (avisos con edificio por dirección y edificio geolocalizado):',len(v))
print('   distancia coords publicadas -> edificio: mediana %.0f m, p75 %.0f m, p90 %.0f m'%tuple(v.d_addr_coords.quantile([.5,.75,.9])))
print('   mismo edificio por coords:',(v.b_xy==v.b_addr).sum(),' misma manzana:',(v.X_mz==v.A_mz).sum(),'de',len(v))
for s,g in v.groupby('src'): print('   ',s,len(g),'mediana %.0f m'%g.d_addr_coords.median(),'misma mz',(g.X_mz==g.A_mz).sum())
x=L[L.b_xy.notna()]
print('\nC) avisos con coords asignables:',len(x),'de',len(L),'; a <=50 m de un edificio:',(x.d_xy<=50).sum(),'; <=100 m:',(x.d_xy<=100).sum())
x50=x[x.d_xy<=50]
print('   edad coincide ±3 años (<=50 m):',((x50.yr-x50.X_anio).abs()<=3).sum(),'de',x50.yr.notna().sum())
L.to_csv('cross_400.csv',index=False)
