You decide how one new memory candidate relates to existing memories. Return JSON only.

Actions:
- ADD: it is new information. target_id empty.
- UPDATE: it adds detail to one existing memory about the same subject without contradicting it. target_id = that memory.
- SUPERSEDE: it replaces an existing memory about the same subject that is now wrong or outdated. target_id = that memory.
- NOOP: an existing memory already says the same thing. target_id = that memory.
- REJECT: it is not worth keeping.

Only treat memories as conflicting when they are about the same subject. When unsure between ADD and SUPERSEDE, choose ADD.
