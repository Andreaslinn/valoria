"""Dominio puro: entidades, value objects, puertos y excepciones.

Regla crítica: este paquete NO puede importar de infrastructure/, api/, ui/
ni de ninguna librería de I/O (sqlalchemy, redis, httpx, fastapi, streamlit).
Si necesitas datos externos, define un puerto en core/ports/ y deja que
otra capa lo implemente.
"""
