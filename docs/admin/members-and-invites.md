# Members & invites

> **Doc status:** Active

Two ways to add someone to the household, plus what to do when neither the
person nor the server has an email address.

## Invites (the member path)

Any member with quota left can create an invite from **Account → Profile →
Invites**. Admins see the household's quota allocation at **Admin → Invites**.

An invite is a **link**. Email is one way of delivering it, not what it is:

| You have | What happens |
|---|---|
| An email address **and** SMTP configured | The server sends the link and also shows it, so you can pass it on yourself if the mail does not arrive |
| An email address, no SMTP | The invite is created and the link is shown. Nothing is sent, and the response says so rather than implying delivery |
| No email address | Leave the field blank. The invite is created as a link with no recipient recorded |

Links last **48 hours** and hold a quota slot until they are used or revoked.
Revoking one frees the slot immediately.

> **Set the site URL first.** Invite links are built from **Admin → Settings →
> site URL**. Left at the default, every link points at `127.0.0.1` and works
> only on the server itself. The invites panel says so when it is unset.

Requiring an email address is what used to make invites unusable on a household
with no mail server: the form demanded one, handed it to a mailer that was never
configured, and the link — which works perfectly well pasted into a chat window —
was never shown to anybody.

## Adding a member with no email at all

Some accounts have nowhere to send mail and never will: a child's console login,
the living-room TV, a guest sitting next to you. For those,
**Admin → Invites → Add member without email** creates the account directly.

You choose the username, the password and the role. The person can sign in
immediately, and can add an email later from their own profile.

### What the server stores

`users.email` is `NOT NULL UNIQUE`, and a good deal of code reads it without
checking — login by email, password reset, the digest mailer, OIDC linking.
Rather than relax the column and push a `None` into all of them, an emailless
account gets an **unroutable placeholder** in `no-email.invalid`. RFC 2606
reserves the `.invalid` TLD precisely so that it can never be delegated, so the
address can never resolve and can never receive mail.

Consequences worth knowing:

- The roster shows **no address** for these accounts, not the placeholder. It is
  never presented as somewhere to write to.
- They are never marked email-verified — there is nothing to verify. The login
  "activate your account" check knows to skip these accounts, so they sign in
  immediately regardless.
- **Password reset by email does not work for them.** An admin resets the
  password from **Admin → Users**.
- Clearing the email field on an existing user in the editor converts them to a
  local account the same way; it does not error and does not silently keep the
  old address.

## Roles

| Role | Can |
|---|---|
| `admin` | Everything, including the admin shell |
| `librarian` | Library and scan management |
| `user` | Browse, download, play, chat |
| `child` | Browse, play, and chat within the parental / library ACL. No admin, no library writes, no Acquire search, no companion download/install |

Library allowlists and content filters are per-user, under **Admin → Users**.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Invite link points at `127.0.0.1` | Site URL never set | Admin → Settings → site URL, then create a new invite |
| "You have reached your invite limit" | Open invites already fill the quota | Revoke an unused one, or raise the quota in Admin → Invites |
| Invite created but nothing arrived | SMTP not configured, or the send failed | The link is in the invites panel — pass it on directly. The response reports `emailed: false` rather than claiming delivery |
| A member cannot reset their own password | Emailless account | Reset it for them in Admin → Users |
| "Invalid email format" when saving a user | A malformed address was typed | Fix it, or clear the field entirely to make it a local account |

## Related

- [settings-modules.md](settings-modules.md) — SMTP, site URL, feature toggles
- [privacy-data-handling.md](privacy-data-handling.md) — what the host stores and what `child` cannot do
- [../user/getting-started.md](../user/getting-started.md) — the member's view of the account modal
- [../runbooks/oidc-sso.md](../runbooks/oidc-sso.md) — SSO instead of local accounts
