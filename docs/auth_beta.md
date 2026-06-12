# Auth beta privada

AVM-v2 usa login real con email y password para beta privada. No hay registro publico:
los usuarios los crea manualmente un admin.

## Crear el primer admin

1. Configura `ADMIN_EMAIL` y `ADMIN_PASSWORD` en `.env` o en el entorno del deploy.
2. Ejecuta migraciones:

```bash
alembic upgrade head
```

3. Arranca la API. Si no existe ningun admin en la DB, la API crea uno con esas variables.
4. Inicia sesion en Streamlit con ese email y password.

Si falta `ADMIN_EMAIL` o `ADMIN_PASSWORD`, la API deja un mensaje claro en logs y no crea
el admin inicial. Cuando ya existe un admin, el bootstrap no se repite.

## Crear usuarios beta

1. Entra como admin.
2. Abre `Cuenta` en el sidebar.
3. En `Usuarios beta`, ingresa email y password inicial.
4. Crea el usuario con rol `beta_user`.

El admin tambien puede listar usuarios y activarlos o desactivarlos desde ese panel.

## Correr local

```bash
alembic upgrade head
uvicorn api.main:app --reload
streamlit run ui/app.py
```

Streamlit guarda el token y el usuario actual en `st.session_state`. Nunca guarda el password.

## No implementado todavia

- Registro publico.
- Pagos.
- Organizaciones o equipos.
- Recuperacion de password.
- OAuth.
- Refresh tokens complejos.
