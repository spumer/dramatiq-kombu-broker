---
argument-hint: [feature description]
description: Orchestrate Django/Python feature implementation with architecture, coding, and review phases
---

# Task

You are orchestrating implementation for feature: $ARGUMENTS

## Workflow

This is a multi-agent workflow with clear separation of concerns:

1. **django-architect** - Designs architecture, creates plans (NO CODE, NO TESTS)
2. **python-implementer** - Writes code according to plan (NO TESTS)
3. **code-reviewer** - Runs tests, linters, finds issues, creates review files

## Implementation Loop

For EACH implementation stage:

### Step 1: Architecture
Launch **django-architect** agent to create/update architectural plan.

### Step 2: Implementation
Launch **python-implementer** agent to write code according to plan.
INSTEAD you CAN run multiplie **python-implementer** agents in PARALLEL to solve INDEPENDED plan PARTS in a quick way.

### Step 3: Review
Launch **code-reviewer** agent to test and review implementation.

### Step 4: Fix or Complete
- **If code-reviewer found issues**: Return to Step 1 with review files
- **If no issues**: Mark stage as ✅ Complete

## Directory Structure

```
features/
  FEAT-[0-9]{4}-<name>/
    README.md                       # Feature requirements
    ARCHITECTURE.md                 # Architecture plan (django-architect)
    ARCHITECTURE_review_<N>.md      # Fix plan for review round N (django-architect)
    review-request-changes/         # Review findings (code-reviewer)
      0001-issue.md
      0001-issue.md_solved
      0002-issue.md
    .test-output/                  # Test results (code-reviewer)
      pytest-run.txt
      linter-output.txt
```

## Critical Rules

- **Separation of Concerns**: Each agent has ONE responsibility
  - Architect = Design only
  - Implementer = Code only
  - Reviewer = Test & review only

- **Artifact Storage**: All files in `features/FEAT-[0-9]{4}-<name>/`

- **Loop Until Clean**: Continue until code-reviewer finds no issues

- **Agent Knowledge**: Each agent knows its responsibilities from its own .md file