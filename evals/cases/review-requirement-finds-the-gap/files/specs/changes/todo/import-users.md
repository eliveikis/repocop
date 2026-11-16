## Requirement

A team adds its users from a CSV file instead of one by one, so that moving an existing user list in takes minutes, not days.

## Acceptance Criteria

1. An import takes a CSV file of at most 100 users, one per row with a name and an email address, and refuses a larger file, saying how many rows it has.
2. Each imported user gets an account and an email inviting them to sign in.
3. A file of 500 users is imported in one go, so a whole team moves in at once.
4. A row whose email address is already a user's is skipped, and the import says which rows it skipped.
