---
name: quill-publish
description: Release a Quill and put it in the Quill Catalog — versions, tags, the release workflow, the README's "What it adds" table, and submitting the repository. Use when the person wants others (or their own server) to install it from the catalog.
---

# Publishing a Quill

1. Everything passes: `cm quill check`, `cm quill test`, `cm quill test --sandbox`.
2. README.md's "What it adds" table is true (`cm quill check` prints what it adds).
3. Bump `version` in quill.toml (major.minor.patch): a new field or action is
   minor; a change that breaks old records or removes something is major.
4. Commit, tag and push: `git tag v1.2.0 && git push --tags`. The release
   workflow checks the tag matches quill.toml, tests again in the sandbox,
   and publishes the release.
   With no machine to push a tag from, run the **release** workflow from
   the Actions tab instead: it checks and tests main, tags it with
   quill.toml's version, and publishes the release.
5. The first release of a Quill of your own: open a pull request on
   Cloudmorrow/quill-catalog adding one block to catalog.toml (its pull
   request template carries it):
   ```toml
   [[quills]]
   id = "fleet"
   name = "Fleet"
   summary = "The vans, when each was last serviced, and who drives it."
   repo = "https://github.com/you/quill-fleet"
   ref = "v1.2.0"
   category = "business"
   publisher = "you"
   ```
   Every release after that needs no pull request by hand: within fifteen
   minutes the catalog's **releases** workflow opens one moving your `ref`
   to it, with the check result and the install sheet in its body, and
   Cloudmorrow merges it or says why not. Opening it yourself is fine too;
   the result is the same. Until it is merged, servers install the release
   the catalog pins. A Quill in github.com/Cloudmorrow/quill-* goes straight
   in: the workflow commits its release to the catalog.

Start a Quill with GitHub's "Use this template" on Cloudmorrow/quill-template
(not a fork), or `cm quill new <id>`. The SDK is a dependency
(`pyproject.toml`, and `sdk = "1"` in the manifest), so a Quill made from an
older template gets new SDK features by updating the dependency.

A Quill that began as somebody's own on their server (`cm quill dev` as a
person who is not an administrator, or their assistant's `quill_dev_install`)
gets this shape with `cm quill export <id>`: the folder, with tests, this
CLAUDE.md, the workflows and a pyproject written in around it, and — by
choice, `--dataset` — their records of its own datamodels as per-owner
datasets. Then the steps above.
