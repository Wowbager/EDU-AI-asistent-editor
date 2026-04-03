# EDU AI asistent

> VEŘEJNÁ BETA VERZE

Prostředí pro návrh a provoz kurzů či procvičování - projekt AI asistent pro učitele a žáky: https://edu-ai.eu

EDU AI asistent usnadňuje práci učitelů - pomáhá s hledáním a tvorbou digitálních učebních materiálů, doučováním a podporou hybridní výuky. Žákům AI asistent pomáhá s pochopením látky a s přípravou na zkoušky. Usnadní jim využití existujících digitálníchvzdělávacích nástrojů a zpřístupní doučování dle potřeb jednotlivce.


## Struktura

* Roborec UI - webová aplikace editoru je psaná v Pythonu, servírují ji Gunicorn workeři 
* DB - databáze (aktuálně z legacy důvodů MySQL)
* Celery - správa úloh pro asynchronní spouštění s využitím front
* RabbitMQ - broker pro Celery
* RASA - open source framework pro tvorbu chatbotů
* RASA Actions - akce, které může RASA vykonat při odpovědi uživateli
* Webchat - webchat komunikující s RASA frameworkem

Při zprávě (webchat nebo jiný vstupní kanál) přijde zpráva do RASA. Tam je aktuálně vyhodnocena se 100 % jistotou dle custom policy a spouští se akce běžící na RASA Actions. Tam je ověřen vstup od uživatele a na základě toho mu v odpovědi přijde text, obrázek, možnost odpovědi pomocí tlačítek nebo pauza. Pokud jde o pauzu - např 10s, je vytvořen asynchronní task v celery s eta např 10s. V okamžiku spuštění tohoto tasku se volá externí kanál RASA a uživateli je skrze vstupní kanál (webchat nebo jiný) vrácena odpověď dle scénaře v Roborec UI. Celé řešení je kontejnerizováno, běží dle konfiguračního souboru .env.


## Instalace

Prostředí pro spuštění aplikace v lokálním prostředí je třeba nainstalovat Docker + docker-compose, viz:

https://docs.docker.com/get-docker 

https://docs.docker.com/compose/install/linux/#install-the-plugin-manually

Před prvním spuštěním je třeba nastavit parametry prostředí v konfiguračním souboru .env (přiložen vzor env.example):

```
# hlavní doména projektu - zejména pro účely správného odkazu na uploadované soubory
PROJECT_URL=http://myserver.com:8088
# RASA URL - pro účely celery workerů a jejich provolávání externích akcí 
RASA_URL=https://myserver.com:5005
# povolení registrace - vhodné pro lokální vývoj
ALLOW_REGISTER=1
# debug mód
DEBUG=1
# port na kterém poběží Roborec UI - pro nastavení proxy, nginx apod…
APP_PORT=8088
# mailový server pro odesílání emailů
MAIL_SERVER="smtp-relay.gmail.com"
# port mailového serveru
MAIL_PORT=465
# zapnout TLS (obvykle pro port 587)
MAIL_USE_TLS=0
# zapnout SSL (obvykle pro port 465)
MAIL_USE_SSL=1
# odesílatel emailů
MAIL_FROM=EDU-AI
# email pro odesílání emailů
MAIL_USERNAME=username@gmail.com
# heslo k emailu ^
MAIL_PASSWORD=randompassword
# poskytovatel odesílání emailů: smtp nebo gmail_api
MAIL_PROVIDER=smtp
# adresa odesílatele pro Gmail API
GMAIL_SENDER_EMAIL=username@gmail.com
# refresh token pro Gmail API (pokud je MAIL_PROVIDER=gmail_api)
GMAIL_REFRESH_TOKEN=""
# token endpoint pro Gmail API
GMAIL_TOKEN_URI="https://oauth2.googleapis.com/token"
# Google OAuth přihlášení
GOOGLE_CLIENT_ID=""
GOOGLE_SECRET=""
# callback URL registrovaná v Google Console
GOOGLE_CALLBACK_URL="https://go.edu-ai.eu/auth/google/callback"
# heslo k databázi
MYSQL_ROOT_PASSWORD=randompassword
# secret key
SECRET_KEY="appsecretkey"
# URL QA API (provolani pri nezname zprave uzivatele) 
MFF_URL="https://qa.server.com"
# URL Wiki URL (provolani pro prikaz /w)
MFF_WIKI_URL="https://wiki.server.com"
# URL knihovny pro ucely stahovani sdilenych kurzu
LIBRARY_URL="https://library.server.com"
```

### Gmail API: co potrebujete od admina

Pokud nemate pristup do firemniho Google Workspace/Cloud, potrebujete od admina jen tyto hodnoty:

1. GOOGLE_CLIENT_ID
2. GOOGLE_SECRET
3. GMAIL_SENDER_EMAIL
4. GMAIL_REFRESH_TOKEN (scope: https://www.googleapis.com/auth/gmail.send)

Pak v `.env` nastavte:

```
MAIL_PROVIDER=gmail_api
GOOGLE_CLIENT_ID=...
GOOGLE_SECRET=...
GMAIL_SENDER_EMAIL=...
GMAIL_REFRESH_TOKEN=...
```

Pro jednorazove vygenerovani refresh tokenu (na stroji s prohlizecem) je pripraven skript:

```
python3 flask/scripts/generate_gmail_refresh_token.py --credentials credentials.json
```

Skript vytiskne hodnotu `GMAIL_REFRESH_TOKEN=...`, kterou vlozite do `.env`.

Porty, které je potřeba otevřít ven (při provozu dle přiložené vzorové konfigurace):

* Rasa API: 5005
* HTTP UI editoru: 8088

Interně využívané porty:

* Rasa actions: 5055
* Flower: 5555
* Adminer: 8082


## Spuštění
Spuštění aplikace - ve složce (výchozí edu_light) příkaz `docker-compose up`

Ukončení, ve složce projektu příkaz `docker-compose down`


## Poznámky
Pro produkční prostředí je doporučeno oddělit jednotlivé části do microservices s nastavením odpovídajícího výkonu + škálování jednotlivých podů. 

Vývoj byl realizován pod Linuxem, vzhledem ke kontejnerům nelze garantovat běh na platformách, které plně nepodporují Docker apod - např. MacOS, Windows.

Vývoj byl podpořen Technologickou agenturou České republiky v projektu TL05000236.
