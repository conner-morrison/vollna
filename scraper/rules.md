# Job filtering rules

What this project decides about a job before anything is sent to the server. The result is one of
**bid**, **manual check** or **skip**.

Client info is judged first.

## Client rules

Two values decide it, both from the client block of a Vollna page:

| Field | Where it comes from | Example |
|---|---|---|
| Total spent | `total spent` | `$301701` |
| Average hourly rate paid | `avg hourly rate` | `21.04/hr` |

| Total spent | Average hourly rate | Result |
|---|---|---|
| ≥ $100K | ≥ $20/hr | **bid** |
| ≥ $100K | < $20/hr | **manual check** |
| < $100K | > $10/hr | **manual check** |
| < $100K | ≤ $10/hr | **skip** |
| none (new client) | none | **bid** |

A **new client** is one Vollna shows with no spend and no hourly rate at all, because the account
is too new to have any history. Example: the client on filter 47052, registered three days before.

Exactly $10/hr counts as **skip**, and exactly $20/hr with spend of $100K or more counts as **bid**.

## Open points

Not covered yet, left as **manual check** until decided:

- **Half-missing values**: a client with spend but no hourly rate, which happens when they have
  only ever hired on fixed price. That is not a new client, so the "new client → bid" rule does
  not apply.
- **Fixed-price jobs**, where an hourly rate says nothing about the budget on offer.

## Still to define

- What happens to each result: which of them reach the server, and in what form.
- Whether anything from project info (hours per week, duration, experience level, project type)
  or the client's work history changes the outcome.
