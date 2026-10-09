# Guida al codice: come è fatto il progetto (versione Ollama)

Questa guida spiega, file per file, cosa fa ogni pezzo del progetto `mcp-android-assistant-Not-CLaude`, partendo dal presupposto che tu non abbia esperienza di programmazione. L'obiettivo è che tu possa leggere il codice sorgente insieme a questa guida e capire cosa succede, riga per riga dove serve.

## Prima di iniziare: qualche parola che userò spesso

**File**: un pezzo di testo scritto in linguaggio Python (o HTML/JavaScript per il frontend) che contiene istruzioni per il computer. Il progetto è diviso in tanti file piccoli invece di uno enorme, così ogni file si occupa di una sola responsabilità.

**Funzione**: un blocco di codice a cui hai dato un nome, che fa un compito specifico e puoi "chiamare" da un'altra parte del programma quando ti serve, invece di riscrivere lo stesso codice più volte. In Python si definisce con `def nome_funzione(...):`.

**Funzione asincrona (`async def`)**: una funzione che può "mettersi in pausa" mentre aspetta qualcosa di lento (tipo una richiesta di rete) senza bloccare tutto il resto del programma. Le riconosci dalla parola `async` prima di `def`, e quando le chiami serve scrivere `await` davanti.

**Classe**: un modello per creare "oggetti" che tengono insieme sia dati sia funzioni che lavorano su quei dati. Se una funzione è una singola azione, una classe è più simile a un piccolo macchinario con uno stato interno.

**Endpoint**: un indirizzo web a cui il tuo browser (o un altro programma) può mandare una richiesta, tipo `/chat` o `/confirm`. Ogni endpoint corrisponde a una funzione che decide cosa rispondere.

**Variabile d'ambiente**: un'impostazione che il programma legge all'avvio dal sistema operativo (non scritta dentro al codice), utile per cambiare comportamento senza modificare i file — es. `LLM_PROVIDER=ollama`.

**JSON**: un formato di testo per scambiare dati strutturati tra programmi, fatto di coppie `chiave: valore`, molto simile a un dizionario. Quasi tutto quello che viaggia tra frontend, backend e i vari server in questo progetto è JSON.

**Dataclass**: una classe scritta in modo compatto, pensata solo per contenere dati (poco o niente comportamento), molto usata in questo progetto per rappresentare "pacchetti di informazioni" come una sessione di chat o un'azione in sospeso.

---

## La struttura generale delle cartelle

```
mcp-android-assistant-Not-CLaude/
├── frontend/          → l'interfaccia grafica (quello che vedi nel browser)
├── backend/           → il server che riceve i messaggi della chat e parla con l'AI
├── mcp_write_server/  → il server MCP che esegue davvero le operazioni di scrittura
├── mock_amapi_server/ → il finto server Google, usato per i test senza dispositivi reali
├── tests/             → i test automatici che verificano che tutto funzioni
├── requirements.txt   → l'elenco delle librerie esterne necessarie
├── .env.example       → il modello delle impostazioni configurabili
├── pytest.ini         → configurazione dello strumento di test
└── README.md          → istruzioni generali del progetto
```

Il modo più semplice per orientarti: **il frontend parla solo con il backend**, **il backend parla con l'AI e con `mcp_write_server`**, e **`mcp_write_server` è l'unico che parla davvero con AMAPI** (nel nostro caso, con `mock_amapi_server`). Nessuno "salta" un livello.

---

## File di configurazione, alla radice del progetto

### `requirements.txt`

Un elenco di librerie esterne (scritte da altre persone) di cui il progetto ha bisogno per funzionare. Quando esegui `pip install -r requirements.txt`, il computer scarica e installa ognuna di queste. Le più importanti:

