# Apple reviewer lane

Isolated customer and expert path for App Store review. The server decides who is on it by binding **existing user ids**. A public signup cannot join by typing an email address, and a client cannot join by sending a flag.

This change does not create production users, change existing accounts, call the admin API, read credential files, set passwords, deploy, or submit the app.

## What was verified

Checked in this repository:

- Public signup stores `is_test` from the email heuristic, including the whole `dalla3.test` domain. There is no email-ownership check on `POST /api/auth/register` or on Apple/Google signup. The address in the body is whatever the client sends.
- An exact email allowlist (`APPLE_REVIEWER_EMAILS`) would therefore grant `reviewerLane` to whoever registers that mailbox first. The expert account does not exist yet, so that mailbox is still claimable. That mechanism is **not** used.
- Catalog, quote, and booking used to treat `is_test` as permission to see and book hidden experts.
- `PUT /api/me/expert` used to copy client `nafath_verified` and force `status = approved` with no server check of phone, IBAN, bank name, or freelance document.

`GET /health` still reports the configured payment provider. It is `mock` unless `PAYMENT_PROVIDER` is changed.

## Design

`APPLE_REVIEWER_USER_IDS` is a comma-separated list of **existing** user ids. Default is empty, which designates nobody. The parser keeps only tokens shaped like the server generator: `u_` plus 10 hex characters (example `u_0123abcd90`). These designate nobody:

- an email address, including `apple-review-customer@dalla3.test`
- `APPLE_REVIEWER_EMAILS` (not a setting; a leftover value is ignored)
- `dalla3.test`, `@dalla3.test`, `*@dalla3.test`
- `*`, `u_*`, `u_`, a short id, an expert id (`e_…`)

Registration and social login always create a new id with `is_apple_reviewer = false`. Sync then sets the column only when that id is already on the list. A stranger who registers an intended mailbox gets their own id, so they stay off the lane even if the email was written into the environment. The lane turns on only after an operator copies the id of the account they already created.

The signed-in user's column is updated to match the list. Other rows are not scanned. Removing an id revokes the lane on that user's next authenticated request.

Visibility:

| Viewer | Public approved experts | Hidden `is_test` experts | Reviewer experts |
| --- | --- | --- | --- |
| Anonymous or normal user | yes | no | no |
| Untrusted test-domain user (`is_test`, not designated) | yes | no | no |
| Designated reviewer | no | no | yes |

Booking uses the same rule. A reviewer customer cannot quote or book a real or hidden expert. A normal or untrusted user cannot quote or book a reviewer expert. The permitted pair is a designated customer and a designated expert. They can book, accept, and cancel.

Reviewer bookings set `bookings.reviewer_lane` and always use the mock payment provider, including refunds, even when `PAYMENT_PROVIDER=moyasar`. The hold runs only after the slot row is reserved, so the request that loses the unique index does not create a payment.

### Duplicate active slots

An active booking occupies `(expert_id, date, time)` while its status is `pending_accept`, `confirmed`, `on_the_way`, `arrived`, or `in_progress`.

- The request checks for that row and returns HTTP 409 if it is already there.
- `uq_booking_active_slot` is a partial unique index on the same columns for those statuses. Two transactions that both pass the read still cannot both commit. The loser gets HTTP 409, and no payment hold is started for that loser.
- Cancelling, rejecting, or completing a booking takes it out of the index, so the clock time can be booked again.
- The index does not cover two different times, two different experts, or a customer booking two different experts at the same time.
- SQLite allows one writer at a time; the waiter then fails on the unique index instead of inserting a second active row. Postgres uses the unique index as the lock. That is the concurrency boundary: the application `SELECT` alone is not a lock.

### Expert onboarding

Production (not designated), enforced on `PUT /api/me/expert`:

- Phone on the user has at least 9 digits.
- IBAN matches a 15–34 character IBAN shape after spaces are removed.
- Bank name and freelance-document number are non-empty.
- `nafath_verified` from the client is discarded. The badge stays false. This API has no Nafath check.
- All four checks pass → `approved` and visible to the public. Otherwise `pending` and not listed.

That is the production path a completed application still follows. The reviewer shortcut does not apply to it.

Designated reviewer expert, on a save **after** the user id is bound:

- Phone, IBAN, bank name, freelance number, and Nafath are not required.
- If the client sends IBAN, bank name, freelance number, or `nafath_verified`, those values are not stored. The profile keeps empty payout/legal fields and `nafathVerified: false`.
- The profile is approved only inside the lane and is marked `is_test` so it stays out of the public catalog.
- The server does not invent a phone, national id, IBAN, or Nafath subject.

A save before the id is bound follows the production rules. Save again after binding so the lane rules apply.

`is_test` still hides QA accounts. It does not grant access to hidden experts.

## Client contract

Boolean field **`reviewerLane`**. Read it from the server. Do not infer it from the email domain or from a value the client sent.

Present on:

