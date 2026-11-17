# Agentic Conversational AI Solutions for Insurance Advisory and Automated Claims Assistance

Kapildev Sukhsagar Yadav · M25AI2158  
M.Tech (Artificial Intelligence), Indian Institute of Technology Jodhpur

This is a runnable, local insurance assistant with **Rasa Open Source 3.6.21**,
a trained **DIET intent model**, Rasa RulePolicy, a Python custom action service,
SQLite, and a browser interface. All demo records, premiums, and claims are
fictional. The in-browser OTP inbox and the claim acknowledgement outbox
simulate delivery. The app records claim intimation, document readiness,
and status. Settlement and document authentication are outside the prototype.

## Start the application

Use **64-bit CPython 3.10** on an x86-64 machine. It can be installed alongside
a newer Python. The first dependency installation needs internet access and
space for TensorFlow. The trained model is included. Running the app needs no
API key, GPU, external model download, or insurer account.

### Windows PowerShell

Extract the project ZIP and open the `Insurance_Assistant` folder. If you
already set up the working `%USERPROFILE%\ia-venv` environment for this
project, double-click **Start_Insurance_Assistant.bat**. It also finds a
project-local `.venv` and opens the browser once the launcher is ready.

For a fresh Windows environment, open PowerShell in the project folder and
use a short virtual environment path:

```powershell
py -3.10 -m venv "$env:USERPROFILE\ia-venv"
& "$env:USERPROFILE\ia-venv\Scripts\python.exe" -m pip install -r requirements.txt
& "$env:USERPROFILE\ia-venv\Scripts\python.exe" run.py
```

If `py -3.10` is unavailable, install 64-bit Python 3.10 first.
The verified environment was Linux x86-64. On Windows, WSL2 with an
x86-64 Ubuntu distribution provides the corresponding Linux path.

### Linux or WSL2

```bash
python3.10 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock-linux.txt
.venv/bin/python run.py
```

If Python 3.10 is unavailable and `uv` is installed, run
`uv python install 3.10` and `uv venv --python 3.10 --seed .venv`.
Then use the last two Linux commands above.

