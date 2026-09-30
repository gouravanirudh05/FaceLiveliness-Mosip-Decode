# Architecture boundary

This project is a standalone local service/application. It must not import or
modify MOSIP Registration Client classes.

`mds-adapter` will expose the MDS/SBI endpoints expected by the configured
MOSIP client. `liveness-core` will decide whether a capture is allowed.
`desktop-companion-ui` is reserved for active-challenge guidance when the
device itself cannot present prompts.

The MDS adapter must keep protocol-specific DTOs isolated from `liveness-api`.
This permits future device vendors and liveness engines to be added without
changing the common workflow contracts.
