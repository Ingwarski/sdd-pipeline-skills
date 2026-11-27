# Move an existing installation to the current repository

The current repository starts from one consolidated, tested SDD snapshot. Older
clones with unrelated history need a separate new installation. A clean,
compatible standalone checkout can use the [guarded update](docs/installation.md#guarded-entry-point),
even if its own updater predates location checks.

1. Inventory the existing checkout, Git identity, hidden and untracked files,
   registration roots, receipts and actual link targets. Make a private backup
   that includes local work and Git metadata, and verify a restore to a different
   directory. Keep old history and recovery bundles private.
2. For a misplaced installation in a product or an ambiguous checkout, follow
   [misplaced-installation recovery](docs/installation.md#recover-a-misplaced-installation)
   with the owner. Quarantine only approved, individually identified accidental
   additions. Preserve the product and all uncertain files.
3. Select a new permanent **absolute path** outside all products and worktrees.
   Use the official release's [guarded bootstrap](docs/installation.md#guarded-entry-point).
   It checks the chosen location before cloning, pins the revision and
   validates each selected personal registration root. If a former registration
   conflicts, preserve the reported path and check its ownership against the
   inventory before a separate repair.
4. Verify the physical checkout, exact SHA, personal registration directories
   and all 13 actual link targets and resources for each selected agent. Retain
   the old installation privately until recovery is verified. Preserve local
   customizations for separate review. Resume regular updates from the new
   standalone checkout.

The project workflow handles product migration and revalidation on authorized
resume. Installing the skillset alone does not authorize moving project files,
rewriting history or transferring local edits into the release checkout.
