# Move an existing installation to the current repository

The current repository starts from one consolidated, tested SDD snapshot.
Older clones have unrelated history. The updater deliberately refuses to merge
or overwrite them. New installations use the normal installation guide.

For an existing installation:

1. Preserve uncommitted work and needed local changes privately before replacing
   the old checkout. Do not upload old Git history or recovery bundles.
2. Clone `https://github.com/Ingwarski/sdd-pipeline-skills.git` into a new durable
   folder using the tested `stable` channel, then create the local `main` branch
   as described in [installation](docs/installation.md).
3. If local skill customizations are needed, review and transfer their file
   changes individually onto the new checkout. Do not merge old branches, copy
   an old `.git` directory, or push old tags. Exclude the retired personal skills
   and their supporting content.
4. Run the documented installer from the new durable checkout to reconnect the
   SDD links in the selected agent installations. Verify all 13 exact targets and
   their resources with `scripts/installation_status.py`.
5. Disable pushing from the old checkout and retain it privately only while
   needed for recovery. Resume normal updates from the new checkout.

Existing product repositories, their work, approvals and test evidence remain
intact. Skill installation does not migrate product records. The current SDD
workflow handles migration and revalidation when a project is resumed within
its existing authorization.

Independent personal skills outside the SDD checkout are not distributed here.
The installer continues to remove the two retired original invocation names
from its explicitly managed roots while preserving unrelated personal names.
