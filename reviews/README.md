# Opus Review Sessions

Deze folder bevat alle outputs en tracking van de Opus 4.6 systematische bot review.

## Structure

```
reviews/
├── README.md                    # Dit bestand
├── REVIEW_PROGRESS.md          # Track progress per sessie
├── prepare_session.ps1         # Helper script om files te bundelen
├── session1_files.txt          # Generated: files voor Opus
├── session1_execution_logic.md # Output van Opus sessie 1
├── session2_files.txt
├── session2_risk_management.md
└── ...
```

## Quick Start

### Voor Sessie 1:

```powershell
# 1. Prepare files
.\reviews\prepare_session.ps1 -Session 1

# 2. Dit opent notepad met alle files
#    Copy alles (Ctrl+A, Ctrl+C)

# 3. Open nieuwe Opus 4.6 chat in Copilot

# 4. Paste prompt van OPUS_REVIEW_PLAN.md -> Sessie 1

# 5. Paste de files van session1_files.txt

# 6. Laat Opus zijn werk doen!

# 7. Save output als session1_execution_logic.md

# 8. Update REVIEW_PROGRESS.md
```

### Voor volgende sessies:

Herhaal met `-Session 2`, `-Session 3`, etc.

## Tips

- ✅ Start NIEUWE chat voor elke sessie
- ✅ Save alle Opus output als markdown
- ✅ Update REVIEW_PROGRESS.md na elke sessie
- ✅ Implement fixes incrementeel, test na elke change
- ✅ Commit na elke geimplementeerde fix

## Vragen?

Zie `OPUS_REVIEW_PLAN.md` voor volledige instructies.
