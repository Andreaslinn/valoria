import pandas as pd, numpy as np, re
exec(open('geo.py').read().split('# boundaries')[0])
L=pd.read_csv('cross_400.csv'); Bd=pd.read_parquet('cat_buildings.parquet')
G=Bd[Bd.lat.notna()]
def pick(row):
    if not pd.isna(row.b_addr): return (row.b_addr,'direccion')
    if pd.isna(row.lat) or abs(row.lat)<1: return (None,None)
    g=G[G.c==row.c]; d=np.hypot((g.lat-row.lat)*111000,(g.lon-row.lon)*93000)
    c=g[d<=75].assign(d=d[d<=75])
    if c.empty: return (None,None)
    if not pd.isna(row.yr):
        ok=c[(c.anio-row.yr).abs()<=3]
        if len(ok): return (ok.d.idxmin(),'coords+edad')
        return (None,None)
    return (c.d.idxmin(),'coords')
p=L.apply(pick,axis=1); L['b']=[a for a,b in p]; L['via']=[b for a,b in p]
# validate coords+edad method on address-matched ones (pretend no address)
v=L[L.b_addr.notna()&L.lat.notna()].copy()
def pick2(row):
    r=row.copy(); r['b_addr']=np.nan; return pick(r)[0]
v['b2']=v.apply(pick2,axis=1)
Bmz=Bd.mz
print('Validación coords+edad sobre avisos con dirección:',len(v),'asignados',v.b2.notna().sum(),'mismo edificio',(v.b2==v.b_addr).sum(),'misma manzana',sum(Bmz.get(a)==Bmz.get(b) for a,b in zip(v.b2,v.b_addr) if not pd.isna(a)))
print(L.via.value_counts(dropna=False).to_dict(), 'por fuente:', L[L.b.notna()].src.value_counts().to_dict(), 'de', L.src.value_counts().to_dict())
# SII units in assigned buildings
cat=pd.read_parquet('cat_deptos.parquet'); c8=pd.read_parquet('/workspace/work/sii_join/catastro_8c.parquet')[['c','mz','pr','m2_H_abierta']]
cat=cat.merge(c8,on=['c','mz','pr'],how='left'); cat['m2_cerr']=cat.m2_H-cat.m2_H_abierta.fillna(0)
units={k:g for k,g in cat.groupby(['c','mz','st','num'])}
cl=pd.read_parquet('/workspace/work/sii_join/cierres_deptos_ufm2.parquet'); cl=cl[cl.motivo=='ok']
cl=cl.merge(cat[['c','mz','pr','st','num']],on=['c','mz','pr'],how='left')
cls={k:g for k,g in cl.groupby(['c','mz','st','num'])}
ex=pd.read_csv('/workspace/projects/8646fc9a-a15b-4c2c-9f7f-69eab812bd69/files/uploads/valoria_departamentos.csv')
ex['key']=ex.source.str[:4]+ex.external_id.astype(str).str.replace('MLC-','').str.replace('MLC','')
UF=41168.03
ex['puf']=np.where(ex.precio_uf.notna(),ex.precio_uf,ex.precio_clp/UF)
L['key']=L.src.str[:4]+L.id.astype(str).str.replace('MLC-','').str.replace('MLC','')
L=L.merge(ex[['key','puf','activo']],on='key',how='left')
out=[]
for _,r in L[L.b.notna()].iterrows():
    b=Bd.loc[int(r.b)]; k=(b.c,b.mz,b.st,b.num); u=units.get(k)
    rec=dict(src=r.src,id=r.id,c=r.c,via=r.via,util=r.util,total=r.total,constr=r.constr,yr=r.yr,puf=r.puf,anio_sii=b.anio,n_units=b.n)
    if u is not None and not pd.isna(r.util):
        i=(u.m2_cerr-r.util).abs().idxmin(); rec['cerr_near_util']=u.m2_cerr[i]; rec['H_of_that']=u.m2_H[i]
    if u is not None and not pd.isna(r.total):
        rec['H_near_total']=u.m2_H[(u.m2_H-r.total).abs().idxmin()]
    if u is not None and not pd.isna(r.constr) and pd.isna(r.util):
        rec['H_near_constr']=u.m2_H[(u.m2_H-r.constr).abs().idxmin()]
    c=cls.get(k)
    size=r.total if not pd.isna(r.total) else r.constr
    if c is not None and not pd.isna(size):
        s=c[(c.m2_H-size).abs()<=0.12*size]
        rec['n_cierres_simil']=len(s); rec['cierre_med_uf']=s.UF.median() if len(s) else np.nan
        rec['ufm2_cierre_edif']=c.ufm2.median(); rec['n_cierres_edif']=len(c)
    out.append(rec)
R=pd.DataFrame(out); R.to_csv('cruce_resultado.csv',index=False)
print('\nasignados',len(R))
P=R[R.src=='portalinmobiliario']
q=P.dropna(subset=['cerr_near_util'])
print('Portal: m² SII cerrado más cercano / útil publicado: mediana %.3f, p25 %.3f, p75 %.3f (n=%d); |dif|<=5%%: %d'%((q.cerr_near_util/q.util).median(),(q.cerr_near_util/q.util).quantile(.25),(q.cerr_near_util/q.util).quantile(.75),len(q),((q.cerr_near_util/q.util-1).abs()<=.05).sum()))
q2=P.dropna(subset=['H_near_total'])
print('Portal: m² SII total más cercano / total publicado: mediana %.3f (n=%d); |dif|<=5%%: %d'%((q2.H_near_total/q2.total).median(),len(q2),((q2.H_near_total/q2.total-1).abs()<=.05).sum()))
print('Portal útil/total publicado: mediana %.3f'%(P.util/P.total).median())
Y=R[R.src=='yapo'].dropna(subset=['H_near_constr'])
if len(Y): print('Yapo construido publicado vs SII total más cercano: mediana %.3f (n=%d)'%((Y.H_near_constr/Y.constr).median(),len(Y)))
g=R.dropna(subset=['puf','cierre_med_uf']); g=g[g.n_cierres_simil>=2]
g['gap']=g.puf/g.cierre_med_uf-1
print('\nGap pedido vs cierres de unidades de tamaño similar en el mismo edificio (>=2 cierres): n=%d, mediana %+.1f%%, p25 %+.1f%%, p75 %+.1f%%'%(len(g),100*g.gap.median(),100*g.gap.quantile(.25),100*g.gap.quantile(.75)))
print(g.groupby('src').gap.agg(['size','median']))
print('con precio:',R.puf.notna().sum(),'con cierres similares>=2:',(R.n_cierres_simil>=2).sum())
