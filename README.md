<!--
SPDX-FileCopyrightText: Silex Data Solutions
SPDX-License-Identifier: Apache-2.0
-->

# Silex Data Ansible Collections — unified docs

**Site: <https://silexdatateam.github.io/collection-docs/>**

One documentation site for every `silexdata.*` Ansible collection in the
SilexDataTeam org, with a shared index across collections, built the way
docs.ansible.com compiles many collections with `antsibull-docs`.

Each collection keeps its own standalone site (e.g.
<https://silexdatateam.github.io/silexdata.akamai/>), built by the shared
`reusable-docs.yml` from
[`silexdata.collection_skeleton`](https://github.com/SilexDataTeam/silexdata.collection_skeleton/tree/ci).
This site only adds to those; nothing here changes a collection repo.

## How it works

[`build-docs.yml`](.github/workflows/build-docs.yml) runs nightly, on pushes
to `main`, and on demand:

1. **Discover**: list the org's public repos named `silexdata.*`, drop
   archived repos, templates and `silexdata.collection_skeleton`, and keep
   those with a root `galaxy.yml`. Namespace and name come from that file.
   A new collection is picked up by the next run with no change here.
2. **Coverage**: copy each collection's already-published coverage report
   (`<its site>/coverage/`) unchanged, and fill in its Coverage Summary page
   from that report with the skeleton's own `generate_coverage_summary.py`.
   Reports are never combined: each stays in its own collection's folder,
   `collections/<namespace>/<name>/coverage/`, where the collection's
   "Coverage Report" button already points.
3. **Build**: `antsibull-docs sphinx-init` with every collection at once and
   without `--squash-hierarchy`, which gives the shared index and the
   `collections/<namespace>/<name>/` layout. [`docs/index.rst`](docs/index.rst)
   is the site's root page.
4. **Deploy** to GitHub Pages. Pull requests build the site without
   deploying it, and attach it as the `docs-html` artifact for review.

A collection with no published coverage report still appears; its Coverage
Summary page keeps the placeholder it commits, which links to its standalone
site.

## Development

[`selftest.yml`](.github/workflows/selftest.yml) lints the workflows and runs
the step tests. To run them locally:

```sh
actionlint .github/workflows/*.yml
python -m pip install pytest pyyaml
python -m pytest tests
```

The tests run `build-docs.yml`'s decision-making `run:` steps exactly as the
runner would, against fixtures (see [`tests/conftest.py`](tests/conftest.py)).
Those steps take their inputs only through `env:`, never `${{ }}` in the
script, so they can run outside GitHub Actions.

The skeleton's coverage summary script is checked out at `v1`. When the
skeleton cuts `v2`, bump that ref in `build-docs.yml` too.
