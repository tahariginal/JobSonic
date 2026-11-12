# Application workflow

## 1. Discovery (automatic, no AI)

Every 12 hours (Settings → Search & schedule) the worker reads each enabled employer board, keeps
engineering titles, and for each posting stores the official URL, job ID, timestamps and a content
fingerprint. Known jobs are updated only when their content changes; jobs that disappear from the
board are marked closed. A job you are working on is re-verified daily and before every form run.

## 2. Analysis (automatic, no AI)

Each job gets:

- **Eligibility**: `eligible`, `needs_review` or `rejected`, with reasons. Each reason is labelled
  *Verified* (a quote from the posting), *Unverified* (nothing found) or *AI interpretation*.

  | Rejected when | Needs review when |
  |---|---|
  | Senior-level title | Experience level not stated |
  | Needs clearly more than your limit (default 2 years; ≥ 4 rejects) | Asks for about 3 years |
  | Requires existing work authorization / excludes sponsorship | Mid-level title, internship |
  | Requires a security clearance, a PhD, or is unpaid | Degree required with no stated alternative |
  | Closed | A language you have not confirmed appears required |

  The 42 Common Core is never treated as a bachelor's degree: such jobs go to Needs review.
  You can override any verdict in the job panel.

- **Visa status**: *Confirmed* (explicit statement for this vacancy), *Conditional* (may be
  considered / local authorization preferred), *Unverified* (nothing found), *Not supported*
  (explicitly excluded), *Not needed* (job is where you already have authorization).
  Relocation help is tracked separately and never upgrades the visa status. Remote roles are
  marked "possibly" workable from Morocco only when described as worldwide.

- **Fit 1–5★**: weighted score of skills overlap (28), experience level (22), visa feasibility (22),
  interests (14), location (9), salary (5). A job with no sponsorship evidence cannot exceed 4★;
  a rejected job is 1★. The explanation and breakdown are shown in the job panel.

## 3. Shortlist and prepare

From a job: **Shortlist**, then **Prepare application**. The system:

1. Picks a CV (one tagged for the role type, otherwise your default).
2. Reads the form's questions (Greenhouse publishes them; Lever and Ashby start from standard fields).
3. Answers each question from your profile, labelled by source:
   *From your profile*, *Your standard answer*, *Generated — check it*, *Edited by you*,
   or **Needs your input** when it cannot be answered truthfully.
4. Writes a cover letter (factual template, or AI if enabled).

Work-authorization answers follow your profile: outside your authorized countries it answers
"not authorized / will need sponsorship". Start-date questions use your earliest desired date and
note that the real date depends on visa processing. Degree questions are never auto-answered.

## 4. Fill the form for review

**Fill form for review** queues a browser run that opens the employer's form, enters the answers,
uploads the CV, takes a full-page screenshot and stops. It never presses submit.

- Questions that only exist on the live page are added to the answer list and resolved the same way.
- A required field that cannot be completed, a CAPTCHA, a login wall or a closed posting stops the
  run and creates a notification.
- When everything required is in place the job moves to **Awaiting approval**.

## 5. Approve

Approvals → open the application. You see the CV, the cover letter, every answer with its source,
whether each was actually entered in the form, and the screenshot. Then:

- **Approve & submit**: approves this exact version (revision + content hash).
- **Request changes**: back to Preparing.
- **Reject**: nothing is sent; the job leaves your pipeline.
- **Edit** anything: saves a new version, cancels any approval, and the form must be filled again.

## 6. Submit (only after approval)

The worker re-checks that the vacancy is open and that the approved hash still matches, claims the
submission once, refills the form, confirms the same fields were placed, presses submit **once**
and looks for a confirmation page.

| Outcome | What happens |
|---|---|
| Confirmation seen | Status **Submitted**, confirmation text and screenshot saved, stage → Submitted |
| Failed before sending (validation error, CAPTCHA, form changed, vacancy closed) | Nothing sent, approval cancelled, you are notified |
| Pressed submit but no confirmation detected, or a crash/restart mid-way | **Check manually**. Never retried. You record "It was sent" or "It was not sent". |

## 7. When manual action is needed

The application page shows what blocked the agent, a **Copy answers** button and the official
form link. Finish it yourself on the employer's site, then **Mark as submitted**.

## 8. Tracking

With Gmail connected (read-only), confirmations, interview invitations, replies, rejections and
offers are matched to applications with a confidence score. Clear, well-matched emails move the
pipeline (e.g. Submitted → Interview); ambiguous ones only notify you. You can correct the
category or the link in Settings → Email. Without Gmail, move cards by hand in the Pipeline.