- `fastapi` — la libreria che permette di costruire sia il backend sia il mock AMAPI come "server web" che rispondono a richieste HTTP.
- `uvicorn` — il programma che fa davvero girare un'app FastAPI, mettendola in ascolto su una porta (es. `:8000`).
- `pydantic` — definisce la "forma" esatta che deve avere un messaggio JSON in entrata o in uscita, e segnala un errore se qualcosa non corrisponde.
- `httpx` — usata per fare vere chiamate HTTP verso altri server (es. dal server di scrittura verso il mock AMAPI).
- `mcp` — la libreria ufficiale del protocollo Model Context Protocol, usata sia per costruire il server di scrittura sia per il client che lo interroga.
- `anthropic` — il client ufficiale per parlare con Claude.
- `ollama` — il client ufficiale per parlare con un modello locale via Ollama.
- `pytest` / `pytest-asyncio` — gli strumenti che eseguono i test automatici, compresi quelli scritti come funzioni asincrone.

### `.env.example`

Un modello di file di configurazione: definisce quali impostazioni esistono (es. `LLM_PROVIDER`, `OLLAMA_MODEL`, `AMAPI_BASE_URL`) senza contenere valori segreti veri. Si copia in un file `.env` reale e si riempiono i valori. Il vantaggio di tenere queste impostazioni fuori dal codice è che puoi cambiare provider, porte o chiavi senza toccare un solo file `.py`.

### `pytest.ini`

Un file minuscolo di configurazione per `pytest` (lo strumento di test). La riga `asyncio_mode = auto` dice a pytest di eseguire automaticamente anche le funzioni di test scritte come `async def test_...`, senza dover aggiungere annotazioni speciali ad ognuna.

### `.gitignore`

