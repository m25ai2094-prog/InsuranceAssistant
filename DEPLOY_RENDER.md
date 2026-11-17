# Deploy Insurance Assistant in free cloud mode on Render

## Why this deployment mode exists

The original local application runs Rasa Open Source 3.6.21 with a trained DIET
model and TensorFlow. Render's Free web-service instance has 512 MB RAM; the
original Rasa process exceeded that limit during model startup.

The cloud mode keeps the same browser interface and validated Python workflow
but replaces only the runtime intent-inference process with the small
rule-based router in `insurance/light_nlu.py`. It does not load TensorFlow or
start Rasa. The original Rasa model archive, Rasa configuration, and local
launcher remain in the repository for local use and academic reference.

## Deploy

1. Push the project root to the GitHub repository's `main` branch.
2. In Render, open the existing `InsuranceAssistant` Blueprint.
3. Trigger **Manual sync** if the Blueprint does not sync automatically.
4. Confirm the web service uses `requirements-cloud.txt` and `python cloud_run.py`.
5. Wait for the `/api/health` check to return `status: ready`.
6. Open the public `.onrender.com` URL and test the workflows below.

The root `render.yaml` configures the Free plan, Python 3.11, the cloud entry
point, and `/api/health`.

## What stays the same

- Browser UI, navigation, and responsive styling.
- Sample policy catalogue and plan comparison workflow.
- Policy lookup and premium due workflows, including demo policy/mobile check.
- Claim registration, claim tracking, and claim document checklist.
- Validated input steps, simulated OTP inbox, confirmation, and demo support queue.
- SQLite schema, seed data, audit events, and claim workflow logic.

## What changes

- Cloud intent selection is deterministic phrase/keyword routing, not the trained
  Rasa DIET neural model. The UI identifies this as `RULE-BASED` and shows a
  heuristic score, not a model probability or DIET confidence.
- Rasa RulePolicy and the Rasa server are not started in cloud mode.
- The original `python run.py` local launcher continues to use Rasa/DIET.
- Less flexible wording may fall back to the menu; use the service choices or
  concise requests if an intent is not recognized.

## Free-tier limitations and safe use

Render Free services sleep after inactivity and may take around a minute to
wake. Their local filesystem is ephemeral, so newly created SQLite claims,
support requests, and audit records can be lost after restart/redeploy; seeded
fictional demo data is recreated. Sessions are in memory and reset on restart.
OTP delivery and support handoff are simulations. This prototype is not linked
to an insurer and must not receive real policyholder, financial, or medical data.
