# Competitive brief: Example Platform versus Other Platform for restarts

Illustrative example of the required shape. Its content is not researched.

## 1. Executive summary

Both platforms restart apps in batches. Example Platform paces a restart on health checks, which makes it safer for apps with slow start-up. Other Platform is simpler to license. Neither keeps a single-instance app available through a restart.

## 2. Comparison

<!-- findings: availability health-checks other-platform licensing -->

| Dimension | Example Platform | Other Platform | As of |
| --- | --- | --- | --- |
| Restart model | Batches, paced by health checks [1][3] | Batches, on a fixed timer [5] | 2026-09 |
| Single-instance apps | Drop requests during restart [2] | Drop requests during restart [5] | 2026-09 |
| Licensing | Per instance [6] | Flat per cluster [6] | 2026-08 |

## 3. Differentiators

<!-- findings: health-checks other-platform -->

- Example Platform waits for new instances to pass health checks before continuing [3]. Other Platform moves on after a fixed interval [5].

## 4. Limitations

<!-- findings: instance-min licensing -->

- Example Platform's per-instance licensing makes adding a second instance cost more than on Other Platform [6].
- Neither platform protects a single-instance app during a restart [2].

## 5. Qualification questions

<!-- findings: instance-min other-platform -->

- Do your apps take longer to start than a fixed restart interval allows?
- How many of your apps run a single instance?

## 6. Objections and responses

<!-- findings: zero-downtime licensing -->

- **"Other Platform told us restarts are zero downtime."** Neither platform achieves that for a single-instance app [4]. Ask which of their apps run one instance.
- **"Your licensing punishes us for running safely."** A second instance does cost more here [6]. Weigh that against the cost of a failed restart on a slow-starting app.

## 7. Unknowns

- How either platform rolls back a failed restart. The research question is still pending.
- Other Platform's pricing after 2026-08. Check the date before quoting it.

## 8. Sources

1. Finding `availability`: Example Platform documentation, "Restarting apps", 2026-09-01, https://example.com/docs/restarting
2. Finding `instance-min`: Example Platform documentation, "Scaling", 2026-09-01, https://example.com/docs/scaling
3. Finding `health-checks`: Example Platform documentation, "Health checks", 2026-08-14, https://example.com/docs/health
4. Finding `zero-downtime`: Example Platform support note, "Restart behaviour", 2026-07-30, https://example.com/support/restart-behaviour
5. Finding `other-platform`: Other Platform documentation, "Restarts", 2026-09-10, https://example.org/docs/restarts
6. Finding `licensing`: both vendors' pricing pages, 2026-08-20, https://example.com/pricing and https://example.org/pricing