- `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/apple`, `POST /api/auth/google` → `user.reviewerLane`
- `GET /api/auth/me` → `reviewerLane`
- `GET /api/me/profile` → `reviewerLane`
- Expert objects → `reviewerLane`
- Booking objects → `reviewerLane` (true for bookings created inside the lane; this stays true for that row even if the id list changes later)

Example, after that user id has been bound:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": {
    "id": "u_…",
    "email": "apple-review-customer@dalla3.test",
    "name": "عميلة المراجعة",
    "phone": "",
    "role": "customer",
    "city": "الرياض",
    "expertId": null,
    "reviewerLane": true
  }
}
```

`reviewerLane` stays `false` until the operator binds `user.id`. Sending `reviewerLane` on input does nothing.

`POST /api/me/expert` for the signed-in expert also returns `status` (`approved` or `pending`).

## Operator setup

Create the accounts first. Bind ids only after you have checked that the row is the account you control. Leave `APPLE_REVIEWER_USER_IDS` empty until then.

1. `apple-review-customer@dalla3.test` already exists. Do not register it again and do not edit that row from this change. If a login works with the password you already have, that row is the customer to bind.
2. Create the expert account yourself, with the password stored in your vault. This repository does not create it and does not contain a password. If signup says the email is already registered, that row is not yours: do not designate it, and create the expert on a mailbox you just registered.
3. Read the ids of those two existing rows (your SQL or the admin list you already operate). Confirm `id`, `email`, and `role` on the same row:

```sql
SELECT id, email, role FROM users
WHERE email IN ('apple-review-customer@dalla3.test', '<expert email you created>');
```

4. Restart the API with those exact ids and nothing else:

```bash
APPLE_REVIEWER_USER_IDS=u_0123abcd90,u_abcdef1234
```

5. The next authentication for those ids returns `reviewerLane: true`. Any signup of the same mailbox before this step stays `reviewerLane: false`.
6. Open the expert profile in the app and save it with no phone, IBAN, bank, freelance number, or Nafath. If the profile was saved before step 4, save it again so the lane rules replace any payout or badge fields.
7. Do not put a real customer's or a real expert's id in the list. Payments for a bound pair stay simulated.

`APPLE_REVIEWER_EMAILS` does not grant the lane. Do not use it.

The iOS app should show the reviewer flow only when `reviewerLane` is true, including skipping phone, legal, bank, and Nafath screens. Those skips are not safe as a client-only email check.

## Schema migration

On startup the API runs `upgrade_reviewer_schema` (`server/schema_updates.py`). It adds missing columns and the slot index. It does not grant the lane to existing rows:

```sql
ALTER TABLE users ADD COLUMN is_apple_reviewer BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE bookings ADD COLUMN reviewer_lane BOOLEAN NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_active_slot
  ON bookings (expert_id, date, time)
  WHERE status IN ('pending_accept', 'confirmed', 'on_the_way', 'arrived', 'in_progress');
```

`DEFAULT 0` is accepted for boolean columns on Postgres and SQLite. New databases get the same objects from the SQLAlchemy models. Existing databases get them from startup, and each statement is skipped when the object is already there.

Equivalent Postgres, if you apply DDL yourself before boot:

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_apple_reviewer BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reviewer_lane BOOLEAN NOT NULL DEFAULT FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_active_slot
  ON bookings (expert_id, date, time)
  WHERE status IN ('pending_accept', 'confirmed', 'on_the_way', 'arrived', 'in_progress');
```

No data backfill. Existing users stay non-reviewers until their user id is listed in `APPLE_REVIEWER_USER_IDS` and they authenticate.

## Rollback

1. Remove `APPLE_REVIEWER_USER_IDS` (or set it empty) and restart. Also remove `APPLE_REVIEWER_EMAILS` if it is still set; it is ignored, but it should not be left around. Authenticated users lose the lane on their next request. The server sets `is_apple_reviewer` back to false for the user who is signing in. Hidden reviewer profiles stay `is_test` so they do not appear in the public catalog. Unhide a profile only if that id was bound by mistake and the profile meets the production requirements.
2. Drop the index and columns when you no longer need them. Postgres:

```sql
DROP INDEX IF EXISTS uq_booking_active_slot;
ALTER TABLE bookings DROP COLUMN IF EXISTS reviewer_lane;
ALTER TABLE users DROP COLUMN IF EXISTS is_apple_reviewer;
```

SQLite 3.35 and newer:

```sql
DROP INDEX IF EXISTS uq_booking_active_slot;
ALTER TABLE bookings DROP COLUMN reviewer_lane;
ALTER TABLE users DROP COLUMN is_apple_reviewer;
```

`downgrade_reviewer_schema` runs those statements. SQLite older than 3.35 cannot drop a column in place; restore a backup taken before the upgrade instead. Dropping the unique index brings back the check-then-insert race for active slots.

Lane bookings already stored keep `payment_provider = 'mock'` after the column drop. That record is the simulated charge and should not be replayed against a live provider.

Leaving the columns in place is the safer code rollback. The previous SQLAlchemy models select only the columns they define, and both new columns default to false. Drop them later with the SQL above when nothing reads them. Keep the unique index unless you intend to allow the slot race again.
