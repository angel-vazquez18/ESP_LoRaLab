# Dashboard instructions

Follow root and testbed instructions. This is the React/TypeScript/Vite dashboard.

- Preserve Bench, Experiments, Campaigns, Voice and Results, light/dark appearance
  and responsive layout. Reuse existing UI/style conventions.
- Call backend interfaces. Do not open serial ports or duplicate run state,
  orchestration or assessment rules in the browser.
- Respect advertised capabilities and physical node requirements. Show missing
  evidence, errors and incomplete cleanup accurately; reference playback is not RF voice.
- Keep HTTP/event shapes coordinated with the backend. Verify interaction changes
  in a browser when available; a production build alone is not browser verification.

From repository root run `npm --prefix testbed/frontend run build` and
`npm --prefix testbed/frontend run format:check`.
