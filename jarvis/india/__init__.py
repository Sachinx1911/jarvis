"""India daily-life features: NAVs, alerts, news, bills, document wallet.

config.py         config/india.yaml (+ config/local.yaml key india_file)
net.py            the small fetch interface every feed uses (fake in tests)
text.py           Indian number, date and amount parsing; Aadhaar/PAN masking
nav.py            AMFI NAVAll.txt parsing, daily cache and change since last fetch
feeds.py          NDMA Sachet CAP RSS alerts, IMD district warnings, Marathi news RSS
bills.py          bill/subscription extraction (deterministic, local), store, recurring, reminders
gmail_import.py   bills from Gmail through the Google connector (bodies parsed locally only)
upi.py            UPI hand-off links, only for payees Sachin confirmed himself; never pays
wallet.py         local document wallet (masked numbers, expiry and tax-deadline reminders)
brief_sections.py morning-brief sections; register_india_sections()
tools.py          chat tools: india_tools(deps)

Privacy: bill details and wallet records are P2 (never to the cloud model). Mail bodies are
parsed here with fixed rules, never by a model. Aadhaar and PAN numbers are masked on input.
"""
