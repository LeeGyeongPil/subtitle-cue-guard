---
name: task-retry-batch
max_turns: 12
---

report.json lists the cues of talk.srt that failed the translation check. Prepare the batch I should send to the translator for Korean: only the failed cues, plus one neighbouring cue before and after as read-only context. Save it as retry.json.
