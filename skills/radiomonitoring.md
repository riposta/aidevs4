---
name: radiomonitoring
description: Zbiera i analizuje sygnały radiowe do identyfikacji miasta Syjon
tools: collect_signals, analyze_signals, submit_report
---

## Zbieranie sygnałów

Use `collect_signals` to start a radio session and collect all available signals. Returns a summary of collected materials (texts, files).

## Analiza

Use `analyze_signals` to process all collected data: parse CSV/JSON/XML, transcribe audio, analyze images, cross-reference cities and trade data. Returns findings about Syjon.

## Raport

Use `submit_report` with parameters: city_name, city_area, warehouses_count, phone_number to send the final report. city_area must be a string with exactly 2 decimal places (e.g. "10.73").
