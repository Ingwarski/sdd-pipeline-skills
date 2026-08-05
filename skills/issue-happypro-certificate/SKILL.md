---
name: issue-happypro-certificate
description: Prepare, visually verify, issue, revoke, or reissue a HappyPro Academy certificate for AI-Driven Digital Product Engineering through the protected website manager flow. Use when the founder provides a registered student's email and English first/last name and wants a certificate PDF with a unique QR verification ID. Always stop after preview for explicit founder approval before issuing.
---

# Issue HappyPro Certificate

## Mission

Operate the HappyPro Academy certificate registry through the website UI. Make
the routine founder workflow fast while preserving the human approval gate,
recipient privacy, immutable issued PDFs, and public verification integrity.

The course printed on the PDF is exactly:

`AI-Driven Digital Product Engineering`

The management route is `/manager/certificates/`. The student route is
`/account/`. The public verification route is `/certificates/<certificate-id>`.

## Required Input

Collect only missing values:

- the registered student's email;
- English first name;
- English last name.

Accept an explicit instruction to revoke or reissue an existing certificate.
Do not ask for an email-delivery address: this system does not send certificate
email. Do not create an unregistered recipient.

## Source Of Truth

Use the live manager page and its returned status as the issuance source of
truth. Do not write directly to the database, certificate store, access store,
or enrollment store. Do not manufacture an ID or PDF outside the site flow.

The approved certificate visual source is the server's canonical DRAFT_v5 SVG
template. A preview must retain its `PREVIEW` watermark. The final issued PDF
must not contain that watermark.

## Workflow

1. Open the site's `/manager/certificates/` route in the available browser.
2. If login is required, leave the manager Google sign-in to the founder. Never
   request, read, or store credentials.
3. Search by exact email and select the registered student. If the email is not
   present, stop and report that the user must register first.
4. Compare the manager profile's certificate name with the supplied English
   first and last names. Update and save it when different. Use Latin letters,
   spaces, apostrophes, and hyphens only.
5. If course completion is not confirmed, use `Позначити завершеним`. This is a
   founder-controlled decision; do it only when the invocation asks to issue a
   certificate for that student.
6. Create the preliminary PDF. Open the full preview and visually inspect all of
   the following:
   - HappyPro logo, gears, flowchart, waves, raspberry dot, and blue background;
   - recipient name spelling and centering;
   - exact English course title;
   - current Kyiv issue date;
   - QR code, visible random `HPA-...` ID, founder signature and issuer caption;
   - `PREVIEW` watermark;
   - no clipping, overlap, missing asset, placeholder QR, or `%%...%%` token.
7. Report the previewed name and current status, then stop for explicit founder
   approval. Do not click `Підтвердити й випустити` in the same turn that created
   the preview unless the founder had already explicitly approved that exact
   preview after seeing it.
8. After explicit approval, click `Підтвердити й випустити` once. Record the
   returned certificate ID and verification URL.
9. Open the public verification URL and confirm HTTP-visible content shows the
   correct recipient, course, issue date, ID, and `Дійсний` status. Report the
   result and tell the founder the PDF is now available in the student's
   `/account/` certificate tab.

## Revoke And Reissue

For a correction after issuance:

1. Open the existing certificate and confirm its ID.
2. Ask for explicit confirmation if revocation was not already directly
   requested. Revocation changes public state and makes the old PDF unavailable
   in the student's account.
3. Click `Анулювати сертифікат` and verify the old public route shows
   `Анульований`.
4. Correct the English name if needed, create and visually inspect a new preview,
   and stop for approval again.
5. Issue only after approval. Confirm the new ID differs from the revoked ID and
   that the new public route is `Дійсний` while the old route remains
   `Анульований`.

## Safety Rules

- Never bypass the preview or founder approval gate.
- Never infer course completion from lesson visits, payment, or course access.
- Never expose or copy a student's email onto a public verification page or PDF.
- Never send a certificate by email.
- Never reuse an old ID or sequentially invent an ID.
- Never claim issuance from a green button alone; verify the public route.
- If the browser, login, manager role, or live site is unavailable, stop with the
  exact blocker and preserve any already-created preview.

## Completion Report

For a prepared preview, report:

- student email;
- exact English certificate name;
- course completion status;
- that visual verification passed or the exact defects found;
- `Awaiting founder approval`.

For an issued certificate, report:

- certificate ID;
- public verification URL;
- recipient, course, issue date, and public status verified;
- PDF available in `/account/`;
- whether any prior ID was revoked.
