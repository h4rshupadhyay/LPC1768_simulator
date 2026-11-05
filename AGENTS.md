# Development isolation

The user practises for examinations in the primary checkout
`C:\Users\kavyk\OneDrive\Desktop\Projects\LPC1768_simulator_extended` on branch
`main`. This is the practice checkout, including when this file is read from that
directory. Develop in `.claude\worktrees\open-workbench` (branch
`worktree-open-workbench`) or another isolated worktree.

- Do not edit, build, stash, reset, or run tests in the practice checkout during development.
- Do not send test requests to its server on port 8765 or restart that server during development.
- Use the development worktree's own `.venv`, `node_modules`, `build`, `dist`, and test results.
- Use port 8879 for the development worktree; explicitly set `LPC_LAB_URL=http://127.0.0.1:8879` for browser tests.
- `start-isolated.bat` and `test-isolated.bat` set those ports automatically. For development, never use plain `start.bat` or the bare browser test command, which default to the practice port.
- When the user explicitly requests promotion, commit and merge the verified changes into `main` and update the practice build. Preserve its running firmware state whenever possible. Keep the development worktree for future work.
