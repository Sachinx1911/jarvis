"""Google Calendar and Gmail through the direct Google API (PLAN.md section 13, items 4 and 5).

client.py  the GoogleClient interface every tool uses (and its normalized shapes)
fake.py    in-memory implementation for offline tests
api.py     the real implementation (google-api-python-client), imported lazily
auth.py    OAuth "Desktop app" flow; the refresh token lives only in the OS secret store
tools.py   the Jarvis tools: calendar_list, calendar_create_event, gmail_search, gmail_read,
           gmail_draft, gmail_send, parse_time
"""
