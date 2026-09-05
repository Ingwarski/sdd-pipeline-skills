# Frozen rendering inputs

Prefer self-contained candidates. `sdd-tree-sha256-v1` hashes UTF-8 `"<relative-path>\n<file-sha256>\n"` entries for every regular file in the candidate root, sorted by UTF-8 path bytes. Exclude nothing; reject links/reparse points, newline paths and empty trees.

Shared assets require `sdd-render-sha256-v2` and `render_dependencies`: exact project-relative files/directories, disjoint from the candidate root and each other. Hash directories with v1 and files by bytes. Include the candidate root in `[path, hash]` pairs, sort by UTF-8 path bytes, serialize JSON with `ensure_ascii=false`, separators `(',', ':')`, then SHA-256 its UTF-8 bytes. The aggregate is `prototype_tree_hash` in candidate, baseline, approval and evidence records. Use `sdd_check.py --project PROJECT --hash-render RECORD.json` to compute it; RECORD is a project-relative JSON file.

Vendor fonts, images, CSS, scripts and mutable remote resources into the bundle. The checker rejects detectable HTML/CSS/module references outside hashed files. Actual browser/network inspection must establish dynamic dependencies; static parsing cannot prove completeness. Offline review must not depend on unrecorded remote responses. Do not hash unrelated files.

Changed shared inputs invalidate every baseline using them. Never overwrite approved files or rehash changed bytes into an old approval. Legacy v1 remains valid only for self-contained candidates; missing historical dependency evidence needs owner-reviewed migration and an explicit limitation.
