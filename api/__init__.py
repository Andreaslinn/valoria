"""API FastAPI. Expone endpoints versionados en /api/v1/.

Capas internas:
    main.py       — app factory + lifespan events
    deps.py       — inyección de dependencias (session, current_user, services)
    security.py   — hash bcrypt + generación/verificación de JWT
    v1/           — routers versionados
"""
