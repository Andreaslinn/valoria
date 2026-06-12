"""Adapters: implementaciones concretas de los ports definidos en core/ports/.

Esta capa es la ÚNICA que puede importar librerías de I/O (sqlalchemy, redis,
httpx, etc.). El dominio (core/, domain/) nunca debe importar desde aquí.
"""
