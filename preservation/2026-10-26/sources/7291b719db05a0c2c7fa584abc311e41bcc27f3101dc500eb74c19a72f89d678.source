import pandas as pd, numpy as np
O=pd.read_parquet('osm_addr_8c.parquet'); Bd=pd.read_parquet('cat_buildings.parquet')
Bd['geo']=np.where(Bd.lat.notna(),'osm_exact',None)
grp={k:g.sort_values('num') for k,g in O.groupby(['c','st'])}
def interp(r):
    g=grp.get((r.c,r.st))
    if g is None or len(g)<2: return (np.nan,np.nan)
    n=g.num.values; lo=n[n<r.num]; hi=n[n>r.num]
    if len(lo)==0 or len(hi)==0: return (np.nan,np.nan)
    a=g[g.num==lo.max()].iloc[0]; b=g[g.num==hi.min()].iloc[0]
    if b.num-a.num>400: return (np.nan,np.nan)
    t=(r.num-a.num)/(b.num-a.num)
    la=a.lat+t*(b.lat-a.lat); lo_=a.lon+t*(b.lon-a.lon)
    if np.hypot((b.lat-a.lat)*111000,(b.lon-a.lon)*93000)>600: return (np.nan,np.nan)
    return (la,lo_)
m=Bd.lat.isna()
res=Bd[m].apply(interp,axis=1)
Bd.loc[m,'lat']=[a for a,b in res]; Bd.loc[m,'lon']=[b for a,b in res]
Bd.loc[m & Bd.lat.notna(),'geo']='osm_interp'
# manzana consistency again
g=Bd[Bd.geo=='osm_exact'].groupby(['c','mz'])[['lat','lon']].median().rename(columns={'lat':'mlat2','lon':'mlon2'})
Bd=Bd.merge(g,on=['c','mz'],how='left')
d=np.hypot((Bd.lat-Bd.mlat2)*111000,(Bd.lon-Bd.mlon2)*93000)
bad=(Bd.geo=='osm_interp')&(d>300); Bd.loc[bad,['lat','lon','geo']]=[np.nan,np.nan,None]
Bd.drop(columns=['mlat2','mlon2']).to_parquet('cat_buildings.parquet')
w=Bd[Bd.c.isin([13101,14157,15103,15105,15108,15128,15160,16106])].groupby('c').apply(lambda x: pd.Series({'edif':len(x),'geo_edif':round(x.lat.notna().mean(),2),'geo_deptos':round(x.n[x.lat.notna()].sum()/x.n.sum(),2),'mz_geo':round(x.groupby('mz').lat.apply(lambda s:s.notna().any()).mean(),2)}))
print(w)
