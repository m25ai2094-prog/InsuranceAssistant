# Browser verification of the redesigned interface

The browser checks used Chromium, synthetic policies, the bundled Python
workflow and SQLite repository, and a local fixture for opening intents.
The separate Rasa evaluation files record the earlier run of the trained model
and the two-service application. The redesign checks cover the browser
interaction and workflow state with fixture intents.

| Journey | Observed result |
| --- | --- |
| Browse services | Overview showed claims, cover, and renewal tasks. Claim centre offered registration, tracking, and the document checklist. |
| Compare a sample plan | Health, age 30, ₹5 lakh minimum cover, and ₹1,200 monthly budget returned Health Essentials at ₹750 per month. |
| Verify a sample policy | The health policy and its matching demo mobile produced a challenge. The on-screen code advanced the flow to claim type. |
| Mark document readiness | Claim form and itemised bills remained selected after an invalid typed selection. The review counted two of four ready. |
| Resume a request | Trying to open tracking while the draft was active offered to keep the existing request. Overview could reopen the draft. |
| Restore the claim review | An unrelated message retained the review and its controls. Reloading reopened the review with the active verification. |
| Confirm and track | A confirmed claim produced reference CLM-F59E496E91 and an acknowledgement. Tracking the same reference after a second policy verification showed Awaiting documents and two outstanding items. |

The figures show the Overview, Claim centre, plan result, checklist, review,
receipt and verified tracking result. They contain fictional records only.
