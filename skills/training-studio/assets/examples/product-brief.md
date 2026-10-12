# Product brief: Rolling restarts on Example Platform

Illustrative example of the required shape. Its content is not researched.

## 1. Executive summary

Example Platform restarts an app one batch of instances at a time, so an app with more than one instance keeps serving during a restart. A single-instance app does not. That one condition answers most customer questions about restarts.

## 2. What it is and where it fits

<!-- findings: availability -->

A rolling restart replaces an app's instances in batches rather than all at once [1]. It is the default way to apply a configuration change or a new build to a running app.

## 3. Capabilities

<!-- findings: availability health-checks -->

- Keeps capacity during a restart when more than one instance is running [1].
- Paces itself: the next batch starts only when the new instances pass their health checks [3].

## 4. Limitations

<!-- findings: instance-min -->

- A single-instance app has nothing left serving while its only instance restarts [2].
- Do not present a rolling restart as a zero-downtime guarantee.

## 5. Qualification questions

<!-- findings: instance-min -->

- Which of your apps run a single instance today?
- Which of those must stay available during a restart?

## 6. Objections and responses

<!-- findings: instance-min zero-downtime -->

- **"We were told rolling restarts mean zero downtime."** That holds for apps with more than one instance. A single-instance app still drops requests while it restarts [2][4].
- **"So we have to double every app?"** No. Only apps that need continuous capacity need a second instance [2].

## 7. Unknowns

- How a failed rolling restart is rolled back. The research question is still pending.
- Whether any app type restarts without a gap on one instance. No evidence was found.

## 8. Sources

1. Finding `availability`: Example Platform documentation, "Restarting apps", 2026-09-01, https://example.com/docs/restarting
2. Finding `instance-min`: Example Platform documentation, "Scaling", 2026-09-01, https://example.com/docs/scaling
3. Finding `health-checks`: Example Platform documentation, "Health checks", 2026-08-14, https://example.com/docs/health
4. Finding `zero-downtime`: Example Platform support note, "Restart behaviour", 2026-07-30, https://example.com/support/restart-behaviour
