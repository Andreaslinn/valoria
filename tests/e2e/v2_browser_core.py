from pathlib import Path
import os,json,re,httpx,traceback
from playwright.sync_api import sync_playwright,expect
ROOT=Path(os.getenv('VALORIA_E2E_OUTPUT',str(Path(__file__).parent/'artifacts')));ROOT.mkdir(exist_ok=True)
BASE=os.getenv('VALORIA_E2E_BASE_URL','http://127.0.0.1:3003');API=os.getenv('VALORIA_E2E_API_URL','http://127.0.0.1:8013')

from urllib.parse import urlparse
assert all(urlparse(u).hostname in {'127.0.0.1','localhost'} for u in [BASE,API]), 'Synthetic browser tests require isolated loopback services'
ROOT.mkdir(parents=True,exist_ok=True)
results=[]
with sync_playwright() as pw:
 browser=pw.chromium.launch(headless=True)
 context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
 context.tracing.start(screenshots=True,snapshots=True,sources=True)
 page=context.new_page();page.set_default_timeout(15000)
 def test(name,fn):
  try:
   fn();results.append({'name':name,'status':'PASS'});print('PASS',name,flush=True)
  except Exception as e:
   page.screenshot(path=str(ROOT/(name+'-failure.png')),full_page=True);(ROOT/(name+'-dom.txt')).write_text(page.locator('body').inner_text(),encoding='utf-8');results.append({'name':name,'status':'FAIL','error':str(e)});print('FAIL',name,str(e)[:400],flush=True)
 def go(path):
  page.goto(BASE+path,wait_until='networkidle');page.wait_for_url(BASE+path)
 def auth():
  go('/resumen');page.get_by_role('button',name='Conecta tu cuenta de Valoria').click();page.get_by_label('Correo electrónico').fill('candidate-a@example.test');page.get_by_label('Contraseña',exact=True).fill('wrong-password');page.get_by_role('button',name='Iniciar sesión',exact=True).last.click();expect(page.get_by_role('dialog').get_by_role('alert')).to_contain_text('incorrectos');page.get_by_label('Contraseña',exact=True).fill('CandidateOnly123!');page.get_by_role('button',name='Iniciar sesión',exact=True).last.click();expect(page.get_by_role('heading',name='Buenos días, candidate-a.')).to_be_visible();page.wait_for_load_state('networkidle')
 test('01-auth-invalid-and-valid',auth)
 token=page.evaluate('localStorage.getItem("valoria_access_token")');assert token,'Login must establish actual session'
 client=httpx.Client(base_url=API,headers={'Authorization':'Bearer '+token},timeout=120)
 def portfolio_cancel():
  go('/portfolio');expect(page.get_by_role('button',name=re.compile('Fixture departamento Independencia 298'))).to_contain_text('Retirada');page.get_by_role('button',name='Quitar de mi cartera',exact=True).click();expect(page.get_by_role('dialog')).to_be_visible();page.get_by_role('button',name='Cancelar',exact=True).click();expect(page.get_by_role('dialog')).not_to_be_visible();assert client.get('/api/v1/watchlist/1130/status').json()['saved'] is True
 test('02-portfolio-historical-and-delete-cancel',portfolio_cancel)
 def alerts():
  go('/alerts');page.get_by_role('button',name='Marcar como leída',exact=True).click();expect(page.get_by_role('heading',name='Tu bandeja está al día.')).to_be_visible();page.get_by_label('Solo pendientes',exact=True).uncheck();expect(page.get_by_role('button',name='Ya revisada',exact=True)).to_be_disabled();page.reload(wait_until='networkidle');page.get_by_label('Solo pendientes',exact=True).uncheck();expect(page.get_by_role('button',name='Ya revisada',exact=True)).to_be_disabled();assert client.get('/api/v1/alerts?include_read=true').json()[0]['is_read'] is True
  other=httpx.post(API+'/api/v1/auth/login',data={'username':'candidate-b@example.test','password':'CandidateOnly123!'});other.raise_for_status();assert httpx.get(API+'/api/v1/alerts',headers={'Authorization':'Bearer '+other.json()['access_token']}).json()[0]['is_read'] is False
 test('03-alert-history-reload-and-user-isolation',alerts)
 def analyzer():
  go('/analizar-url');page.get_by_label('URL de la publicación',exact=True).fill('https://www.yapo.cl/departamento/298');page.get_by_role('button',name='Consultar publicación',exact=True).click();expect(page.locator('body')).to_contain_text('histórica');expect(page.get_by_role('button',name=re.compile('guardada',re.I))).to_be_disabled();print('ANALYZER BUTTONS',page.get_by_role('button').all_text_contents(),flush=True)
 test('04-analyzer-withdrawn-and-saved-initialization',analyzer)
 def radar():
  go('/radar');page.get_by_role('button',name='Buscar oportunidades',exact=True).click();expect(page.locator('body')).to_contain_text('Fixture departamento Independencia 1130');images=page.locator('img[src*="/thumbnails/"]');expect(images.first).to_be_visible();expect(images.first).to_have_js_property('complete',True);assert images.first.evaluate('(img)=>img.naturalWidth')>0;print('RADAR BUTTONS',page.get_by_role('button').all_text_contents(),flush=True);page.screenshot(path=str(ROOT/'radar-ready.png'),full_page=True)
 test('05-radar-real-http-thumbnail',radar)
 def prefill():
  page.get_by_role('button',name='Analizar propiedad',exact=True).last.click();page.get_by_role('link',name='Abrir Analizar URL en Valoria V2',exact=True).click();page.wait_for_url(BASE+'/analizar-url');expect(page.get_by_label('URL de la publicación',exact=True)).to_have_value('https://www.yapo.cl/departamento/31261710');page.reload(wait_until='networkidle');expect(page.get_by_label('URL de la publicación',exact=True)).to_have_value('')
 test('08-radar-secondary-link-prefill-consumed-once',prefill)
 def navigation():
  for label,path in [('Tasar','/tasar'),('Analizar URL','/analizar-url'),('Mi cartera','/portfolio'),('Alertas','/alerts'),('Resumen','/resumen')]:
   page.get_by_role('navigation',name='Navegación principal').locator('a[href="'+path+'"]').click();page.wait_for_url(BASE+path);expect(page.get_by_role('main')).to_be_visible()
 test('06-native-navigation',navigation)
 def logout():
  other=context.new_page();other.goto(BASE+'/portfolio',wait_until='networkidle');expect(other.locator('body')).to_contain_text('Fixture departamento Independencia 1130');go('/resumen');page.locator('button.profile').click();page.get_by_role('button',name='Cerrar sesión',exact=True).click();expect(page.get_by_role('heading',name='Bienvenido a Valoria.')).to_be_visible();expect(other.locator('body')).not_to_contain_text('Fixture departamento Independencia 1130');assert other.evaluate('localStorage.getItem("valoria_access_token")') is None;other.close()
 test('07-logout-clears-second-tab',logout)
 context.tracing.stop(path=str(ROOT/'candidate-trace.zip'));context.close();browser.close();client.close()
(ROOT/'results.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
raise SystemExit(any(r['status']=='FAIL' for r in results))
