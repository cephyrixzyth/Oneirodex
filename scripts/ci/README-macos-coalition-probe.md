# macOS coalition capability probe

> **Doc status:** Reference

`probe-macos-launch-coalition.py --output <report.json>` tests ordinary-user API access, two uniquely labelled temporary user launchd jobs, an independently launched outsider, held guardian leases, guardian-only counter baselines and resource-coalition isolation. It requires macOS and refuses root. Nonzero exit2 means unsupported runtime/API/domain; exit1 means a failed invariant or fixture cleanup. Every controller run writes a structured result. There is no privileged setup or automatic fallback.

This first phase does **not** test descendants, detached children, guardian-loss game survival, production tracking, account recovery or packaged acceptance. `family_recovery_acceptance` remains false even if the phase passes. A source build or successful job cannot close those gates.

`python3 scripts/ci/test_macos_launch_coalition_probe.py` checks controller safety with simulated command faults: a bootstrap error/timeout must unload the exact attempted label, a still-loaded job after bootout must fail, rejected bootstrap with a confirmed absent job retains its unsupported result, shared outside coalitions cannot pass, and root cannot qualify ordinary-user behavior. These tests do not execute or qualify macOS APIs.

The ABI probe is constrained by pinned Apple XNU source `f6217f891ac0bb64f3d375211650a4c1ff8ca1ea`: [coalition overview](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/doc/observability/coalitions.md), [counter prefix and bounded copy](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/sys_coalition.c#L252), and [process-query structure/flavor](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/sys/proc_info_private.h#L63). Source declarations do not establish runtime availability; the executable probe checks actual symbols and return sizes.

Only disposable synthetic Python guardians run. Temporary jobs never enter login/autostart directories; cleanup addresses their exact unique labels. No user game, credential, server connection, kernel setting, signing entitlement, system service or production installation is used. The installed platform's launchd behavior still requires the later game-survival controls.
