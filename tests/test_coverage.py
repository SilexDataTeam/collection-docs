# SPDX-FileCopyrightText: Silex Data Solutions
# SPDX-License-Identifier: Apache-2.0
"""Each collection's coverage report: copied unchanged, kept with its collection."""

import functools
import http.server
import json
import shutil
import socket
import threading

import pytest

PLACEHOLDER = "Coverage Summary\n================\n\nThe generation step didn't run.\n"

# Stands in for the skeleton's generate_coverage_summary.py: the test checks
# the step calls it with the right report and page, not what the script writes.
FAKE_SUMMARY = (
    "import pathlib, sys\n"
    "pathlib.Path(sys.argv[2]).write_text('summary of ' + sys.argv[1] + '\\n')\n"
)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def pages(tmp_path):
    """A local stand-in for github.io, serving <repo>/coverage/ trees."""
    root = tmp_path / "pages"
    root.mkdir()
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(QuietHandler, directory=root)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield root, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def publish_report(root, repo, label):
    report = root / repo / "coverage"
    report.mkdir(parents=True)
    (report / "index.html").write_text(
        f'<link rel="stylesheet" href="style_cb.css">'
        f'<a href="z_abc_module_py.html">module.py</a>{label}'
        # Leads out of /coverage/, which --no-parent must not follow.
        f'<a href="../plugin_module.html">docs</a>'
    )
    (report / "z_abc_module_py.html").write_text(f"lines of {label}")
    (report / "style_cb.css").write_text("body {}")
    # The rest of the collection's site, which must not end up in the copy.
    (root / repo / "plugin_module.html").write_text("plugin docs")
    return report


def closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir()
    summary = tmp_path / "generate_coverage_summary.py"
    summary.write_text(FAKE_SUMMARY)
    return ws, runner_temp, summary


def collection(ws, name, *, placeholder=True):
    root = ws / "ansible_collections" / "silexdata" / name
    rst = root / "docs" / "docsite" / "rst"
    rst.mkdir(parents=True)
    if placeholder:
        (rst / "coverage-report.rst").write_text(PLACEHOLDER)
    return rst / "coverage-report.rst"


def entry(name, pages_url):
    return {
        "repo": f"silexdata.{name}",
        "branch": "main",
        "namespace": "silexdata",
        "name": name,
        "fqcn": f"silexdata.{name}",
        "pages_url": pages_url,
    }


@pytest.fixture
def copy_reports(step, workspace):
    ws, runner_temp, summary = workspace

    def run(entries):
        return step(
            "build-docs.yml",
            "docs",
            "coverage",
            {"COLLECTIONS": json.dumps(entries), "SUMMARY_SCRIPT": str(summary)},
            cwd=ws,
            runner={"RUNNER_TEMP": str(runner_temp)},
        )

    return run


@pytest.mark.skipif(not shutil.which("wget") or not shutil.which("jq"),
                    reason="needs wget and jq, as on the runner")
