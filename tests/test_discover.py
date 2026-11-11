# SPDX-FileCopyrightText: Silex Data Solutions
# SPDX-License-Identifier: Apache-2.0
"""Which org repos the discover step treats as collections, and what it emits."""

import json
import os
import shutil
import textwrap

import pytest

ORG = "SilexDataTeam"
ENV = {"GH_TOKEN": "fake", "ORG": ORG, "EXCLUDE": "silexdata.collection_skeleton"}

# A stand-in for the gh CLI that serves the two API calls the step makes from
# fixture files. The repo listing is filtered through the step's own --jq
# expression with the real jq, so the step's filter is what's under test.
FAKE_GH = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import os, pathlib, subprocess, sys

    args = sys.argv[1:]
    fixtures = pathlib.Path(os.environ["FAKE_GH_FIXTURES"])
    path = next(a for a in args if a.startswith(("orgs/", "repos/")))
    if path.startswith("orgs/"):
        if "type=public" not in path:
            sys.exit("fake gh: the repo listing must ask for type=public")
        jq = args[args.index("--jq") + 1]
        listing = (fixtures / "repos.json").read_text()
        sys.exit(subprocess.run(["jq", "-r", jq], input=listing, text=True).returncode)
    repo = path.split("/")[2]
    if (fixtures / "error" / repo).exists():
        sys.exit("fake gh: HTTP 502: Bad Gateway")
    galaxy = fixtures / "galaxy" / repo
    if not galaxy.exists():
        sys.exit("gh: Not Found (HTTP 404)")
    sys.stdout.write(galaxy.read_text())
    """
)


def repo(name, *, archived=False, template=False, pages=True, branch="main"):
    return {
        "name": name,
        "archived": archived,
        "is_template": template,
        "has_pages": pages,
        "default_branch": branch,
    }


def galaxy(namespace, name):
    return f"---\nnamespace: {namespace}\nname: {name}\nversion: 1.0.0\n"


@pytest.fixture
def discover(step, tmp_path):
    """`discover(repos, galaxies, errors=())` -> StepResult."""

    def run(repos, galaxies, errors=()):
        fixtures = tmp_path / "fixtures"
        (fixtures / "galaxy").mkdir(parents=True)
        (fixtures / "error").mkdir()
        (fixtures / "repos.json").write_text(json.dumps(repos))
        for name, text in galaxies.items():
            (fixtures / "galaxy" / name).write_text(text)
        for name in errors:
            (fixtures / "error" / name).touch()
        bindir = tmp_path / "bin"
        bindir.mkdir()
        (bindir / "gh").write_text(FAKE_GH)
        (bindir / "gh").chmod(0o755)
        return step(
            "build-docs.yml",
            "discover",
            "discover",
            ENV,
            runner={
                "PATH": f"{bindir}:{os.environ['PATH']}",
                "FAKE_GH_FIXTURES": str(fixtures),
            },
        )

    return run


def emitted(result):
    assert result.returncode == 0, result.stdout
    return json.loads(result.outputs["collections"])


@pytest.mark.skipif(not shutil.which("jq"), reason="needs jq, as on the runner")
class TestDiscover:
    def test_emits_each_collection_sorted_with_its_pages_url(self, discover):
        result = discover(
            [repo("silexdata.mysql"), repo("silexdata.akamai", branch="devel")],
            {
                "silexdata.mysql": galaxy("silexdata", "mysql"),
                "silexdata.akamai": galaxy("silexdata", "akamai"),
            },
        )
        assert emitted(result) == [
            {
                "repo": "silexdata.akamai",
                "branch": "devel",
                "namespace": "silexdata",
                "name": "akamai",
                "fqcn": "silexdata.akamai",
                "pages_url": "https://silexdatateam.github.io/silexdata.akamai/",
            },
            {
                "repo": "silexdata.mysql",
                "branch": "main",
                "namespace": "silexdata",
                "name": "mysql",
                "fqcn": "silexdata.mysql",
                "pages_url": "https://silexdatateam.github.io/silexdata.mysql/",
            },
        ]

    def test_namespace_and_name_come_from_galaxy_yml_not_the_repo_name(
        self, discover
    ):
        result = discover(
            [repo("silexdata.legacy_name")],
            {"silexdata.legacy_name": "namespace: 'silexdata'\nname: \"current\"\n"},
        )
        [collection] = emitted(result)
        assert collection["repo"] == "silexdata.legacy_name"
        assert collection["fqcn"] == "silexdata.current"

    def test_only_unarchived_non_template_silexdata_repos_are_candidates(
        self, discover
    ):
        result = discover(
            [
                repo("silexdata.akamai"),
                repo("silexdata.old", archived=True),
                repo("silexdata.template", template=True),
                repo("ansible-demos"),
            ],
            {
                name: galaxy("silexdata", name.split(".")[-1].replace("-", "_"))
                for name in (
                    "silexdata.akamai",
                    "silexdata.old",
                    "silexdata.template",
                    "ansible-demos",
                )
            },
        )
        assert [c["repo"] for c in emitted(result)] == ["silexdata.akamai"]

    def test_skeleton_is_excluded_by_name_even_as_a_collection(self, discover):
        result = discover(
            [repo("silexdata.akamai"), repo("silexdata.collection_skeleton")],
            {
                "silexdata.akamai": galaxy("silexdata", "akamai"),
                "silexdata.collection_skeleton": galaxy("silexdata", "skeleton"),
            },
        )
        assert [c["repo"] for c in emitted(result)] == ["silexdata.akamai"]

    def test_repo_without_root_galaxy_yml_is_skipped_with_a_notice(self, discover):
        result = discover(
            [repo("silexdata.akamai"), repo("silexdata.website")],
            {"silexdata.akamai": galaxy("silexdata", "akamai")},
        )
        assert [c["repo"] for c in emitted(result)] == ["silexdata.akamai"]
        assert any("silexdata.website" in n for n in result.annotations("notice"))

    def test_repo_without_pages_has_no_pages_url(self, discover):
        result = discover(
            [repo("silexdata.akamai", pages=False)],
            {"silexdata.akamai": galaxy("silexdata", "akamai")},
        )
        assert emitted(result)[0]["pages_url"] == ""

    def test_api_error_other_than_404_fails_rather_than_dropping_a_collection(
        self, discover
    ):
        result = discover(
            [repo("silexdata.akamai")],
            {"silexdata.akamai": galaxy("silexdata", "akamai")},
            errors=["silexdata.akamai"],
        )
        assert result.returncode != 0
        assert result.annotations("error")
        assert "collections" not in result.outputs

    @pytest.mark.parametrize(
        "text",
        ["namespace: silexdata\n", "namespace: Silex-Data\nname: akamai\n", "---\n"],
    )
    def test_invalid_galaxy_yml_fails(self, discover, text):
        result = discover([repo("silexdata.akamai")], {"silexdata.akamai": text})
        assert result.returncode != 0
        assert result.annotations("error")

    def test_two_repos_declaring_the_same_collection_fail(self, discover):
        result = discover(
            [repo("silexdata.akamai"), repo("silexdata.akamai_fork")],
            {
                "silexdata.akamai": galaxy("silexdata", "akamai"),
                "silexdata.akamai_fork": galaxy("silexdata", "akamai"),
            },
        )
        assert result.returncode != 0
        assert any("silexdata.akamai" in e for e in result.annotations("error"))

    def test_finding_no_collection_fails(self, discover):
        result = discover([repo("silexdata.website")], {})
        assert result.returncode != 0
        assert result.annotations("error")
