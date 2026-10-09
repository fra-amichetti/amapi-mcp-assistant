# AMAPI + MCP: dal modello reale al progetto di tesi

Questo documento spiega prima come funziona, end-to-end, un vero sistema che collega un assistente AI ad AMAPI tramite MCP in un'azienda reale, poi come funziona il tuo progetto (`mcp-android-assistant`), come si usa, e quali scorciatoie sono state prese rispetto al modello reale.

---

## Parte 1 — Il modello reale, dall'inizio alla fine

### 1.1 Cos'è AMAPI

AMAPI (Android Management API) è il servizio di Google per gestire da remoto flotte di dispositivi Android aziendali: registrare dispositivi, definire regole (policy), leggerne lo stato, inviare comandi (blocco, reset, cancellazione dati). Non ha nulla a che fare con l'intelligenza artificiale: è un'API REST tradizionale, esiste indipendentemente da qualsiasi assistente conversazionale.

Le risorse principali di AMAPI sono:

- **Enterprise**: l'organizzazione registrata presso Google, contenitore di tutto il resto.
- **Device**: un dispositivo Android arruolato, identificato da un nome tipo `enterprises/LC00.../devices/xxxx`.
- **Policy**: un insieme di regole (restrizioni fotocamera, app obbligatorie, requisiti password...) che uno o più device referenziano tramite il campo `policyName`.
- **Operation/Command**: l'esito di un comando inviato a un device (es. `LOCK`, `REBOOT`, `RESET_PASSWORD`, `START_LOST_MODE`).

### 1.2 Cos'è MCP