class TestCopyReports:
    def test_each_report_is_copied_whole_and_kept_with_its_collection(
        self, copy_reports, pages, workspace
    ):
        root, base = pages
        ws, runner_temp, _ = workspace
        published = {
            name: publish_report(root, f"silexdata.{name}", name)
            for name in ("akamai", "mysql")
        }
        rsts = {name: collection(ws, name) for name in published}

        result = copy_reports(
            [entry(name, f"{base}/silexdata.{name}/") for name in published]
        )

        assert result.returncode == 0, result.stdout
        for name, report in published.items():
            copy = runner_temp / "coverage" / "silexdata" / name
            assert sorted(p.name for p in copy.iterdir()) == sorted(
                p.name for p in report.iterdir()
            )
            for page in report.iterdir():
                assert (copy / page.name).read_bytes() == page.read_bytes()
            assert rsts[name].read_text() == f"summary of {copy}/index.html\n"

    def test_nothing_published_keeps_the_placeholder_with_a_notice(
        self, copy_reports, pages, workspace
    ):
        _, base = pages
        ws, runner_temp, _ = workspace
        rst = collection(ws, "akamai")

        result = copy_reports([entry("akamai", f"{base}/silexdata.akamai/")])

        assert result.returncode == 0, result.stdout
        assert rst.read_text() == PLACEHOLDER
        assert not (runner_temp / "coverage" / "silexdata" / "akamai").exists()
        assert any("Nothing is published" in n for n in result.annotations("notice"))
        assert not result.annotations("warning")

    def test_no_pages_site_keeps_the_placeholder(self, copy_reports, workspace):
        ws, runner_temp, _ = workspace
        rst = collection(ws, "akamai")

        result = copy_reports([entry("akamai", "")])

        assert result.returncode == 0, result.stdout
        assert rst.read_text() == PLACEHOLDER
        assert not (runner_temp / "coverage").exists()
        assert result.annotations("notice")

    def test_failing_to_fetch_warns_and_keeps_the_placeholder(
        self, copy_reports, workspace
    ):
        ws, runner_temp, _ = workspace
        rst = collection(ws, "akamai")

        result = copy_reports(
            [entry("akamai", f"http://127.0.0.1:{closed_port()}/silexdata.akamai/")]
        )

        assert result.returncode == 0, result.stdout
        assert rst.read_text() == PLACEHOLDER
        assert not (runner_temp / "coverage" / "silexdata" / "akamai").exists()
        assert result.annotations("warning")

    def test_collection_without_a_summary_page_still_gets_its_report(
        self, copy_reports, pages, workspace
    ):
        root, base = pages
        ws, runner_temp, _ = workspace
        publish_report(root, "silexdata.akamai", "akamai")
        rst = collection(ws, "akamai", placeholder=False)

        result = copy_reports([entry("akamai", f"{base}/silexdata.akamai/")])

        assert result.returncode == 0, result.stdout
        assert not rst.exists()
        copy = runner_temp / "coverage" / "silexdata" / "akamai"
        assert (copy / "index.html").exists()


@pytest.fixture
def place(step, workspace):
    ws, runner_temp, _ = workspace

    def run():
        return step(
            "build-docs.yml",
            "docs",
            "place",
            {},
            cwd=ws,
            runner={"RUNNER_TEMP": str(runner_temp)},
        )

    return run


def built_site(ws):
    html = ws / "docsbuild" / "build" / "html"
    for name in ("akamai", "mysql"):
        (html / "collections" / "silexdata" / name).mkdir(parents=True)
        (html / "collections" / "silexdata" / name / "index.html").write_text(name)
    return html


class TestPlaceReports:
    def test_each_report_lands_in_its_own_collections_coverage_folder(
        self, place, workspace
    ):
        ws, runner_temp, _ = workspace
        html = built_site(ws)
        for name in ("akamai", "mysql"):
            copy = runner_temp / "coverage" / "silexdata" / name
            copy.mkdir(parents=True)
            (copy / "index.html").write_text(f"report of {name}")

        result = place()

        assert result.returncode == 0, result.stdout
        for name in ("akamai", "mysql"):
            target = html / "collections" / "silexdata" / name / "coverage"
            assert [p.name for p in target.iterdir()] == ["index.html"]
            assert (target / "index.html").read_text() == f"report of {name}"
        assert not (html / "coverage").exists()

    def test_no_reports_is_a_no_op(self, place, workspace):
        ws, _, _ = workspace
        html = built_site(ws)

        result = place()

        assert result.returncode == 0, result.stdout
        assert not list(html.glob("collections/*/*/coverage"))

    def test_refuses_to_overwrite_a_built_coverage_folder(self, place, workspace):
        ws, runner_temp, _ = workspace
        html = built_site(ws)
        (html / "collections" / "silexdata" / "akamai" / "coverage").mkdir()
        copy = runner_temp / "coverage" / "silexdata" / "akamai"
        copy.mkdir(parents=True)
        (copy / "index.html").write_text("report")

        result = place()

        assert result.returncode != 0
        assert result.annotations("error")
