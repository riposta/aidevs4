---
name: negotiations
description: Pobiera dane CSV i uruchamia serwer API do przeszukiwania przedmiotów/miast dla zadania negotiations
tools: fetch_negotiations_data, start_negotiations_server, check_negotiations_result
---

## Pobieranie danych

Use `fetch_negotiations_data` to download CSV files from the server. Call it first before starting the server.

## Uruchomienie serwera

Use `start_negotiations_server` to start the API server, create a public tunnel, and submit tool URLs to the verification system. This will start a Flask server with search endpoints and expose it via cloudflared tunnel.

## Sprawdzenie wyniku

Use `check_negotiations_result` to check if the external agent has finished and retrieve the flag. Call it after waiting ~60 seconds from submitting tools.