When the terminal prints **Insurance Assistant ready**, open
[http://127.0.0.1:8000](http://127.0.0.1:8000). Keep the terminal running.
Press **Ctrl+C** to stop. If ports are busy, use
`python run.py --port 8010 --rasa-port 5010` with the same venv interpreter
and open port 8010. Startup diagnostics are written to `instance/rasa.log`.
If the browser opens and replies fail, inspect the log for model loading
errors. Appendix C of the final report covers the previously observed Rasa
3.6.21 Windows archive extraction error `WinError 123`.

## Navigate the service desk

**Overview** groups service shortcuts for claims, cover, and renewals.
**Claim centre** collects claim registration, tracking, and document preparation.
**Assistant** accepts typed requests and shows the current step. Sample values
appear under **Demo records** when relevant. Selecting a value submits it.

When you navigate away from an unfinished request, **Resume request** returns
to the same step. Reloading restores the pending step and a review with valid
verification. Selecting a different service while a draft is open asks whether
to keep the current request or discard it. **New session** clears the draft
and creates a new browser session.

## Live demonstration

| Task | Example |
| --- | --- |
| Compare plans | Type “Could you recommend a health plan for me?” Enter age `30`, minimum cover `5` lakh, and budget `1200` per month. The sample match is Health Essentials. |
| View a policy | In **Overview**, choose **View my policy**. Select the Health policy, then click the policy number and demo mobile as prompted. Choose **Use code** in **Demo inbox**. |
| Check a premium | Choose **Check premium due**, then verify the same health policy and mobile. |
| View claim documents | Type “What supporting paperwork should I collect for a motor claim?” and choose **Vehicle theft**. |
| Register a claim | Under **Claim centre**, choose **Register a claim** and verify the health policy. Choose **Hospitalisation**, use the sample date, enter a fictional description, then enter **Demo City Hospital**. Tick **Claim form** and **Itemised bills and receipts** and choose **Review claim**. Check the 2-of-4 result and choose **Confirm claim**. |
| Track that claim | The receipt shows **Awaiting documents** and a new reference. Select **Track this claim**, verify the same policy, then use the last claim reference. From a new session use **Track a claim** and type the receipt reference. The seed reference `CLM-0000001001` gives an **Under review** example. |
| Queue support | Choose **Get support**, then choose **Claim**, **Policy**, or **Other**. |

The Demo records selector also contains motor, life, and travel samples. You
can type the values in the composer. The document step also accepts `1, 3`,
`All ready`, and `None ready`. Leaving all boxes unchecked marks all documents
as pending. **Cancel** clears the active workflow. SQLite retains confirmed
claims, acknowledgements, queued support tickets, and audit events across restarts.

## Retrain and verify

Run the following from the project folder with the venv Python. On Windows,
replace `python` in these examples with `.\.venv\Scripts\python.exe` unless the
venv is active. On Linux, use `.venv/bin/python`.

```text
python -m tests.evaluate_nlu --output evidence/nlu_recheck.json
python -m tests.check_workflows --output evidence/workflow_recheck.json
python run.py --train
```

Evaluation loads the actual archive and reads `rasa/heldout.yml`. Workflow
checks start both local services on separate ports and use an isolated test
database. Retraining replaces `models/insurance-rasa.tar.gz` from the YAML in
`rasa/data/`. A retrain can change the binary hash and scores. The supplied
model digest is in `models/SHA256SUMS`. Use the first two commands before
retraining to reproduce the included model's checks.

## Project files

| Path | Purpose |
| --- | --- |
| `run.py` | Starts both loopback services or retrains the Rasa archive. |
| `rasa/config.yml`, `rasa/domain.yml`, `rasa/data/` | NLU configuration, intents, training examples, rules, and action declarations. |
| `rasa/endpoints.yml`, `rasa/credentials.yml` | Loopback action endpoint, per-turn tracker, and REST channel. |
| `rasa/heldout.yml` | Authored test data kept outside the training directory. |
| `models/insurance-rasa.tar.gz` | Trained DIET, regex extractor, fallback component, and RulePolicy archive. |
| `insurance/web.py`, `insurance/tracker.py` | Flask gateway, Rasa action callback, and turn-scoped tracker. |
| `insurance/workflow.py`, `insurance/catalog.py` | State transitions, validation, OTP, sample plans and checklists. |
| `insurance/repository.py` | Schema, demo seed data, policy-scoped lookups, atomic claims and audit. |
| `insurance/static/` | Responsive local HTML, CSS, and JavaScript. |
| `tests/`, `evidence/` | Runnable checks, raw NLU predictions, and measured scenario outcomes. |
| `evidence/ui_verification.md`, `figures/` | Browser checks and screenshots of the redesigned interface. |

## Implementation scope

The proposal describes Rasa Pro CALM. This implementation uses Rasa Open
Source and RulePolicy for licence-free execution, with validated workflow
steps in the custom action service. The NLU model chooses a supported route.
The Python workflow enforces authorization, validates collected fields, and
requires explicit confirmation before writing a claim. The app listens on
loopback for a local demonstration. Real insurer APIs, independent OTP
delivery, document OCR, IVR, and live CRM handoff would need separate
integration and validation.

## Free cloud demonstration mode

The original local launcher (`python run.py`) still uses the supplied Rasa
Open Source 3.6.21 DIET model and RulePolicy. For a small free cloud instance,
use `python cloud_run.py` instead. This cloud entry point uses only Flask and a
small deterministic, rule-based intent router (`insurance/light_nlu.py`) to
select the same existing Python workflows. It does **not** load TensorFlow or
start the Rasa server, which avoids the 512 MB Render Free memory failure.

The browser interface, sample policy catalogue, advisory flow, policy lookup,
premium lookup, claim registration, claim tracking, document checklist,
simulated OTP inbox, support queue, validation, and confirmation workflow are
shared with the local application. The cloud UI labels its intent trace as
`RULE-BASED`; the original local UI/runtime remains Rasa/DIET. The lightweight
router is heuristic and is not equivalent to the trained DIET model, so its
intent coverage and confidence display should not be represented as DIET model
metrics.

Deploy the cloud mode with `render.yaml`; it installs only
`requirements-cloud.txt` and starts `cloud_run.py`. Render Free uses an
ephemeral filesystem, so newly created SQLite demo records may be lost after a
restart or redeploy. The seeded fictional demo records are recreated at startup.
Do not enter real policyholder, financial, or medical information. OTP and
support handoff remain simulated and are not connected to a real insurer.
