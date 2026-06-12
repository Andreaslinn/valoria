# Release ZIP AVM v2

`scripts/create_release_zip.py` genera paquetes ZIP limpios para distribuir AVM v2
sin secretos, caches, entornos virtuales, logs, bases productivas ni artefactos
locales.

El ZIP se crea en `releases/` con el formato:

```powershell
releases/AVM_v2_beta_YYYYMMDD_HHMM.zip
```

## Uso

Dry-run beta, sin crear archivos:

```powershell
python scripts/create_release_zip.py --mode beta --dry-run
```

Crear ZIP beta:

```powershell
python scripts/create_release_zip.py --mode beta
```

Crear ZIP production:

```powershell
python scripts/create_release_zip.py --mode production
```

Incluir tests o docs cuando el release lo necesite:

```powershell
python scripts/create_release_zip.py --mode beta --include-tests
python scripts/create_release_zip.py --mode beta --include-docs
```

Generar checksum SHA-256 junto al ZIP:

```powershell
python scripts/create_release_zip.py --mode beta --checksum
```

## Demo DB

Solo el modo `demo` puede incluir una base SQLite de demostracion, y el nombre
del archivo debe contener `demo`.

```powershell
python scripts/create_release_zip.py --mode demo --demo-db-path data/tasador_demo.db
```

La DB queda dentro del ZIP como `data/tasador_demo.db`. El script bloquea nombres
como `tasador.db`, `production.db`, `avm.db` y cualquier `.db`, `.sqlite` o
`.sqlite3` que no sea una DB demo explicita.

## Seguridad

El release excluye siempre:

- `.env`, `.git/`, `.venv/`, `.venv-win/`, `venv/`
- `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`
- `.DS_Store`, `*.pyc`, `*.pyo`, `*.log`, `logs/`
- `reports/`, `htmlcov/`, `.coverage`, `avm.egg-info/`
- `releases/`, `backups/`, `node_modules/`, `dist/`, `build/`
- `*.db`, `*.sqlite`, `*.sqlite3`

Tambien falla si un archivo candidato a entrar al ZIP tiene un nombre que
contenga `secret`, `token`, `key`, `password` o `credential`.

## Manifest

Cada ZIP incluye `release_manifest.json` con modo, fecha, commit git si existe,
version de Python, conteos, tamano total, tamano del ZIP, warnings y la lista de
archivos incluidos con su tamano.

Para revisar el manifest desde PowerShell:

```powershell
Expand-Archive releases\AVM_v2_beta_YYYYMMDD_HHMM.zip -DestinationPath tmp_release_check -Force
Get-Content tmp_release_check\release_manifest.json
```

## Verificar checksum

Si se genero `.sha256`, calcula el hash local y comparalo con el archivo:

```powershell
Get-FileHash releases\AVM_v2_beta_YYYYMMDD_HHMM.zip -Algorithm SHA256
Get-Content releases\AVM_v2_beta_YYYYMMDD_HHMM.zip.sha256
```