Elenca file e cartelle che, se il progetto fosse messo sotto controllo di versione (Git), non andrebbero mai salvati: la cartella dell'ambiente virtuale Python (`venv/`), il file con le impostazioni segrete (`.env`), i file temporanei di Python, e il database dell'audit trail (`audit_log.db`, perché è un dato generato dall'uso, non codice sorgente).

### `README.md`

Il documento di riferimento del progetto: spiega l'architettura, come installarlo, come avviarlo, e quali frasi provare nella chat per testare ogni scenario.

---

## `frontend/` — quello che vedi nel browser

### `frontend/index.html`

È **l'unico file** dell'interfaccia utente: contiene insieme la struttura della pagina (HTML), lo stile grafico (CSS, dentro il tag `<style>`) e la logica interattiva (JavaScript, dentro il tag `<script>`). Non è "diviso" in più file perché per un progetto di queste dimensioni è più semplice tenerlo tutto insieme.

Le parti chiave del JavaScript:

- `postJSON(path, body)` — una funzione che manda una richiesta al backend (es. a `/chat`) con dei dati, e restituisce la risposta. È il "telefono" che la pagina usa per parlare col backend.
- `appendMessage(role, text, toolUsed)` — aggiunge una bolla di messaggio nella chat (utente, assistente o messaggio di sistema), e se è stato usato un tool MCP ci aggiunge sotto il badge `🔧 nome_tool`.
- `showConfirm(pending)` / `hideConfirm()` — mostrano o nascondono la finestra modale di conferma quando arriva un'azione ad alto rischio.
- L'ascoltatore `form.addEventListener("submit", ...)` — si attiva quando premi "Invia": manda il messaggio a `/chat` e mostra la risposta.
- Gli ascoltatori su `approveBtn`/`rejectBtn` — mandano la decisione dell'amministratore a `/confirm`.
- `resetBtn` — chiama `/demo/reset` per azzerare sessione e mock server con un click.
- `checkFakeLlmMode()` — all'apertura della pagina, controlla `/health` e mostra il banner giallo se `FAKE_LLM` è attivo.

Nota importante: il frontend **non sa nulla** di Ollama, Claude, MCP o AMAPI. Sa solo mandare messaggi a due indirizzi (`/chat`, `/confirm`) e mostrare quello che torna indietro. Tutta l'intelligenza sta nel backend.

---

## `backend/` — il cervello che coordina tutto

### `backend/__init__.py`

Un file vuoto (o quasi). La sua unica funzione è dire a Python "questa cartella è un pacchetto", cioè un gruppo di file che si possono importare insieme, così altri file possono scrivere `from backend.app import ...`.

### `backend/app.py`

Il server web principale, costruito con FastAPI. Definisce gli **endpoint**, cioè gli indirizzi a cui il frontend (o chiunque altro) può mandare richieste:

- `GET /` — restituisce la pagina `frontend/index.html`.
- `GET /health` — restituisce lo stato del sistema: se Google è collegato, se `FAKE_LLM` è attivo, e l'elenco dei tool disponibili.
- `POST /chat` — riceve un messaggio dell'utente, lo aggiunge alla cronologia della sessione, e chiama `run_turn()` (da `llm_agent.py`) per far ragionare l'AI.
- `POST /confirm` — riceve la decisione (conferma o rifiuto) su un'azione ad alto rischio in sospeso.
- `POST /demo/reset` — azzera la sessione di chat e resetta il mock AMAPI, per ricominciare una demo da zero.

Alcuni dettagli importanti nel codice:

```python
sessions: dict[str, ChatSession] = {}
```
Questo è un dizionario Python che tiene in memoria tutte le conversazioni in corso, una per ogni utente/scheda del browser, identificate da un `session_id`. Non è un database: se il backend si riavvia, tutte le conversazioni si perdono (l'audit trail delle azioni critiche invece sopravvive, perché è su un file separato, come vedremo dopo).

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await host.start()
    yield
    await host.stop()
```
Questo blocco dice: "quando il backend si avvia, collega il server MCP (`host.start()`); quando si spegne, disconnettilo pulito (`host.stop()`)". È il punto in cui il backend accende la connessione verso `mcp_write_server`.

```python
def _tool_name(tool: dict) -> str:
    return tool.get("name") or tool.get("function", {}).get("name", "?")
```
Una piccola funzione difensiva: siccome i tool hanno una forma diversa a seconda che tu stia usando Claude o Ollama (uno mette `name` in cima, l'altro lo annida sotto `function`), questa funzione sa leggerlo in entrambi i casi, usata solo per mostrare l'elenco tool su `/health`.

Il commento nel codice su `/confirm` spiega un dettaglio non ovvio: quando confermi un'azione, il tool "vero" eseguito è quello originale (es. `issue_command`), non `confirm_action` stesso — per questo il nome viene salvato in `confirmed_tool_name` prima di proseguire, così il badge mostrato in chat è sempre corretto.

### `backend/llm_agent.py`

Il file più importante per capire "come pensa" l'assistente. Gestisce il ciclo di conversazione con l'AI (Claude o Ollama) e decide quando chiamare un tool.

```python
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
FAKE_LLM = os.environ.get("FAKE_LLM", "").strip().lower() in {"1", "true", "yes", "on"}
```
Tre interruttori letti dall'ambiente: quale motore usare (Claude o Ollama), quale modello Ollama specifico, e se attivare la modalità demo finta.

`SYSTEM_PROMPT` è una stringa di testo che viene data all'AI a ogni conversazione, prima ancora del messaggio dell'utente: sono le "istruzioni di comportamento" (rispondi in italiano, usa i tool, non dare per eseguita un'azione che richiede conferma, eccetera).

Due dataclass:
```python
@dataclass
class PendingAction:
    tool_use_id: str
    action_id: str
    summary: str
    risk: str
    tool_name: str

@dataclass
class ChatSession:
    messages: list = field(default_factory=list)
    pending: Optional[PendingAction] = None
```
`ChatSession` rappresenta una conversazione: la lista dei messaggi scambiati finora, e (se presente) un'azione ancora in attesa di conferma. `PendingAction` è il "promemoria" di quell'azione sospesa.

Il cuore del file sono due funzioni gemelle, una per ciascun motore:

`_step()` — usata quando il provider è Claude (o quando `FAKE_LLM` è attivo): manda la cronologia dei messaggi e l'elenco dei tool a `_client.messages.create(...)` (l'API di Anthropic), legge la risposta cercando un blocco di tipo `tool_use`, ed esegue il tool tramite `host.call_tool(...)`.

`_step_ollama()` — usata quando il provider è Ollama: fa la stessa cosa logica ma con la forma diversa delle risposte di Ollama:
```python
response = ollama.chat(model=OLLAMA_MODEL, messages=session.messages, tools=host.list_tools())
message = response["message"]
tool_calls = message.get("tool_calls") or []
```
Qui non c'è bisogno di analizzare "blocchi di contenuto" come per Claude: Ollama restituisce direttamente una lista di `tool_calls`, con gli argomenti già pronti come dizionario Python (non serve nemmeno interpretarli da testo a JSON).

In entrambe le funzioni, se il tool eseguito risponde con `"status": "confirmation_required"`, la funzione salva l'azione in `session.pending` e restituisce all'utente il riassunto, **senza eseguire nulla**. Se invece l'operazione è a basso/medio rischio, il risultato del tool viene rimesso nella cronologia (`session.messages`) e la conversazione continua, perché l'AI deve ancora formulare una risposta finale in linguaggio naturale.

```python
async def run_turn(session: ChatSession, host: McpHost, max_iterations: int = 6) -> dict:
    for _ in range(max_iterations):
        outcome = await _step(session, host)
        ...
        if outcome["done"]:
            return {...}
```
`run_turn()` è il ciclo che chiama `_step()` più volte di fila: serve perché a volte l'AI deve prima leggere un dato (es. `list_devices`) e solo dopo, in un secondo giro, decidere l'azione di scrittura. Il limite di 6 giri evita che il sistema resti bloccato in un loop infinito se l'AI continua a chiamare tool senza mai concludere.

`resolve_pending()` inserisce nella cronologia l'esito reale di un'azione confermata o rifiutata, in un formato diverso a seconda del provider (Ollama usa un messaggio con `role: "tool"`, Claude usa un blocco `tool_result` più articolato).

### `backend/mcp_host.py`

Il "centralino": tiene i collegamenti verso i server MCP e presenta all'AI un unico elenco di tool, indipendentemente da dove vengano davvero.

```python
def _tool_to_anthropic_schema(tool): ...
def _tool_to_ollama_schema(tool): ...
def _tool_schema(tool):
    if LLM_PROVIDER == "ollama":
        return _tool_to_ollama_schema(tool)
    return _tool_to_anthropic_schema(tool)
```
Ogni tool MCP arriva con una descrizione "neutra" (nome, descrizione, schema dei parametri). Queste funzioni la traducono nel formato specifico richiesto da chi la userà (Claude o Ollama vogliono la stessa informazione organizzata diversamente).

La classe `McpHost` ha quattro metodi principali:

- `start()` — lancia `mcp_write_server` come processo separato (usando `stdio_client`, cioè comunicando tramite input/output standard, non rete), ottiene l'elenco dei suoi tool, e se sono configurate le credenziali Google prova a collegarsi anche al server ufficiale di sola lettura.
- `stop()` — chiude ordinatamente tutte le connessioni aperte.
- `list_tools()` — restituisce l'elenco aggregato di tool, quello che verrà passato all'AI.
- `call_tool(name, arguments)` — instrada la richiesta al server giusto: guarda in `self._tool_source` chi possiede quel nome di tool (`"write"` o `"google"`) e la inoltra lì.

Il dizionario `_tool_source` è la parte più importante da capire: è la "rubrica" che ricorda, per ogni singolo tool, quale dei due server sa eseguirlo davvero.

### `backend/fake_llm.py`

La controfigura gratuita di Claude/Ollama, usata solo quando `FAKE_LLM=1`. Non contiene nessuna intelligenza artificiale: cerca parole chiave nell'ultimo messaggio dell'utente ("blocca", "cancella"+"dati", "aggiorna"+"policy", "elenca") e costruisce a mano una finta chiamata a un tool.

```python
class FakeTextBlock: ...
class FakeToolUseBlock: ...
class FakeMessage: ...
```
Queste tre classi esistono solo per **imitare la forma esatta** di una vera risposta di Claude (stessi nomi di campo: `.content`, `.type`, `.text`, `.stop_reason`), così il resto del codice in `llm_agent.py` non deve sapere se la risposta è vera o finta.

Un limite importante da ricordare (ne abbiamo parlato: è il motivo per cui "elenca i dispositivi" in modalità finta risponde con un messaggio generico invece di descrivere i dispositivi): la funzione `_summarize_tool_result()` restituisce sempre frasi fisse tipo `"[demo] Operazione completata."`, senza mai leggere davvero il contenuto del risultato del tool.

### `backend/google_mcp_client.py`

Il client per il server MCP ufficiale di Google (sola lettura). Esiste ed è scritto correttamente, ma nel tuo progetto non si è mai potuto attivare per davvero (serve un'enterprise Google reale).

```python
def is_configured() -> bool:
    creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "")
    enterprise_id = os.environ.get("GOOGLE_ENTERPRISE_ID", "")
    return bool(creds_path and os.path.isfile(creds_path) and enterprise_id)
```
Controlla se esistono davvero le credenziali prima di provare a collegarsi: se mancano, il resto del sistema continua a funzionare tranquillamente solo con il server custom.

```python
async def _session():
    headers = {"Authorization": f"Bearer {_get_token()}"}
    async with streamablehttp_client(GOOGLE_MCP_URL, headers=headers) as (read, write, _get_session_id):
        ...
```
Se le credenziali ci fossero, questo codice otterrebbe un token OAuth2 vero da Google e aprirebbe una connessione HTTP verso l'endpoint ufficiale — la parte "predisposta ma mai validata" di cui abbiamo parlato.

---

## `mcp_write_server/` — il server MCP che esegue le operazioni

### `mcp_write_server/__init__.py`

Come per `backend/__init__.py`: file vuoto che marca la cartella come pacchetto Python.

### `mcp_write_server/server.py`

Il vero e proprio server MCP, quello che dichiara e sa eseguire i tool. Gira come processo separato, comunicando con il backend tramite il protocollo MCP su stdio (non è un server web con una porta come gli altri).

```python
TOOLS: list[types.Tool] = [
    types.Tool(name="list_devices", description=..., inputSchema={...}),
    types.Tool(name="get_device", ...),
    types.Tool(name="list_policies", ...),
    types.Tool(name="update_policy", ...),
    types.Tool(name="delete_policy", ...),
    types.Tool(name="issue_command", ...),
    types.Tool(name="wipe_device", ...),
    types.Tool(name="confirm_action", ...),
]
```
Questo è il "catalogo" ufficiale: ogni voce dice all'AI il nome del tool, cosa fa (in linguaggio naturale, la `description`) e che parametri richiede (`inputSchema`, in formato JSON Schema). Nota che le prime tre (lettura) sono state aggiunte in un secondo momento per completare la demo senza dipendere dal server ufficiale Google.

```python
@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return TOOLS

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> dict:
    ...
    risk = classify(name, arguments)
    if requires_confirmation(risk):
        return _propose(name, arguments)
    return await _execute(name, arguments)
```
Questi due sono i soli due "doveri" che qualunque server MCP deve rispettare: sapere elencare i propri tool, e sapere eseguirli quando richiesto. `handle_call_tool` è dove avviene la decisione più importante del progetto: prima classifica il rischio, e solo se è basso/medio esegue subito, altrimenti "propone" l'azione e si ferma.

```python
def _propose(tool_name, arguments) -> dict:
    risk = classify(tool_name, arguments)
    summary = summarize(tool_name, arguments)
    record = pending_actions.create(tool_name, arguments, risk, summary)
    audit_db.log_proposed(record["action_id"], tool_name, arguments, record["risk"], created_at=_now_iso())
    return {"status": "confirmation_required", ...}
```
Quando un'azione è rischiosa, viene salvata sia in memoria (`pending_actions`, per poterla eseguire velocemente appena arriva la conferma) sia su disco (`audit_db.log_proposed`, per lasciarne traccia permanente).

```python
async def _execute(tool_name, arguments) -> dict:
    try:
        if tool_name == "list_devices":
            result = await amapi.list_devices()
            return {"status": "executed", "result": result}
        ...
    except AmapiError as exc:
        return {"status": "error", "error_code": exc.status_code, "message": exc.message}
```
`_execute()` è dove il tool diventa davvero una richiesta REST verso AMAPI (o il mock), tramite l'oggetto `amapi` (un `AmapiClient`, vedi sotto). Se AMAPI risponde con un errore, viene catturato e restituito come un normale risultato JSON, non come un crash del programma.

### `mcp_write_server/risk.py`

Il "regolamento" che decide quanto è pericolosa ogni operazione.

```python
class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
```
Un `Enum` è un elenco chiuso di valori possibili: qui dice che il rischio può essere solo uno di questi quattro, niente altro.

```python
_ISSUE_COMMAND_RISK = {"LOCK": HIGH, "REBOOT": HIGH, "RESET_PASSWORD": HIGH, "START_LOST_MODE": CRITICAL}
_TOOL_RISK = {"list_devices": LOW, "get_device": LOW, "list_policies": LOW,
              "update_policy": MEDIUM, "delete_policy": CRITICAL, "wipe_device": CRITICAL}
_REQUIRES_CONFIRMATION = {HIGH, CRITICAL}
```
Due tabelle di corrispondenza: una per i comandi diretti al device (alcuni comandi sono più gravi di altri), una per gli altri tool. Solo HIGH e CRITICAL bloccano l'esecuzione in attesa di conferma.

```python
class PendingActionStore:
    def __init__(self, ttl_seconds=15*60):
        self._actions: dict[str, dict] = {}
    def create(...): ...
    def pop(action_id): ...
    def _evict_expired(self): ...
```
Una "sala d'attesa" in memoria per le azioni proposte ma non ancora confermate. Ogni azione ha un tempo massimo di vita (15 minuti): se nessuno la conferma entro quel tempo, decade automaticamente e non potrà più essere eseguita, così non restano richieste pericolose "aperte" all'infinito.

### `mcp_write_server/amapi_client.py`

Il traduttore da "voglio fare questa operazione" a "vera richiesta HTTP verso AMAPI".

```python
def _short_id(raw_id: str) -> str:
    return raw_id.rsplit("/", 1)[-1]
```
La funzione aggiunta per risolvere il bug che hai incontrato: se arriva un ID completo tipo `enterprises/LC00demo123/policies/policy_sales`, ne estrae solo l'ultimo pezzo (`policy_sales`); se arriva già l'ID breve, lo lascia invariato. `rsplit("/", 1)` significa "dividi la stringa dall'ultima `/` in poi, al massimo in due pezzi", e `[-1]` prende l'ultimo pezzo.

```python
@dataclass
class AmapiClient:
    base_url: str
    enterprise_id: str
    ...
    async def patch_policy(self, policy_id, policy_fields):
        path = f"/v1/{self.enterprise_id}/policies/{_short_id(policy_id)}"
        return await self._request("PATCH", path, json_body=policy_fields)
```
Ogni metodo (`patch_policy`, `delete_policy`, `issue_command`, `wipe_device`, `get_device`, `list_devices`, `list_policies`) costruisce l'indirizzo web esatto e il verbo HTTP giusto (GET/POST/PATCH/DELETE), poi delega a `_request()` la vera chiamata di rete con la libreria `httpx`. Il `base_url` (di solito `http://127.0.0.1:8001`, il mock) è l'unica cosa che cambierebbe per parlare con AMAPI vero.

### `mcp_write_server/audit_db.py`

Il registro permanente delle azioni critiche, su un piccolo database SQLite (un unico file sul disco, `audit_log.db`, niente da installare a parte).

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS azioni_log (
    action_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    arguments TEXT NOT NULL,
    risk TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
"""
```
Questa è la "tabella" del database: ogni riga rappresenta un'azione, con le sue colonne. `CREATE TABLE IF NOT EXISTS` significa "creala solo se non esiste già", così il file può essere aperto ripetutamente senza errori.

```python
def log_proposed(action_id, tool_name, arguments, risk, created_at, db_path=DEFAULT_DB_PATH):
    conn = _connect(db_path)
    conn.execute("INSERT INTO azioni_log (...) VALUES (?, ?, ?, ?, 'proposed', ?)", (...))
    conn.commit()
    conn.close()

def log_confirmed(action_id, resolved_at, db_path=DEFAULT_DB_PATH):
    conn = _connect(db_path)
    conn.execute("UPDATE azioni_log SET status = 'confirmed', resolved_at = ? WHERE action_id = ?", (...))
    conn.commit()
    conn.close()
```
Due semplici operazioni: `log_proposed` aggiunge una nuova riga quando un'azione viene proposta, `log_confirmed` aggiorna quella riga quando viene davvero eseguita. Ogni funzione apre e chiude la propria connessione al file, così i dati vengono scritti subito su disco e sopravvivono anche se il programma si ferma un istante dopo.

---

## `mock_amapi_server/` — il finto Google

### `mock_amapi_server/__init__.py`

Stesso ruolo degli altri `__init__.py`: marca la cartella come pacchetto.

### `mock_amapi_server/fixtures.py`

I "dati finti" del progetto: 3 dispositivi e 2 policy scritti a mano, con tutti i campi che avrebbe una vera risposta di Google (stato, connettività, policy assegnata, informazioni hardware).

```python
class Store:
    def __init__(self):
        self.reset()
    def reset(self):
        self.enterprise = copy.deepcopy(_ENTERPRISE_INFO)
        self.devices = {...}
        self.policies = copy.deepcopy(_INITIAL_POLICIES)
        self._command_counter = 0
```
`Store` è il "magazzino" in memoria: tiene lo stato attuale di dispositivi e policy. `reset()` lo riporta ai valori di partenza (usato sia all'avvio sia quando premi "Reimposta demo"). `copy.deepcopy` serve per essere sicuri che modificare un dispositivo non alteri per sbaglio il dato originale di partenza.

### `mock_amapi_server/main.py`

Il server web che finge di essere AMAPI: stesse rotte, stesso formato di risposta, ma legge/scrive nel `Store` in memoria invece che sui server veri di Google.

```python
@app.get("/v1/enterprises/{enterprise_id}/devices")
def list_devices(enterprise_id, pageSize=50, pageToken=""):
    return {"devices": list(store.devices.values())}

@app.post("/v1/enterprises/{enterprise_id}/devices/{device_id}:issueCommand")
def issue_command(enterprise_id, device_id, payload: dict):
    device = _device_or_404(device_id)
    ...
    state = "EXECUTED" if device["connectivity"] == "ONLINE" else "PENDING"
    return {...}
```
Ogni funzione decorata con `@app.get(...)`, `@app.post(...)`, `@app.patch(...)`, `@app.delete(...)` corrisponde esattamente a un indirizzo e un verbo HTTP. Nota la logica di `issue_command`: se il device è online il comando "va a buon fine subito", se è offline resta "in coda" — la stessa distinzione che farebbe il vero AMAPI con un dispositivo davvero irraggiungibile.

```python
@app.middleware("http")
async def enforce_scenario(request, call_next):
    if request.url.path.startswith("/v1/"):
        try:
            scenario.maybe_raise(request.url.path, request.method)
        except HTTPException as exc:
            return JSONResponse(...)
    return await call_next(request)
```
Un "middleware" è codice che si esegue prima di ogni richiesta, per tutte le rotte. Questo controlla se è stato impostato uno scenario di errore attivo (tramite `/_scenario`) e, se sì, lo simula prima ancora di arrivare alla vera logica dell'endpoint.

### `mock_amapi_server/scenarios.py`

L'iniettore di errori configurabile, per testare come si comporta il sistema quando AMAPI risponde male (credenziali scadute, quota superata, servizio non disponibile).

```python
_ERROR_BODIES = {
    401: {"error": {"code": 401, "status": "UNAUTHENTICATED", ...}},
    429: {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", ...}},
    ...
}

class ScenarioController:
    def set(self, status_code, path_prefix="", method=None, times=1): ...
    def maybe_raise(self, request_path, request_method): ...
```
`set()` viene chiamato quando mandi una richiesta a `/_scenario` (es. da curl): registra "per le prossime N richieste che iniziano con questo percorso, rispondi con questo errore". `maybe_raise()` è la funzione che il middleware chiama a ogni richiesta per controllare se deve scattare l'errore finto.

---

## `tests/` — i controlli automatici

Un test è un pezzetto di codice che verifica automaticamente che un'altra parte del codice si comporti come previsto, senza che tu debba cliccare a mano nell'interfaccia ogni volta. Ogni funzione che inizia con `test_` viene eseguita da `pytest`, e se una delle sue `assert` (cioè "verifica che...") risulta falsa, il test fallisce e ti dice esattamente cosa non ha funzionato.

### `tests/test_mock_server.py`

Verifica il comportamento REST del mock da solo (senza backend, senza AI): che `list_devices` restituisca 3 dispositivi, che un device inesistente dia 404, che una policy aggiornata incrementi la versione, che un comando su device offline resti `PENDING`, che gli scenari di errore iniettati funzionino e si esauriscano dopo l'uso.

### `tests/test_write_server.py`

Verifica la logica di `mcp_write_server` da sola: che le operazioni a rischio medio/basso eseguano subito, che quelle ad alto rischio restino "in sospeso" finché non arriva `confirm_action`, che un rifiuto lasci tutto invariato, che una conferma non possa essere "riusata" due volte, e (il test aggiunto per il bug che hai trovato) che passare un nome di risorsa completo o l'ID breve produca lo stesso identico risultato.

### `tests/test_audit_db.py`

Verifica solo `audit_db.py`: scrive una riga, la rilegge con una connessione nuova (simulando "chiudi e riapri"), aggiorna lo stato a "confirmed", e controlla che tutto sia stato salvato correttamente su disco.

### `tests/test_backend_chat.py`

Il test più "grande": accende un vero mock server AMAPI (in un thread separato) e un vero backend FastAPI, poi simula conversazioni complete con Claude — ma sostituendo la vera chiamata all'API Anthropic con risposte scriptate a mano (`script_anthropic`), così il test non costa nulla e non richiede una chiave vera. Verifica l'intero percorso: messaggio → tool eseguito o proposto → conferma → esecuzione reale sul mock, controllando anche gli effetti concreti (es. che la policy sia stata davvero modificata nello `Store`).

---

## Come viaggia una richiesta: un esempio completo

Per mettere insieme tutti i pezzi, ecco cosa succede davvero, file per file, quando scrivi **"blocca pixel-9-pro-sales-01"** nella chat e poi confermi:

1. `frontend/index.html` cattura l'invio del form, chiama `postJSON("/chat", {...})`.
2. `backend/app.py`, endpoint `/chat`: aggiunge il messaggio a `session.messages`, chiama `run_turn(session, host)`.
3. `backend/llm_agent.py`, `run_turn()` chiama `_step()` (o `_step_ollama()` se `LLM_PROVIDER=ollama`).
4. Il modello (Claude o Ollama) riceve messaggio + elenco tool (preso da `backend/mcp_host.py::list_tools()`), decide di chiamare `issue_command` con `device_id="pixel-9-pro-sales-01"`, `command_type="LOCK"`.
5. `llm_agent.py` chiama `host.call_tool("issue_command", {...})`, che in `mcp_host.py` viene instradato (tramite `_tool_source`) al server di scrittura.
6. `mcp_write_server/server.py::handle_call_tool` riceve la richiesta, chiama `classify()` da `risk.py` → risultato `HIGH` → chiama `requires_confirmation()` → vero → chiama `_propose()`.
7. `_propose()` salva l'azione in `pending_actions` (memoria) e in `audit_db.log_proposed()` (disco), risponde `{"status": "confirmation_required", ...}`.
8. La risposta risale: `mcp_host.py` → `llm_agent.py` (che salva `session.pending`) → `app.py` (che la mette in `ChatResponse.pending`) → `frontend/index.html`, che apre la modale di conferma.
9. Premi "Conferma azione": il frontend chiama `postJSON("/confirm", {...})`.
10. `backend/app.py`, endpoint `/confirm`: chiama `host.call_tool("confirm_action", {"action_id": ...})`.
11. `mcp_write_server/server.py`: recupera l'azione da `pending_actions.pop(action_id)`, chiama `_execute("issue_command", {...})`, che chiama `amapi.issue_command(...)` in `amapi_client.py`, che fa una vera richiesta `POST` verso `mock_amapi_server/main.py`.
12. Il mock aggiorna il suo `Store` (se serve) e risponde con l'esito dell'operazione.
13. Torna indietro fino a `server.py`, che chiama `audit_db.log_confirmed()` per registrare l'esito permanentemente.
14. `app.py` chiama di nuovo `run_turn()` per far concludere la conversazione all'AI con una risposta testuale finale, che arriva al frontend e viene mostrata in chat.

Questi 14 passaggi attraversano praticamente ogni file del progetto: se li tieni a mente, hai capito l'architettura intera, non solo i singoli pezzi.
