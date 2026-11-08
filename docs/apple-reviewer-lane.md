# Apple reviewer lane

Isolated customer and expert path for App Store review. The server decides who is on it. A public signup cannot join by using a `@dalla3.test` address, and a client cannot join by sending a flag.

This change does not create production users, change existing accounts, call the admin API, read credential files, deploy, or submit the app.

## What the current code was doing

Checked in this repository (the earlier iOS investigation transcript was not readable from this run):

- `server/test_accounts.py` classifies the whole `dalla3.test` domain, plus a few other test domains and local-parts, as test mail. `POST /api/auth/register` and the Apple/Google signup path store that result on `users.is_test`. The old module comment that said new signups stay `is_test = false` did not match the auth routes.
- Catalog, quotes, and booking creation treated `user.is_test` as permission to see and book hidden experts. A person who registered `anyone@dalla3.test` therefore unlocked hidden QA experts, and could still book real experts.
- `PUT /api/me/expert` copied the client field `nafath_verified` onto the profile and set `status = approved` with no server check of phone, IBAN, bank name, or freelance document. That is a self-asserted verified badge.

`GET /health` still reports the configured payment provider. It is `mock` unless `PAYMENT_PROVIDER` is changed.

## Design

`APPLE_REVIEWER_EMAILS` is a comma-separated list of **exact** mailboxes. The parser keeps only values shaped like `name@host.tld`. These are ignored:

- `dalla3.test`
- `@dalla3.test`
- `*@dalla3.test`

The allowlist is read on each request. `users.is_apple_reviewer` is updated only for the signed-in user so the column matches the allowlist. There is no startup job that rewrites other rows, and there is no backfill from the email domain. Removing an address from the variable revokes the lane on the next authenticated request.

Visibility:

| Viewer | Public approved experts | Hidden `is_test` experts | Reviewer experts |
| --- | --- | --- | --- |
| Anonymous or normal user | yes | no | no |
| Untrusted test-domain user (`is_test`, not designated) | yes | no | no |
| Designated reviewer | no | no | yes |

Booking uses the same rule. A reviewer customer cannot quote or book a real or hidden expert. A normal or untrusted user cannot quote or book a reviewer expert. The one permitted pair (designated customer + designated expert) can book, accept, and cancel. A second active booking for the same expert, date, and time is rejected with HTTP 409 until the first booking is no longer active (`pending_accept`, `confirmed`, `on_the_way`, `arrived`, `in_progress`). The check runs in the request. It is not a database exclusion constraint, so two requests arriving together can still both pass it.

Reviewer bookings set `bookings.reviewer_lane` and always use the mock payment provider, including refunds, even when `PAYMENT_PROVIDER=moyasar`.

### Expert onboarding

Production (not designated), enforced on `PUT /api/me/expert`:

- Phone on the user has at least 9 digits.
- IBAN matches a 15–34 character IBAN shape after spaces are removed.
- Bank name and freelance-document number are non-empty.
- `nafath_verified` from the client is discarded. The badge stays false until a real server-side Nafath check exists. There is no such check in this API.
- All four checks pass → `approved` and visible to the public. Otherwise `pending` and not listed.

That is the production path a completed application still follows. The reviewer shortcut does not apply to it.

Designated reviewer expert:

- Phone, IBAN, bank name, freelance number, and Nafath are not required.
- If the client sends IBAN, bank name, freelance number, or `nafath_verified`, those values are not stored. The profile keeps empty payout/legal fields and `nafathVerified: false`.
- The profile is approved only inside the lane and is marked `is_test` so it stays out of the public catalog.
- The server does not invent a phone, national id, IBAN, or Nafath subject.

`is_test` still hides QA accounts. It no longer grants a QA user access to hidden experts.

## Client contract

Boolean field **`reviewerLane`**. Read it from the server. Do not infer it from the email domain.

Present on:

- `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/apple`, `POST /api/auth/google` → `user.reviewerLane`
- `GET /api/auth/me` → `reviewerLane`
- `GET /api/me/profile` → `reviewerLane`
- Expert objects → `reviewerLane`
- Booking objects → `reviewerLane` (true for bookings created inside the lane; this stays true for that row even if the allowlist changes later)

Example:

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

`POST /api/me/expert` for the signed-in expert also returns `status` (`approved` or `pending`) so the client can tell a production application that is still missing requirements from a lane profile that is approved.

Sending `reviewerLane` on input does nothing. The field is not accepted as a privilege.

## Operator setup

Leave the default empty until the review build. Then set the exact mailboxes and restart the API:

```bash
APPLE_REVIEWER_EMAILS=apple-review-customer@dalla3.test,apple-review-expert@dalla3.test
```

- `apple-review-customer@dalla3.test` is the customer already created in the product through public signup. This repository change does not modify that row. After the variable is set, the account enters the lane the next time it authenticates. Until then it is only an `is_test` user and cannot see hidden experts.
- `apple-review-expert@dalla3.test` is **not** created by this change and was not present when this work started. Create it by signing up in the app **after** the variable is set, with no phone, IBAN, bank, freelance number, or Nafath. Saving the expert profile approves it inside the lane only.
- Use any other exact mailboxes if you prefer. Do not put a domain in the variable.
- Do not point this path at a real expert or a real customer.
- Payments for this pair stay simulated. No Moyasar charge is created for a lane booking.

The iOS app should show the reviewer flow only when `reviewerLane` is true, including skipping phone, legal, bank, and Nafath screens. Those skips are not safe as a client-only domain check; the API above is what allows the booking.

## Schema migration

On startup the API runs `upgrade_reviewer_schema` (see `server/schema_updates.py`). It adds missing columns and does **not** grant the lane to existing rows:

```sql
ALTER TABLE users ADD COLUMN is_apple_reviewer BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE bookings ADD COLUMN reviewer_lane BOOLEAN NOT NULL DEFAULT 0;
```

`DEFAULT 0` is accepted for boolean columns on Postgres and SQLite. New databases get the columns from the SQLAlchemy models (`server_default` `0`). Existing databases get them from the startup `ALTER`. The statement is skipped when the column is already there.

Equivalent Postgres, if you apply DDL yourself before boot:

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_apple_reviewer BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reviewer_lane BOOLEAN NOT NULL DEFAULT FALSE;
```

No data backfill. Existing users stay non-reviewers until their exact email is in `APPLE_REVIEWER_EMAILS` and they authenticate.

## Rollback

1. Remove `APPLE_REVIEWER_EMAILS` (or set it empty) and restart. Authenticated users lose the lane immediately; the server will set `is_apple_reviewer` back to false for the user who is signing in. Hidden reviewer profiles stay `is_test` so they do not appear in the public catalog. Unhide a profile only if it was allowlisted by mistake and it meets the production requirements.
2. Drop the columns when you no longer need the marker. Postgres:

```sql
ALTER TABLE bookings DROP COLUMN IF EXISTS reviewer_lane;
ALTER TABLE users DROP COLUMN IF EXISTS is_apple_reviewer;
```

SQLite 3.35 and newer:

```sql
ALTER TABLE bookings DROP COLUMN reviewer_lane;
ALTER TABLE users DROP COLUMN is_apple_reviewer;
```

The same statements are what `downgrade_reviewer_schema` runs. SQLite older than 3.35 cannot drop a column in place; restore a backup taken before the upgrade instead.

Lane bookings already stored keep `payment_provider = 'mock'` after the column drop. That record is the simulated charge and should not be replayed against a live provider.

Leaving the columns in place is the safer code rollback. The previous SQLAlchemy models select only the columns they define, and both new columns default to false. Drop them later with the SQL above when nothing reads them.
