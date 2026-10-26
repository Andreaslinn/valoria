import pandas as pd, numpy as np, glob, re, json
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 40)
CODE = {'PROVIDENCIA':15103,'VITACURA':15160,'LA FLORIDA':15128,'ESTACION CENTRAL':14157,
        'SAN MIGUEL':16106,'SANTIAGO CENTRO':13101,'LAS CONDES':15108,'NUNOA':15105}
NAME = {v:k.title() for k,v in CODE.items()}; NAME[13101]='Santiago'; NAME[15105]='Ñuñoa'; NAME[14157]='Estación Central'
cat = 'cat/'
# ---------- catastro N (one row per rol)
Ncols = ['c','mz','pr','dir','avaluo','contrib','dest','exento','bc1c','bc1m','bc1p','bc2c','bc2m','bc2p','supter','ubic','pc','pm','pp']
N = pd.concat([pd.read_csv(f, sep='|', header=None, names=Ncols+['x'], usecols=range(19), dtype=str, encoding='latin1')
               for f in glob.glob(cat+'BRTMPCATASN_2026_2_*')])
for k in ['c','mz','pr']: N[k] = N[k].astype(int)
N['dir'] = N['dir'].str.strip(); N['dest'] = N['dest'].str.strip()
N['avaluo'] = pd.to_numeric(N.avaluo, errors='coerce')
N['dp'] = N['dir'].str.contains(r'\b(DP|DEPTO|DPTO|DEP)\b', regex=True)
N['bx'] = N['dir'].str.contains(r'\b(BX|BD|EST|BOD)\b', regex=True)
# ---------- catastro NL (lines)
Lcols = ['c','mz','pr','lin','mat','cal','anio','sup','dest','cond','pisos']
L = pd.concat([pd.read_csv(f, sep='|', header=None, names=Lcols+['x'], usecols=range(11), dtype=str, encoding='latin1')
               for f in glob.glob(cat+'BRTMPCATASNL_2026_2_*')])
for k in ['c','mz','pr']: L[k] = L[k].astype(int)
L['sup'] = pd.to_numeric(L.sup, errors='coerce'); L['dest'] = L.dest.str.strip(); L['cond'] = L.cond.fillna('').str.strip()
L['anio'] = pd.to_numeric(L.anio, errors='coerce')
H = L[(L.dest=='H') & (L.sup>0)].copy()
H['ab'] = np.where(H.cond=='CA', H.sup, 0)
agg = H.groupby(['c','mz','pr']).agg(m2_H=('sup','sum'), n_lin_H=('sup','size'), anio=('anio','min'),
        m2_H_abierta=('ab','sum'), pisos=('pisos','first')).reset_index()
agg['m2_H_cerrada'] = agg.m2_H - agg.m2_H_abierta
N = N.merge(agg, on=['c','mz','pr'], how='left')
N['tipo'] = np.select([(N.dest=='H') & N.dp, (N.dest=='H') & ~N.dp, N.dest=='Z', N.dest=='L'],
                      ['depto','casa_u_otro_H','estac','bodega'], 'otro')
