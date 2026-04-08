from core.agent import run_task


def run():
    run_task("sendit",
        "Wypełnij deklarację transportu SPK dla przesyłki z Gdańska do Żarnowca. "
        "Nadawca: 450202122, waga: 2800 kg, zawartość: kasety z paliwem do reaktora. "
        "Budżet: 0 PP (przesyłka musi być darmowa). Brak uwag specjalnych. "
        "Pobierz dokumentację, ustal kategorię, trasę i opłatę, wypełnij deklarację wg wzoru i wyślij."
    )