MCP (Model Context Protocol) è uno standard, indipendente da AMAPI e da Android, che definisce come un modello linguistico (l'host, es. Claude) può scoprire e usare strumenti esterni in modo strutturato. MCP non sa nulla di dispositivi Android: potrebbe collegare un LLM a un database, a un calendario, a un sistema di ticketing, o come nel nostro caso ad AMAPI.

I ruoli del protocollo:

- **Host**: l'applicazione che ospita il modello (es. Claude Desktop, o un backend come il tuo).
- **Client MCP**: il componente dentro l'host che parla il protocollo con uno o più server.
- **Server MCP**: espone un elenco di *tool* (funzioni con nome, descrizione e schema JSON dei parametri), e sa eseguirli quando richiesto.

Il flusso tecnico è sempre lo stesso, qualunque sia il dominio applicativo:

1. **Handshake iniziale** (`initialize`): client e server si scambiano le rispettive capacità supportate.
2. **Scoperta strumenti** (`tools/list`): il server dichiara quali tool espone e con quali parametri.
3. **Turno di conversazione**: l'utente scrive un messaggio in linguaggio naturale; il modello lo riceve insieme all'elenco dei tool disponibili e decide, ragionando, se e quale tool chiamare.
4. **Invocazione** (`tools/call`): il client MCP invia la richiesta al server, che esegue l'azione vera e la restituisce come risultato strutturato.
5. **Risposta finale**: il modello integra il risultato del tool nella conversazione e risponde all'utente in linguaggio naturale.

MCP, di per sé, non decide mai *quale* tool chiamare: si limita a esporre il menu (punto 2) e a eseguire quello che gli viene richiesto (punto 4). La decisione (punto 3) è compito esclusivo del modello.

Google pubblica un **server MCP ufficiale per Android Management**, ma è di **sola lettura**: espone 9 tool (`get_enterprise`, `list_enterprises`, `get_device`, `list_devices`, `get_policy`, `list_policies`, `get_application`, `get_web_app`, `list_web_apps`). Non esiste un server MCP ufficiale di scrittura pubblicato da Google: chi vuole eseguire azioni di scrittura (bloccare un device, cambiare una policy) via MCP deve costruirselo, esattamente come è stato fatto in questo progetto.

### 1.3 Come si incastrano: l'architettura completa

```
Amministratore IT
      │  scrive in linguaggio naturale
      ▼
Client di chat (host MCP, es. Claude)
      │  messaggio + elenco tool disponibili
      ▼
Modello (Claude) ── ragiona e sceglie ──► tool + parametri
      │  tools/call (via MCP)
      ├──────────────► Server MCP ufficiale Google (sola lettura)
      │                       │  chiamata REST autenticata
      │                       ▼
      │                    AMAPI (Google) ──► Enterprise / Device / Policy reali
      │
      └──────────────► Server MCP di scrittura (custom, costruito dall'azienda)
                              │  valuta il rischio dell'azione
                              │  se rischiosa: richiede conferma umana esplicita
                              │  chiamata REST autenticata (service account)
                              ▼
                           AMAPI (Google)
                              │  push (Firebase Cloud Messaging)
                              ▼
                    Dispositivo Android reale (Android Device Policy)
                              │  esegue il comando
                              ▼
                    Google Cloud Pub/Sub ──► notifica asincrona dell'esito
```

Componenti che servono per far funzionare tutto questo nella realtà, prima ancora di scrivere una riga di codice applicativo:

1. **Registrazione enterprise**: l'azienda si registra come EMM presso Google (flusso di *signup*), ottenendo un'enterprise (`enterprises/LC...`) legata a Managed Google Play.
2. **Credenziali**: viene creato un *service account* su Google Cloud con una chiave JSON; tutte le chiamate ad AMAPI si autenticano con OAuth2 usando questa chiave e lo scope `androidmanagement`.
3. **Policy**: l'amministratore definisce una o più policy tramite `policies.patch`, prima ancora di avere dispositivi.
4. **Arruolamento (enrollment)**: per ogni dispositivo si genera un *enrollment token* (QR code o link); sul telefono si installa/attiva l'app "Android Device Policy" (o un DPC custom), che legge il token e registra il device presso Google. Da quel momento il device esiste come risorsa reale in AMAPI.
5. **Notifiche asincrone**: AMAPI usa Google Cloud Pub/Sub per notificare eventi (cambio stato, esito comandi, non conformità): il sistema non è puramente richiesta/risposta sincrona, molte cose arrivano in modo asincrono anche minuti dopo.
6. **Recapito dei comandi**: quando un comando viene inviato, Google lo inoltra al dispositivo reale tramite push (Firebase Cloud Messaging); se il device è offline, resta in coda (`PENDING`) finché non si riconnette.

### 1.4 Esempio reale in un'azienda, passo per passo

Immaginiamo un'azienda con 400 dispositivi Android per il personale di magazzino e vendita, che ha integrato un assistente conversazionale (via MCP) collegato sia al server ufficiale Google di sola lettura sia a un server interno di scrittura costruito dal proprio team IT.

**Scenario: un tablet viene smarrito.**

1. L'IT manager scrive nella chat aziendale: *"il tablet del magazzino B è stato smarrito, trovalo e attiva la modalità smarrito"*.
2. Il modello riceve il messaggio insieme all'elenco dei tool disponibili (lettura dal server Google, scrittura dal server interno).
3. Il modello chiama prima `list_devices` (o `get_device`) sul server di sola lettura, per identificare l'ID esatto del dispositivo del magazzino B: è una vera richiesta REST contro AMAPI, che restituisce dati reali.
4. Trovato il device, il modello propone di chiamare `issue_command` con `command_type=START_LOST_MODE` sul server interno di scrittura.
5. Essendo un'azione ad alto rischio, il server interno non la esegue subito: risponde con uno stato "richiede conferma", e l'IT manager deve approvarla esplicitamente in chat.
6. Dopo la conferma, il server interno effettua la vera chiamata `devices.issueCommand` su AMAPI, autenticandosi con le credenziali del service account aziendale.
7. Google inoltra il comando al dispositivo reale tramite push; se il tablet è online lo esegue nel giro di secondi, altrimenti resta in coda finché non si riconnette a internet.
8. Un evento Pub/Sub notifica in modo asincrono l'esito reale del comando (eseguito, fallito, ancora in coda), e il sistema aziendale può aggiornare lo stato o avvisare di nuovo l'IT manager.

Questo è il ciclo completo: linguaggio naturale → ragionamento del modello → protocollo MCP → chiamata REST autenticata → infrastruttura Google → dispositivo fisico → notifica asincrona di ritorno.

---

## Parte 2 — Il tuo progetto (`mcp-android-assistant`)

### 2.1 Architettura e componenti

```
Utente (browser)
      │
      ▼
frontend/index.html ──── chat + modale di conferma
      │  HTTP (/chat, /confirm)
      ▼
backend/app.py (FastAPI) ── gestisce le sessioni di chat
      │
      ▼
backend/llm_agent.py ── loop di tool-calling
      │  se FAKE_LLM=1: backend/fake_llm.py (match di parole chiave)
      │  altrimenti: vera API Anthropic (Claude)
      ▼
backend/mcp_host.py ── client MCP, aggrega i server disponibili
      │  protocollo MCP (stdio)
      ▼
mcp_write_server/server.py ── server MCP di scrittura (solo tool: update_policy,
      │                        delete_policy, issue_command, wipe_device, confirm_action)
      │  mcp_write_server/risk.py: classifica il rischio, richiede conferma se necessario
      ▼
mcp_write_server/amapi_client.py ── client REST (httpx), stesso codice sia contro
      │                              il mock sia (in teoria) contro AMAPI vero
      ▼
mock_amapi_server/main.py ── implementa le stesse rotte REST di AMAPI reale,
                              leggendo/scrivendo su dati finti in memoria
                              (mock_amapi_server/fixtures.py)
```

Ogni componente corrisponde a un pezzo del modello reale descritto nella Parte 1, tranne l'ultimo: al posto di Google AMAPI reale c'è un server che imita solo il comportamento REST, con dati inventati.

### 2.2 Come si usa

Ci sono tre modalità possibili, con costo crescente:

| Modalità | LLM | AMAPI | Costo | A cosa serve |
|---|---|---|---|---|
| Demo | `fake_llm.py` (parole chiave) | mock | zero | testare interfaccia, flusso di conferma, chiamate REST simulate |
| Validazione | Claude reale | mock | pochi centesimi | verificare che l'AI capisca davvero il linguaggio naturale e scelga i tool giusti |
| Reale (non testata) | Claude reale | AMAPI vero | dipende da Google Cloud | uso in produzione, richiede enterprise e credenziali reali |

Per avviare il progetto in modalità demo o validazione:

1. Avviare il mock AMAPI: `uvicorn mock_amapi_server.main:app --port 8001`
2. Avviare il backend, puntandolo al mock, con `AMAPI_BASE_URL=http://127.0.0.1:8001`, ed eventualmente `FAKE_LLM=1` (demo) oppure `ANTHROPIC_API_KEY=...` (validazione): `uvicorn backend.app:app --port 8000`
3. Aprire `http://127.0.0.1:8000` per la chat, oppure `http://127.0.0.1:8001/docs` (Swagger) per chiamare direttamente il mock come se fossi tu stesso AMAPI.

### 2.3 Esempio pratico end-to-end nel progetto

Scenario dimostrativo: cancellazione dati di un dispositivo compromesso (`wipe_device`, rischio CRITICAL).

1. Su Swagger (`:8001/docs`) si fa `GET /v1/enterprises/LC00demo123/devices` e si verifica che `pixel-8-support-02` esiste ancora.
2. Nella chat (`:8000`) si scrive: *"cancella tutti i dati di pixel-8-support-02"*.
3. Il modello (reale o finto) sceglie il tool `wipe_device` con `device_id=pixel-8-support-02` e lo invia via MCP al server di scrittura.
4. `risk.py` classifica `wipe_device` come CRITICAL: l'esecuzione si ferma, il backend risponde con `pending` e il frontend mostra la modale di conferma con il livello di rischio.
5. L'utente clicca "Conferma azione": il frontend chiama `/confirm`, che invoca il tool `confirm_action` sul server MCP.
6. Solo a questo punto il server di scrittura esegue davvero la richiesta REST (`DELETE /devices/pixel-8-support-02`) contro il mock.
7. Ripetendo la `GET /devices` su Swagger, il dispositivo non compare più: prova diretta che l'azione partita dalla chat ha modificato realmente lo stato del sistema a valle, non solo "raccontato" di averlo fatto.

### 2.4 Differenze e scorciatoie rispetto al modello reale

| Aspetto | Modello reale | Nel tuo progetto | Perché è una scorciatoia accettabile |
|---|---|---|---|
| Enterprise e credenziali | Service account OAuth2, enterprise Google vera | Nessuna autenticazione, il mock accetta tutto | La tesi verte sul pattern MCP e sul flusso di conferma, non sull'autenticazione Google |
| Dispositivi | Migliaia di device fisici reali, con Android Device Policy installato | 3 device finti, dati statici in memoria (`fixtures.py`) | Bastano per dimostrare ogni tipo di operazione (lettura, comando, wipe) senza hardware |
| Notifiche di stato | Asincrone, via Google Cloud Pub/Sub | Sincrone, risposta REST immediata | Semplifica la dimostrazione; si perde la parte di asincronia reale |
| Esecuzione comandi | Recapitati al device via push FCM, tempi di rete reali e variabili | Simulata: `EXECUTED` se il device è "ONLINE", `PENDING` se "OFFLINE", nessuna comunicazione fisica | Riproduce la logica di business, non la latenza di rete reale |
| Lettura device/policy | Server MCP ufficiale Google, dati veri | Non collegato di default (flag `host.google_enabled`); nel demo le letture passano comunque dal mock | Il progetto si concentra sul server di scrittura custom, la lettura ufficiale è predisposta ma opzionale |
| Scelta del tool da chiamare | Claude reale, ragiona sul linguaggio naturale | In modalità demo: match di parole chiave (`fake_llm.py`); con chiave reale: Claude vero, identico al caso reale | Il match a parole chiave serve solo per test gratuiti dell'interfaccia, non sostituisce la validazione con AI vera |
| Persistenza dati | Database reale, stato permanente nel tempo | In memoria, si azzera a ogni riavvio del mock | Non serve persistenza per una demo di validazione |
| Errori e limiti di quota | Errori reali di Google (429, 503...) imprevedibili | Endpoint `/_scenario` per iniettare a comando errori specifici | Permette di testare la resilienza del codice in modo controllato e ripetibile |
| Scala | Multi-tenant, migliaia di enterprise possibili | Una sola enterprise fissa (`LC00demo123`), fissata da variabile d'ambiente | Sufficiente per uno scenario dimostrativo singolo |

In sintesi: **il protocollo (MCP), la logica applicativa (backend, risk.py, il pattern di conferma) e il modo in cui i pezzi comunicano tra loro sono identici al modello reale**. Le scorciatoie riguardano esclusivamente ciò che sta "oltre" il client REST — cioè l'infrastruttura Google vera e i dispositivi fisici — sostituita da un mock che ne replica fedelmente il comportamento osservabile (stesse rotte, stessi formati JSON, stessa logica di stato) senza esserne l'implementazione reale.
