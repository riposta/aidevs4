from core.agent import run_task


def run():
    run_task("firmware",
        "Uruchom plik /opt/firmware/cooler/cooler.bin na maszynie wirtualnej.\n"
        "Krok po kroku:\n"
        "1. Aktywuj skill 'firmware', wykonaj 'help', potem 'reboot'\n"
        "2. Przeczytaj .gitignore żeby wiedzieć czego nie dotykać\n"
        "3. Przeczytaj settings.ini i spróbuj uruchomić binarke\n"
        "4. Znajdź hasło komendą 'find *pass*' i przeczytaj znaleziony plik\n"
        "5. Napraw settings.ini (editline) i uruchom binarke z hasłem\n"
        "6. Gdy uzyskasz kod ECCS-..., zapisz go firmware_store_answer i wyślij przez verify\n"
        "7. Po udanym submit ZAKOŃCZ — napisz końcową wiadomość tekstową",
        max_iterations=50,
    )