# building size proxy: roles per manzana with DP
mzdp = N[N.tipo=='depto'].groupby(['c','mz']).size().rename('deptos_mz')
N = N.merge(mzdp, on=['c','mz'], how='left'); N['deptos_mz'] = N.deptos_mz.fillna(0)
cat_summary = pd.crosstab(N.c, N.tipo)
dep = N[N.tipo=='depto']
cat_summary['deptos_con_m2'] = dep.groupby('c').m2_H.apply(lambda s: s.notna().mean()).round(3)
cat_summary['m2_mediana_depto'] = dep.groupby('c').m2_H.median()
cat_summary['share_con_terraza_CA'] = dep.groupby('c').m2_H_abierta.apply(lambda s:(s>0).mean()).round(3)
print(cat_summary)
# ---------- F2890
F = pd.read_csv('f2890raw/F2890_01-10-2026.txt', sep=';', dtype=str, encoding='latin1')
F = F[F.COMUNA.isin(CODE)].copy()
F['c'] = F.COMUNA.map(CODE); F['mz'] = pd.to_numeric(F.MANZANA, errors='coerce'); F['pr'] = pd.to_numeric(F.PREDIO, errors='coerce'); F = F.dropna(subset=['mz','pr']); F['mz']=F.mz.astype(int); F['pr']=F.pr.astype(int)
F['fi'] = pd.to_datetime(F.FECHA_INSCRIPCION, format='%Y%m%d', errors='coerce')
F = F[(F.fi >= '2024-01-01')].copy()
F['fe'] = pd.to_datetime(F.FECHA_ESCRITURA, format='%Y%m%d', errors='coerce')
F['MONTO_UF'] = pd.to_numeric(F.MONTO_UF, errors='coerce').fillna(0); F['MONTO_PESOS'] = pd.to_numeric(F.MONTO_PESOS, errors='coerce').fillna(0)
uf = pd.read_csv('uf_daily.csv', parse_dates=['fecha']).set_index('fecha').uf
F['fconv'] = F.fe.where((F.fe >= '2024-01-01') & (F.fe <= F.fi), F.fi)
F['uf_dia'] = F.fconv.map(uf).fillna(F.fi.map(uf))
F['UF'] = np.where(F.MONTO_UF > 0, F.MONTO_UF, np.where(F.MONTO_PESOS > 0, F.MONTO_PESOS / F.uf_dia, 0.0))
n_raw = F.groupby('c').size()
F = F.sort_values('UF', ascending=False).drop_duplicates(['c','mz','pr','FECHA_INSCRIPCION','FECHA_ESCRITURA'])
n_dedup = F.groupby('c').size()
F = F.merge(N[['c','mz','pr','tipo','dest','dir','m2_H','m2_H_cerrada','m2_H_abierta','anio','avaluo','deptos_mz']], on=['c','mz','pr'], how='left')
F['join'] = F.tipo.notna()
gk = ['c','mz','FECHA_ESCRITURA','FECHA_INSCRIPCION']
F['g_roles'] = F.groupby(gk).pr.transform('size')
F['_d']=(F.tipo=='depto').astype(int)
F['g_deptos']=F.groupby(gk)._d.transform('sum')
F['_pos']=(F.UF>0).astype(int)
F['g_priced']=F.groupby(gk)['_pos'].transform('sum')
F['_aux']=((F.tipo.isin(['estac','bodega']))&(F.UF<=0)).astype(int)
F['g_aux_unpriced']=F.groupby(gk)._aux.transform('sum')
F['_pos']=(F.UF>0).astype(int)
F['g_nuniq']=F.groupby(gk).UF.transform('nunique')
F['g_same_amt']=(F.g_roles>1)&(F.g_priced==F.g_roles)&(F.g_nuniq==1)
# ---------- comparable depto sales
D = F[(F.tipo=='depto')].copy()
reasons = pd.Series('ok', index=D.index)
reasons[D.UF<=0] = 'sin_monto'
reasons[(reasons=='ok') & D.m2_H.isna()] = 'sin_m2'
reasons[(reasons=='ok') & D.g_same_amt] = 'monto_repetido_en_lote'
reasons[(reasons=='ok') & (D.g_aux_unpriced>0)] = 'incluye_estac_bodega_sin_precio'
reasons[(reasons=='ok') & (D.g_deptos>=10)] = 'lote_masivo_10+_deptos'
D['ufm2'] = D.UF / D.m2_H
reasons[(reasons=='ok') & ((D.m2_H<20)|(D.m2_H>300))] = 'm2_fuera_20_300'
reasons[(reasons=='ok') & ((D.ufm2<15)|(D.ufm2>300))] = 'ufm2_fuera_15_300'
D['motivo'] = reasons
qual = pd.crosstab(D.c.map(NAME), D.motivo, margins=True)
print(qual)
OK = D[D.motivo=='ok'].copy()
OK['comuna'] = OK.c.map(NAME)
OK['m2b'] = pd.cut(OK.m2_H, [0,45,60,75,90,110,140,300], labels=['<45','45-60','60-75','75-90','90-110','110-140','140+'])
OK.to_parquet('cierres_deptos_ufm2.parquet')
res = OK.groupby('comuna').agg(n=('ufm2','size'), ufm2_p25=('ufm2', lambda s:s.quantile(.25)), ufm2_med=('ufm2','median'),
        ufm2_p75=('ufm2', lambda s:s.quantile(.75)), uf_med=('UF','median'), m2_med=('m2_H','median'))
mz = OK.groupby(['comuna','mz']).ufm2.agg(['size','median'])
mz5 = mz[mz['size']>=5]
res['manzanas_n5'] = mz5.groupby('comuna').size()
res['mz_p10'] = mz5.groupby('comuna')['median'].quantile(.1); res['mz_p90'] = mz5.groupby('comuna')['median'].quantile(.9)
print(res.round(1))
bym2 = OK.pivot_table(index='comuna', columns='m2b', values='ufm2', aggfunc='median', observed=False).round(1)
print(bym2)
OK['q'] = OK.fi.dt.to_period('Q').astype(str)
trend = OK.pivot_table(index='comuna', columns='q', values='ufm2', aggfunc='median').round(1); print(trend)
# yearly by construction age
OK['edad'] = pd.cut(2026-OK.anio, [-1,3,10,20,40,200], labels=['0-3','4-10','11-20','21-40','40+'])
age = OK.pivot_table(index='comuna', columns='edad', values='ufm2', aggfunc='median', observed=False).round(1); print(age)
cov = pd.DataFrame({'f2890_filas_2024+': n_raw.rename(NAME), 'dedup': n_dedup.rename(NAME),
                    'join_catastro_%': F.groupby('c').join.mean().mul(100).round(1).rename(NAME),
                    'ventas_depto': D.groupby('c').size().rename(NAME), 'comparables_ok': OK.groupby('c').size().rename(NAME)})
cov['ok_%'] = (cov.comparables_ok/cov.ventas_depto*100).round(1)
print(cov)
for nm, df in [('res',res),('bym2',bym2),('trend',trend),('age',age),('cov',cov),('qual',qual),('cat',cat_summary.rename(NAME))]:
    df.to_csv(f'out6_{nm}.csv')
mz.reset_index().to_csv('out6_manzanas.csv', index=False)
D.to_parquet('deptos_all_motivo.parquet')
F.drop(columns=['_d','_pos','_aux']).to_parquet('f2890_8c_join.parquet')
N[['c','mz','pr','tipo','dest','m2_H','anio','avaluo','n_lin_H','m2_H_abierta']].to_parquet('catastro_8c.parquet')
