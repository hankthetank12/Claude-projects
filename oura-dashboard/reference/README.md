# Pinned Oura API reference

`oura-openapi-1.37.json` is Oura's own OpenAPI document (spec version 2.0),
served from <https://cloud.ouraring.com/v2/static/json/openapi-1.37.json>.

It is vendored here because the field semantics are not guessable and getting
them wrong produces plausible-looking but wrong numbers. Two examples that
this file settled:

- `daily_stress.stress_high` and `recovery_high` are **seconds**, so a value
  of 240 is four minutes, not four hours.
- `sleep.type` is an enum where `rest` is *falsely detected* sleep the user
  rejected and `deleted` is sleep the user removed — neither is a night, and
  `sleep` is capped at three hours so it is a nap rather than a night.

Check any new field against this file before reading it, and re-download it
when Oura publishes a newer version.
