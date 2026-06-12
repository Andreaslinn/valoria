"""Procesos de fondo: jobs de scraping, geocoding, scheduler.

Estos módulos se ejecutan fuera del ciclo request/response de la API.
Se lanzan desde `workers/scheduler.py` o manualmente con `python -m workers.scraper_job`.
"""
