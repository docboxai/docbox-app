"""Benchmarks: run the installed OCR models over the user's own documents and compare
them on speed, memory, confidence and, when reference text is given, accuracy (CER/WER).

dataset.py  what to read, and the reference text for it
metrics.py  normalising text and scoring it against a reference
worker.py   one model reading every page, in its own process
runner.py   a whole run: models one after another, results into the store
store.py    saved runs under <data>/benchmarks/
report.py   leaderboards, Markdown / JSON / CSV
"""
