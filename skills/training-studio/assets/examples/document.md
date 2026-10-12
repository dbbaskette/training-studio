# Rolling restarts

Illustrative example of the required shape. Its content is not researched.

**For:** solutions engineers who deploy apps and need to explain restart behaviour to customers.
**Time:** 25 minutes.

**After this you will be able to:**

- describe what a rolling restart does,
- explain when a rolling restart keeps capacity,
- answer a customer who believes rolling restarts guarantee zero downtime.

## Why this matters

<!-- covers: O3 -->

A customer restarts an app during business hours, sees dropped requests, and says, "You told us this could not happen." What you say next decides whether they trust the platform. This guide gives you the facts to answer well.

## What a rolling restart does

<!-- covers: O1 K1.1 K1.3 -->

A rolling restart replaces an app's instances one batch at a time rather than all at once [1]. The platform stops a batch, starts its replacements, and waits. Health checks decide when the next batch starts: the platform moves on only when the new instances report healthy [3].

## When capacity holds

<!-- covers: O2 K1.2 -->

Capacity holds only when more than one instance is running [1][2]. With three instances, two keep serving while one restarts. With one instance, nothing serves while it restarts.

> **Common mistake.** "Rolling always means zero downtime." A single-instance app still drops requests while it restarts [2].

### Worked example

A web app runs three instances behind a router. During a rolling restart the platform replaces the first instance while the other two serve traffic, waits for its health check to pass, then moves to the second. Capacity never falls below two instances.

## Summary

- A rolling restart replaces instances in batches, and health checks pace the batches.
- It keeps capacity only when more than one instance is running.
- For a single-instance app, expect a gap, and say so.

## Check your understanding

1. What happens to an app's instances during a rolling restart?
2. Why does a single-instance app lose capacity during a rolling restart?
3. A customer says rolling restarts guarantee zero downtime. What do you say?

## Answer key

1. They are replaced one batch at a time, with health checks deciding when the next batch starts.
2. Nothing else is running to serve requests while its only instance restarts.
3. Separate apps with more than one instance from single-instance apps, explain the gap for the second kind, and recommend running more than one instance where continuous capacity matters.

## Glossary

- **Instance:** one running copy of an app.
- **Health check:** the test the platform uses to decide an instance is ready to serve.

## Sources

1. Finding `availability`: Example Platform documentation, "Restarting apps", https://example.com/docs/restarting
2. Finding `instance-min`: Example Platform documentation, "Scaling", https://example.com/docs/scaling
3. Finding `health-checks`: Example Platform documentation, "Health checks", https://example.com/docs/health
