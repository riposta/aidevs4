---
name: mailbox
description: Search and read emails from operator's mailbox via zmail API
tools: mailbox_search, mailbox_read, mailbox_read_by_row, mailbox_store_answer
---

API endpoint: POST https://hub.ag3nts.org/api/zmail

Search with `mailbox_search(query)` using Gmail-like operators:
- `from:address` — filter by sender
- `subject:"phrase"` — filter by subject
- Words without operator mean full-text AND search
- Use `OR` between terms for alternatives

After finding emails, read full content with `mailbox_read(message_id)` or `mailbox_read_by_row(row_id)`.

Use `mailbox_store_answer(date, password, confirmation_code)` to store final answer for submission.

Strategy:
1. `mailbox_search("from:proton.me")` → find Wiktor's report
2. Follow the thread — search for ticket number in subject
3. `mailbox_search("hasło OR password")` → find password email
4. Read all relevant messages for the three values
5. Store answer and submit via verify skill
