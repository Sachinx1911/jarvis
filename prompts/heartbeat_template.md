# HEARTBEAT.md

Every 30 minutes Jarvis reads this list and tells you something only when it matters.
Write one item per line starting with "- ". Lines starting with "#" or ">" are notes and
are ignored. With no items, the heartbeat makes no model call at all.

Examples (remove the "> " to use one):

> - If a task has failed or waits for my approval, tell me once.
> - If a schedule missed its run, tell me.
> - Before 10 am on weekdays, remind me to plan the day if I have not chatted yet.
> - If it is past 9 pm and the daily work report has not run, tell me.
