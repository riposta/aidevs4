from core.agent import run_task


def run():
    run_task("mailbox",
        "Przeszukaj skrzynkę mailową operatora. Znajdź trzy informacje: "
        "1) date - kiedy dział bezpieczeństwa planuje atak na elektrownię (format YYYY-MM-DD), "
        "2) password - hasło do systemu pracowniczego, "
        "3) confirmation_code - kod potwierdzenia z ticketa działu bezpieczeństwa (format SEC- + 32 znaki = 36 znaków). "
        "Wiktor doniósł z adresu proton.me. Zacznij od znalezienia jego maila, potem śledź wątek ticketa. "
        "Skrzynka jest aktywna - nowe wiadomości mogą wpływać. Jeśli nie znalazłeś kodu lub ma złą długość, szukaj ponownie."
    )
