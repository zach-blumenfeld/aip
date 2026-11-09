# Storage Formats Reference

CypherLite keeps committed state in one of four durable forms. All four share
the same engine — an in-memory graph with a write-ahead log for crash
recovery; the form only decides what a checkpoint writes to disk
([ADR-0050](../adr/0050-snapshot-codecs.md)). Every form opens with the same
`--database PATH` (or `cypherlite::Database`); the path's shape and the
store's recorded codec pick the form.

| Form | Path shape | Best for | On disk |
| --- | --- | --- | --- |
| **Parquet** (default) | directory | machine-efficient storage: columnar shards, compact, fast bulk reload | `manifest.json`, `nodes/*.parquet`, `relationships/*.parquet` |
| **JSON** | directory | human-readable snapshots with no build feature required | `manifest.json`, `graph.json` |
| **Markdown vault** | directory (the vault) | human-authorable knowledge bases — OKF notes, Obsidian vaults, git-diffable text | `Label/name.md` files + regenerated `index.md`/`log.md` views + `.cypherlite/` engine sidecar |
| **`.cl` bundle** | any path ending in `.cl` | single-file stores: copy, attach, archive | one file (a zip of the store) |

## Choosing

- **Parquet** — the default. Id-window checkpoint shards keep rewrites
  small; the columnar layout is the most compact and reloads fastest.
  Requires the `parquet` Cargo feature (the `full` CLI bundle).
- **JSON** — every committed value in one readable `graph.json`. The same
  directory layout, no feature flag: the fallback default in `agent` and
  `minimal` builds.
- **Markdown vault** — the store *is* a folder of plain markdown notes
  ([ADR-0406](../adr/0406-markdown-vault-snapshot-codec.md)). Each node is a
  file (`Person/Ada.md`): YAML frontmatter for properties, the file body for
  text, `[[wikilinks]]` for relationships. Open it in Obsidian (or any OKF
  tool), edit notes by hand while the database is closed, and the next open
  picks the edits up; `index.md` and `log.md` views are regenerated at every
  checkpoint. Machine state (WAL, manifest, journal) hides under
  `.cypherlite/`. Which properties render as the body — the first one
  bare, the rest as `## <property>` sections — is configured per label
  with `--markdown-body-properties`
  ([ADR-0460](../adr/0460-markdown-body-properties.md)); unconfigured,
  the body is the single `body` property. See the
  [Obsidian vault guide](../guides/obsidian-vault.md).
- **`.cl` bundle** — the whole store compressed into one file
  ([ADR-0074](../adr/0074-single-file-bundle-vfs.md)). Any path ending in
  `.cl` opens as a bundle; clone into one to ship a self-contained database.

## Selecting a form

```
# an empty directory becomes that codec's store
cypherlite --snapshot-format markdown --database ./my-vault "CREATE (:Person {name:'Ada'})"

# environment variable, same choice
CYPHERLITE_SNAPSHOT_FORMAT=markdown cypherlite --database ./my-vault "RETURN 1"

# an existing directory keeps the codec it was created with; a mismatched
# --snapshot-format is an error

# copy a database into another form
cypherlite clone --to-snapshot-format markdown ./friends ./friends-vault
```

`--snapshot-format` (or `CYPHERLITE_SNAPSHOT_FORMAT`) selects the codec for
an **empty** directory only; existing stores keep their recorded codec.
`clone --to-snapshot-format json|parquet|markdown` transcodes into a fresh
copy — the source is never written. `:memory:` keeps its in-process form
either way.

One codec per directory: mixing forms' files is an error, as is opening a
directory whose files name a different codec than requested.
