# Environment-specific Shortcut templates

Links are selected by the existing validated runtime AppEnvironment. Missing runtime
environment, method or authorization returns no link. There is no cross-environment
fallback. Intent types, queries and execution are unchanged.

## Published metadata inspection (2026-11-27)

All eight owner-supplied Apple iCloud signed assets were downloaded read-only,
LZFSE-decoded and their embedded property lists inspected. Each has one action,
with consistent action identifier, descriptor bundle and intent identifier:
Development = com.familycaragent.app.dev; Production = com.familycaragent.app.
No XTL descriptor or preselected vehicle parameter appears. Action parameters are
only AppIntentDescriptor and the action UUID (not a vehicle identifier).

| Environment | Method | Action | iCloud ID |
|---|---|---|---|
| Development | CarPlay | TAKE | 099b74c9808f4dcba04a8578e2a469d0 |
| Development | CarPlay | RETURN | 34aa0aaf15cb43a8b1824176231f3950 |
| Development | Bluetooth | TAKE | 306ff496250b4e28a7702ca430e94ffe |
| Development | Bluetooth | RETURN | 022b1a3800b243a4b576fb7deac614ab |
| Production | CarPlay | TAKE | 90e16638d8a84f44868298cfebf95a92 |
| Production | CarPlay | RETURN | f67ed93cb09c4dee8ed595c9d14db3db |
| Production | Bluetooth | TAKE | e1bd388340fe49309523a570f05b12f6 |
| Production | Bluetooth | RETURN | 6ee5f10d3f154735b2e3c7ac4430dc7b |

All templates ask for the vehicle at action index 0 and trigger enablement.
CarPlay also asks about notification settings; Bluetooth asks for the selected
Bluetooth device. These are metadata observations, not proof that iOS presents or
applies every import question. Cryptographic signature trust was not independently
verified. Published content inspection is a snapshot, not a future immutability guarantee.

## Existing installations and physical acceptance

Updating these links does NOT repair stored action associations in already installed
shortcuts. Owners must manually replace the old templates/actions and update each
automation to reference the correct new shortcut, avoiding duplicate triggers.
Do not reset accounts, device identity or offline queues.

With both apps installed, import each environment's templates and verify its vehicle
picker shows that environment only. Re-export to confirm action association. Check
CarPlay/Bluetooth trigger, TAKE/RETURN direction, vehicle selection and import prompts.
Actual automation execution and environment-correct Backend routing require a separate
owner-controlled physical acceptance cycle. No templates were imported or executed
by this implementation task.
