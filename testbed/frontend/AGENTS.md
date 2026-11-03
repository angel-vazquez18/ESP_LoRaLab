# Dashboard instructions

Read root and testbed `AGENTS.md`. This is the existing React/TypeScript/Vite UI.

- Prioritize GUI usability while retaining the same backend behavior for the CLI.
- Preserve Bench, Experiments, Campaigns, Voice and Results workflows, light/dark
  appearance, responsive layout, and physical node requirements and historical evidence provenance.
- Call backend interfaces; do not open serial ports, calculate independent passing
  assessments or maintain a second run/campaign state machine in the UI.
- Show unavailable capabilities, incomplete evidence and failed cleanup accurately.
  Reference-file playback is not received RF voice.
- Keep frontend changes compatible with backend event/HTTP shapes and error states.
- Use the existing layout and styling conventions. Verify meaningful interaction
  changes in the browser when available; a production build alone is not browser QA.

From repository root: `npm --prefix testbed/frontend run build` and
`npm --prefix testbed/frontend run format:check`. `make frontend-dev` starts Vite;
run the backend separately with `make serve`.
