---
name: post-edit-py
description: After editing any .py file, format with ruff and run the matching test file (if one exists). Lightweight, non-blocking guidance hook.
applyTo: "**/*.py"
trigger: post-edit
---

# Post-edit Python hook

After editing a `.py` file, do the following lightweight checks before continuing:

1. **Format the file**:
   ```powershell
   .\.venv\Scripts\python.exe -m ruff format <file>
   ```

2. **Lint the file** (auto-fix safe issues):
   ```powershell
   .\.venv\Scripts\python.exe -m ruff check --fix <file>
   ```

3. **Run the matching test file** if one exists at `tests/test_<basename>.py`:
   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/test_<basename>.py -v -x
   ```

4. **Check for compile errors**:
   ```powershell
   .\.venv\Scripts\python.exe -c "import py_compile; py_compile.compile('<file>', doraise=True)"
   ```

If any step fails, surface the error and propose a fix BEFORE moving to the next user request.

## Skip when
- Editing test files only — running the test is enough.
- Editing `.github/`, `docs/`, `*.md`, `*.json` — not Python.
- Editing within a multi-file refactor that's still in-progress (run all checks once at the end).
