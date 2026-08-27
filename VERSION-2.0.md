# Short Analytical Note

## What Changed

The SDD Pipeline now has a stronger process for creating high-quality design before writing code.

### 1. Better Definition of User Needs

At the `product-idea` stage, the process now additionally clarifies:

- what exactly the user wants to accomplish;
- the situation in which the need arises;
- what triggers the action;
- what outcome counts as successful;
- how the user solves the problem today;
- what constraints exist: device, time, attention, accessibility, and internet access;
- what the user is afraid of or where they may make a mistake;
- what evidence confirms that the task was completed successfully.

This helps create design from a real user situation rather than from a list of features.

### 2. Jobs To Be Done Added

`Job To Be Done` is a short description of the real task the user wants to solve.

For example:

> “When I need to compare options quickly, I want to see the key differences so that I can make a confident decision.”

Each important task receives a `JOB-*` identifier. This is simply a stable reference that prevents the connection between the user need, design, and implementation from being lost later.

### 3. Use Cases Added

`Use Case` describes how the product helps the user complete a specific task:

- who acts;
- what triggers the process;
- what conditions are required;
- what the primary path is;
- what happens when an error occurs;
- how the user can retry the action or recover the process;
- what outcome counts as completion.

`UC-*` identifiers are used for these cases.

`JOB-*` answers “why is the user doing this?”, while `UC-*` answers “how exactly does the product support it?”.

### 4. Formal H1-H10 Heuristic Layer Added

A single list of 10 usability principles from Nielsen Norman Group is now used:

1. visibility of system status;
2. match between the system and the real world;
3. user control and freedom;
4. consistency and standards;
5. error prevention;
6. recognition rather than recall;
7. flexibility and efficiency of use;
8. aesthetic and minimalist design;
9. helping users recognize, diagnose, and recover from errors;
10. help and documentation.

For each principle, the process now records:

- where it applies;
- which screens, states, and devices are checked;
- what the expected behavior is;
- what evidence is required;
- how critical the issue is;
- whether it blocks release.

### 5. Separate Heuristic Usability Gate Added

`heuristic_usability_review` is a formal H1-H10 design review.

It is separate from:

- checking fidelity to the approved visual design;
- testing with real users;
- technical functionality testing.

In other words, an interface that looks polished and matches the mockup is not automatically considered usable.

### 6. Real User Validation Added

For critical or high-risk scenarios, the pipeline now provides a separate validation step:

- a representative target user performs a real task;
- the primary path is checked;
- desktop/mobile and key states are covered;
- the expected outcome is recorded as achieved or not achieved.

This is not the same as an expert design review. Heuristic review identifies potential problems, while user validation checks whether people can actually complete the task.

### 7. Error Handling Standardized

For every error, the design must explain:

> cause → what was preserved → next action → retry/undo → condition for successful completion

This means the user should not be left with an unclear message or lose work they have already completed.

### 8. Existing Design Approval Model Preserved

No new manual approval stages were added.

There is still one main approval: approval of the complete integrated design. The new heuristic and usability checks are quality gates and evidence of quality, not additional approval procedures.

## Overall Result

The pipeline now better ensures that:

- design starts from real user needs;
- requirements, scenarios, and screens remain connected;
- usability is evaluated systematically;
- visual fidelity is not confused with ease of use;
- errors and recovery are designed in advance;
- important problems are identified before implementation;
- different stages do not duplicate one another and have clear areas of responsibility.

The changes have been committed and pushed to the repository.
