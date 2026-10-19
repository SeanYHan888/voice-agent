# Lesson 1 — Product Vocabulary

## 1. Product vocabulary

**Definition:** Product vocabulary gives one precise name to each actor, identity transition, and scheduling state so code and discussion refer to the same thing.

Maya is a clinic receptionist implemented as software. She answers clinic questions, schedules visits, and creates work for an Admin when a request needs human judgment.

| Term | Meaning in this repository |
|---|---|
| Caller | Someone in a live voice conversation whose identity is not yet proven |
| Patient | A person represented by a clinic Patient record |
| Verification | Proving that a Caller is a particular Patient during a Call |
| Authentication | Signing into the web portal as a Patient or Admin account |
| Slot | Unclaimed time on a Provider's calendar |
| Appointment | A Slot claimed by a Patient for a Visit Type |
| Approval Task | Pending work requiring an Admin decision before a restricted action executes |

Follow this scenario:

```shell
Jordan begins speaking
        |
        v
Caller --Verification--> Patient
                            |
                            | chooses
                            v
Slot + Visit Type ----> Appointment
                            |
                            | near-term cancellation
                            v
                      Approval Task
                            |
                            v
                          Admin
```

The important contrasts are:

```shell
Caller        != Patient
Verification  != Authentication
Slot          != Appointment
Approval Task != completed action
```

A Caller asking for public clinic hours needs no Verification because the request does not access a Patient record.

**Next:** Once the nouns are clear, locate the independent processes that own them.
