"""Log parsers used by the Longtail-SWE tasks (install_config.log_parser).

Pruned from the full parser collection to the parsers referenced by the task files in
data/ and their helpers.
"""
import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from lib.constants import TestStatus

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

OCAML_STATUS_PRECEDENCE = {
    TestStatus.PASSED.value: 0,
    TestStatus.SKIPPED.value: 1,
    TestStatus.FAILED.value: 2,
    TestStatus.ERROR.value: 3,
}

def ansi_escape(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return ANSI_ESCAPE_RE.sub("", text)

def parse_log_elixir(log: str) -> dict[str, str]:
    """Parse ExUnit output and return {full_test_name: status}.

    Rules:
      * Lines like: "* test <name> [L#42]" or with timing "(12.3ms)" -> PASSED (tentative)
      * Lines like: "* test <name> (skipped) [L#42]" -> SKIPPED
      * Failure headers: "1) test <name> (<Module>)" -> FAILED (overrides prior PASS)
    """
    results: dict[str, str] = {}

    # Regexes
    skipped_re = re.compile(r"^\*\s+test\s+(.*?)\s+\(skipped\)\s+\[L#\d+\]$")
    passed_timed_re = re.compile(
        r"^\*\s+test\s+(.*?)\s+\([0-9]+(?:\.[0-9]+)?ms\)\s+\[L#\d+\]$"
    )
    passed_basic_re = re.compile(r"^\*\s+test\s+(.*?)\s+\[L#\d+\]$")
    failure_header_re = re.compile(r"^\d+\)\s+test\s+(.*?)\s+\([^)]+\)$")

    for raw in log.splitlines():
        line = raw.strip()
        if not line:
            continue
        if m := skipped_re.match(line):
            results[m.group(1)] = TestStatus.SKIPPED.value
            continue
        if m := failure_header_re.match(line):
            results[m.group(1)] = TestStatus.FAILED.value
            continue
        if m := passed_timed_re.match(line):
            results.setdefault(m.group(1), TestStatus.PASSED.value)
            continue
        if m := passed_basic_re.match(line):
            results.setdefault(m.group(1), TestStatus.PASSED.value)
            continue
    return results

ERLANG_EUNIT_MODULE_RE = re.compile(
    r"^\s*module\s+'?(?P<module>[A-Za-z][A-Za-z0-9_@]*)'?\s*$"
)

ERLANG_EUNIT_CASE_RE = re.compile(
    r"^\s*(?:(?P<module>'?[A-Za-z][A-Za-z0-9_@]*'?)\s*:\s*)?"
    # EUnit generator names are valid test identities but can begin with a
    # hyphen and contain slash/parenthesized source context, e.g.
    # ``suite: -generator/0-fun-0- (file.erl)...*failed*``.  Keep the entire
    # emitted name so before/after matching remains exact.
    r"(?P<case>.+?)\s*\.\.\."
    # EUnit optionally inserts a per-case elapsed-time token before the
    # outcome, e.g. ``case...[0.001 s] ok``.  It is reporting metadata rather
    # than part of the test identity and must not make an otherwise named pass
    # disappear from the result set.
    r"(?:\s*\[[0-9]+(?:\.[0-9]+)?\s*s\])?\s*"
    r"(?P<outcome>ok|skipped|\*failed\*|\*error\*|\*timed out\*)\s*$",
    flags=re.IGNORECASE,
)

ERLANG_EUNIT_PENDING_RE = re.compile(
    r"^\s*(?:(?P<module>'?[A-Za-z][A-Za-z0-9_@]*'?)\s*:\s*)?"
    r"(?P<case>.+?)\s*\.\.\..*$"
)

ERLANG_EUNIT_LATE_OUTCOME_RE = re.compile(
    r"^(?:\[[0-9]+(?:\.[0-9]+)?\s*s\]\s*)?"
    r"(?P<outcome>ok|skipped|\*failed\*|\*error\*|\*timed out\*)\s*$",
    flags=re.IGNORECASE,
)

ERLANG_CT_CASE_RE = re.compile(
    r"^=case\s+(?P<module>[A-Za-z][A-Za-z0-9_@]*)\s*:\s*"
    r"(?P<case>[A-Za-z][A-Za-z0-9_@']*)\s*$"
)

ERLANG_CT_RESULT_RE = re.compile(
    r"^=result\s+(?P<outcome>ok|skipped|failed|error)\b", flags=re.IGNORECASE
)

ERLANG_CT_VERBOSE_CASE_RE = re.compile(
    r"^%%%\s+(?P<module>[A-Za-z][A-Za-z0-9_@]*)\s+==>\s+"
    r"(?P<group>(?:(?:[A-Za-z][A-Za-z0-9_@']*)\.)*)"
    r"(?P<case>[A-Za-z][A-Za-z0-9_@']*)\s*:\s*"
    r"(?P<outcome>ok|passed|skipped|failed|error)\s*$",
    flags=re.IGNORECASE,
)

ERLANG_CT_SCREEN_SUITE_RE = re.compile(
    r"^==\s+(?P<module>[A-Za-z][A-Za-z0-9_@]*_SUITE)\s+==$"
)

ERLANG_CT_SCREEN_PASS_RE = re.compile(
    r"\x1b\[[0-9;]*32m(?P<case>[A-Za-z][A-Za-z0-9_@']*)"
    r"\x1b\[[0-9;]*m\s*\([0-9:.]+\)"
)

ERLANG_CT_SCREEN_PLAIN_PASS_RE = re.compile(
    r"^(?P<case>[A-Za-z][A-Za-z0-9_@']*)\s*\([0-9:.]+\)$"
)

ERLANG_CT_SCREEN_FAILURE_RE = re.compile(
    r"\x1b\[[0-9;]*31m(?P<module>[A-Za-z][A-Za-z0-9_@]*)\s*>\s*"
    r"(?P<case>[A-Za-z][A-Za-z0-9_@']*)"
)

ERLANG_CT_SCREEN_CASE_RE = re.compile(
    r"^(?P<module>[A-Za-z][A-Za-z0-9_@]*)\s*>\s*"
    r"(?P<case>[A-Za-z][A-Za-z0-9_@']*)\s*$"
)

ERLANG_ATOMVM_CASE_RE = re.compile(
    r"^(?P<case>[A-Za-z][A-Za-z0-9_@-]*)\s*:\s*(?P<outcome>ok|failed)\s*$",
    flags=re.IGNORECASE,
)

ERLANG_STATUS_PRECEDENCE = {
    TestStatus.PASSED.value: 0,
    TestStatus.SKIPPED.value: 1,
    TestStatus.FAILED.value: 2,
    TestStatus.ERROR.value: 3,
}

def _erlang_status(outcome: str) -> str:
    normalized = outcome.lower()
    if normalized in {"ok", "passed"}:
        return TestStatus.PASSED.value
    if normalized == "skipped":
        return TestStatus.SKIPPED.value
    if "error" in normalized or "timed out" in normalized:
        return TestStatus.ERROR.value
    return TestStatus.FAILED.value

def _set_erlang_status(results: dict[str, str], name: str, status: str) -> None:
    current = results.get(name)
    if current is None or ERLANG_STATUS_PRECEDENCE[status] >= ERLANG_STATUS_PRECEDENCE[current]:
        results[name] = status

def parse_log_erlang(log: str) -> dict[str, str]:
    """Parse named EUnit and Common Test cases without deriving aggregate buckets."""
    results: dict[str, str] = {}
    current_module = ""
    pending_eunit_case = ""
    pending_ct_case = ""
    current_ct_screen_module = ""
    pending_ct_screen_case = ""
    for raw in log.splitlines():
        line = ansi_escape(raw).strip()
        if not line:
            continue
        if match := ERLANG_CT_SCREEN_SUITE_RE.match(line):
            current_ct_screen_module = match.group("module")
            pending_ct_screen_case = ""
            continue
        if match := ERLANG_CT_SCREEN_FAILURE_RE.search(raw):
            name = f"{match.group('module')}:{match.group('case').strip(chr(39))}"
            _set_erlang_status(results, name, TestStatus.ERROR.value)
            pending_ct_screen_case = ""
            continue
        if match := ERLANG_CT_SCREEN_PASS_RE.search(raw):
            if current_ct_screen_module:
                name = f"{current_ct_screen_module}:{match.group('case').strip(chr(39))}"
                _set_erlang_status(results, name, TestStatus.PASSED.value)
            continue
        if match := ERLANG_CT_SCREEN_PLAIN_PASS_RE.match(line):
            if current_ct_screen_module:
                name = f"{current_ct_screen_module}:{match.group('case').strip(chr(39))}"
                _set_erlang_status(results, name, TestStatus.PASSED.value)
            continue
        if match := ERLANG_CT_SCREEN_CASE_RE.match(line):
            # A yellow screen header can be a skipped group or a testcase whose
            # init hook failed.  Do not label it until the following structured
            # result supplies evidence; this avoids turning benign groups into
            # failures while retaining Common Test's ``{skip, {failed, ...}}``.
            pending_ct_screen_case = f"{match.group('module')}:{match.group('case').strip(chr(39))}"
            continue
        if pending_ct_screen_case and ("{failed," in line or "{error," in line):
            _set_erlang_status(results, pending_ct_screen_case, TestStatus.ERROR.value)
            pending_ct_screen_case = ""
            continue
        if match := ERLANG_EUNIT_MODULE_RE.match(line):
            current_module = match.group("module")
            pending_eunit_case = ""
            continue
        if match := ERLANG_CT_CASE_RE.match(line):
            pending_ct_case = f"{match.group('module')}:{match.group('case')}"
            continue
        if match := ERLANG_CT_RESULT_RE.match(line):
            if pending_ct_case:
                _set_erlang_status(results, pending_ct_case, _erlang_status(match.group("outcome")))
            pending_ct_case = ""
            continue
        if match := ERLANG_CT_VERBOSE_CASE_RE.match(line):
            module = match.group("module")
            case = match.group("case").strip(chr(39))
            status = _erlang_status(match.group("outcome"))
            # Common Test suite.log records omit a group prefix; preserve that
            # alias for parity with `=case`, then additionally retain the
            # literal verbose reporter identity when a group prefix is present.
            _set_erlang_status(results, f"{module}:{case}", status)
            group = match.group("group").rstrip(".")
            if group:
                _set_erlang_status(results, f"{module}:{group}.{case}", status)
            continue
        if match := ERLANG_ATOMVM_CASE_RE.match(line):
            _set_erlang_status(results, match.group("case"), _erlang_status(match.group("outcome")))
            continue
        if match := ERLANG_EUNIT_CASE_RE.match(line):
            module = (match.group("module") or current_module).strip("'")
            name = match.group("case").strip("'")
            full_name = f"{module}:{name}" if module else name
            _set_erlang_status(results, full_name, _erlang_status(match.group("outcome")))
            pending_eunit_case = ""
            continue
        if pending_eunit_case and (match := ERLANG_EUNIT_LATE_OUTCOME_RE.match(line)):
            _set_erlang_status(results, pending_eunit_case, _erlang_status(match.group("outcome")))
            pending_eunit_case = ""
            continue
        if match := ERLANG_EUNIT_PENDING_RE.match(line):
            module = (match.group("module") or current_module).strip("'")
            name = match.group("case").strip("'")
            pending_eunit_case = f"{module}:{name}" if module else name
    return results

def parse_log_gradle_custom(log: str) -> dict[str, str]:
    """
    Parser for test logs generated with 'gradle test'. Assumes that the
    pre-install script to update the gradle config has run.
    """
    test_status_map = {}

    pattern = r"^([^>].+)\s+(PASSED|FAILED)$"

    for line in log.split("\n"):
        match = re.match(pattern, line.strip())
        if match:
            test_name, status = match.groups()
            if status == "PASSED":
                test_status_map[test_name] = TestStatus.PASSED.value
            elif status == "FAILED":
                test_status_map[test_name] = TestStatus.FAILED.value

    return test_status_map

def parse_log_tap(log: str) -> dict[str, str]:
    """
    Parser for test logs generated with TAP

    Args:
        log (str): log content
    Returns:
        dict: test case to test status mapping
    """
    test_status_map = {}

    # Pattern to match TAP result lines
    pattern = r"^(ok|not ok) (\d+) (.+)$"

    for line in log.split("\n"):
        match = re.match(pattern, line.strip())
        if match:
            status, _test_number, test_name = match.groups()
            if status == "ok":
                test_status_map[test_name] = TestStatus.PASSED.value
            elif status == "not ok":
                test_status_map[test_name] = TestStatus.FAILED.value

    return test_status_map

def parse_lue_nvim(log: str) -> dict[str, str]:
    results: dict[str, str] = {}

    # Precompiled regexes
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    success_re = re.compile(r"^Success\s*\|\|\s*(.+?)\s*$")
    fail_re = re.compile(r"^(?:Fail|Failed)\s*\|\|\s*(.+?)\s*$")
    skip_re = re.compile(r"^(?:Skip|Skipped)\s*\|\|\s*(.+?)\s*$", re.IGNORECASE)

    for raw in log.splitlines():
        if not raw.strip():
            continue
        # Remove ANSI escapes then trim whitespace & trailing tabs
        line = ansi_re.sub("", raw).rstrip()

        # Ignore summary counters (they have a colon right after keyword and no '||')
        if ":" in line.split("\t")[0] and "||" not in line:
            # e.g., "Success:" or "Failed :" or "Errors :"
            # ensure we don't skip real test lines which always have '||'
            continue

        # Match order: fail overrides, skip, success (success uses setdefault)
        m_fail = fail_re.match(line)
        if m_fail:
            name = m_fail.group(1).strip()
            results[name] = TestStatus.FAILED.value
            continue

        m_skip = skip_re.match(line)
        if m_skip:
            name = m_skip.group(1).strip()
            # Only set if not already failed
            results.setdefault(name, TestStatus.SKIPPED.value)
            continue

        m_success = success_re.match(line)
        if m_success:
            name = m_success.group(1).strip()
            # Don't overwrite FAIL (or SKIPPED) with PASS
            results.setdefault(name, TestStatus.PASSED.value)
            continue

    return results

def parse_log_junit_strict(log: str) -> dict[str, str]:
    """Parse test cases only from complete, well-formed JUnit suites.

    Unlike ``parse_log_junit``, this opt-in parser never treats an unmatched
    ``<testcase>`` fragment as a passing test. This prevents shell-command
    echoes containing XML-like regular expressions from becoming test IDs.
    """
    results: dict[str, str] = {}
    suite_open_re = re.compile(r"<testsuite\b[^>]*>", re.DOTALL)
    suite_close_re = re.compile(r"</testsuite\s*>", re.DOTALL)

    for open_match in suite_open_re.finditer(log):
        close_match = suite_close_re.search(log, open_match.end())
        if close_match is None:
            continue
        xml_fragment = log[open_match.start() : close_match.end()]
        try:
            suite = ET.fromstring(xml_fragment)
        except ET.ParseError:
            continue

        for testcase in suite.iter():
            if testcase.tag.rsplit("}", 1)[-1] != "testcase":
                continue
            name = testcase.attrib.get("name")
            if not name:
                continue
            classname = testcase.attrib.get("classname", "")
            full_name = f"{classname} {name}".strip() if classname else name
            child_tags = {child.tag.rsplit("}", 1)[-1] for child in testcase}
            if "failure" in child_tags:
                status = TestStatus.FAILED.value
            elif "error" in child_tags:
                status = TestStatus.ERROR.value
            elif "skipped" in child_tags:
                status = TestStatus.SKIPPED.value
            else:
                status = TestStatus.PASSED.value
            results[full_name] = status

    return results

def parse_log_haskell_v2(log: str) -> dict[str, str]:  # noqa: C901, PLR0912, PLR0915
    lines = re.sub(r"\x1b[78]", "", ansi_escape(log)).replace("\r", "\n").splitlines()
    if "___TESTS_SECTION___" in lines:
        lines = lines[lines.index("___TESTS_SECTION___") + 1 :]
    for index, line in enumerate(lines):
        if line.strip() == "___TESTS_SECTION_END___":
            lines = lines[:index]
            break
    suite_starts = [
        index
        for index, line in enumerate(lines)
        if line.startswith("Test suite ") and ": RUNNING..." in line
    ]
    tasty_result = re.compile(
        r"^(?P<name>.+?):\s*(?P<status>OK|PASS|FAIL|ERROR|SKIP|PENDING)(?:\s|$)"
    )
    if any(
        tasty_result.match(line.strip())
        for line in lines
        if not line.startswith("Test suite ")
    ):
        tasty_results: dict[str, str] = {}
        groups: list[tuple[int, str]] = []
        leaf_indent: int | None = None
        statuses = {
            "OK": TestStatus.PASSED.value,
            "PASS": TestStatus.PASSED.value,
            "FAIL": TestStatus.FAILED.value,
            "ERROR": TestStatus.ERROR.value,
            "SKIP": TestStatus.SKIPPED.value,
            "PENDING": TestStatus.SKIPPED.value,
        }
        precedence = {
            TestStatus.PASSED.value: 0,
            TestStatus.SKIPPED.value: 1,
            TestStatus.FAILED.value: 2,
            TestStatus.ERROR.value: 3,
        }
        collecting = not suite_starts
        for line in lines:
            name = line.strip()
            if not name:
                continue
            if name.startswith("Test suite "):
                collecting = ": RUNNING..." in name
                groups.clear()
                leaf_indent = None
                continue
            if not collecting:
                continue
            if re.match(
                r"(?:All \d+ tests? passed|\d+ out of \d+ tests? failed)\b", name
            ):
                collecting = False
                continue
            indent = len(line) - len(line.lstrip(" "))
            if leaf_indent is not None and indent > leaf_indent:
                continue
            while groups and groups[-1][0] >= indent:
                groups.pop()
            if match := tasty_result.match(name):
                full_name = ".".join(
                    [group for _, group in groups] + [match.group("name").strip()]
                )
                status = statuses[match.group("status")]
                if (
                    full_name not in tasty_results
                    or precedence[status] > precedence[tasty_results[full_name]]
                ):
                    tasty_results[full_name] = status
                leaf_indent = indent
            else:
                groups.append((indent, name))
                leaf_indent = None
        return tasty_results
    if len(suite_starts) > 1:
        combined: dict[str, str] = {}
        precedence = {
            TestStatus.PASSED.value: 0,
            TestStatus.SKIPPED.value: 1,
            TestStatus.FAILED.value: 2,
            TestStatus.ERROR.value: 3,
        }
        for start, end in zip(
            suite_starts, [*suite_starts[1:], len(lines)], strict=True
        ):
            for name, status in parse_log_haskell_v2(
                "\n".join(lines[start:end])
            ).items():
                if (
                    name not in combined
                    or precedence[status] > precedence[combined[name]]
                ):
                    combined[name] = status
        return combined

    # 1) Collect explicit failures from the Failures: section
    failed_fullnames = set()
    failures_idx = None
    for idx, ln in enumerate(lines):
        if ln.strip() == "Failures:":
            failures_idx = idx
            break

    if failures_idx is not None:
        failure_header_re = re.compile(r"^\s*\d+\)\s+(.*)$")
        i = failures_idx + 1
        while i < len(lines):
            s = lines[i].strip()
            if not s:
                i += 1
                continue
            if s.startswith(
                (
                    "To rerun use:",
                    "Randomized with seed",
                    "Finished in ",
                    "Test suite ",
                )
            ):
                break
            m = failure_header_re.match(s)
            if m:
                header = m.group(1).strip()
                parts = [p.strip() for p in header.split(",")]
                if parts:
                    full = ".".join([parts[0]] + parts[1:])
                    failed_fullnames.add(full)
            i += 1

    # 2) Find the tree section (between RUNNING and Failures/summary)
    start_idx = None
    for idx, ln in enumerate(lines):
        if ln.startswith("Test suite ") and ": RUNNING..." in ln:
            start_idx = idx + 1
            break
    if start_idx is None:
        # Fallback heuristic for when RUNNING marker isn't present
        for idx, ln in enumerate(lines):
            if (
                ln
                and not ln.startswith(" ")
                and "." in ln
                and not any(
                    k in ln
                    for k in (
                        "Downloading",
                        "Building",
                        "Installing",
                        "Completed",
                        "Starting",
                        "Preprocessing",
                        "Configuring",
                        "Linking",
                        "Resolving dependencies",
                        "Build profile",
                        "In order, the following will be built",
                        "Error:",
                        "Test suite ",
                        "Running ",
                    )
                )
            ):
                start_idx = idx
                break
    end_idx = failures_idx if failures_idx is not None else len(lines)
    for index in range(start_idx or 0, end_idx):
        if lines[index].strip().startswith(
            ("Randomized with seed", "Finished in ", "Test suite ")
        ) or re.fullmatch(
            r"\d+ examples?, \d+ failures?(?:,.*)?", lines[index].strip()
        ):
            end_idx = index
            break
    if start_idx is None:
        return {name: TestStatus.FAILED.value for name in failed_fullnames}

    def is_info(text: str) -> bool:
        return text == "Golden and Actual output didn't change"

    def leading_spaces(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    # Helper to peek next significant tree line (skips blanks and info lines)
    def next_sig_index(k: int):
        m = k + 1
        while m < end_idx:
            t = lines[m].rstrip("\n")
            s = t.strip()
            if not s or is_info(s):
                m += 1
                continue
            return m
        return None

    results: dict[str, str] = {}
    stack: list[str] = []

    i = start_idx or 0
    while i < end_idx:
        raw = lines[i].rstrip("\n")
        s = raw.strip()
        if not s or is_info(s):
            i += 1
            continue

        # Compute level by indentation (2 spaces per level in Hspec output)
        indent = leading_spaces(raw)
        level = indent // 2

        # Normalize leaf name and detect inline status (FAILED/PENDING)
        status_hint = None
        m_fail = re.match(r"^(.*?)\s+FAILED\s*\[\d+\]$", s)
        m_pending = re.match(r"^(.*?)\s+(?:PENDING|SKIPPED)\b.*$", s, re.IGNORECASE)
        if m_fail:
            name_core = m_fail.group(1).strip()
            status_hint = TestStatus.FAILED.value
        elif m_pending:
            name_core = m_pending.group(1).strip()
            status_hint = TestStatus.SKIPPED.value
        else:
            name_core = s

        # Update hierarchy stack at this level
        if level < len(stack):
            stack[level] = name_core
            del stack[level + 1 :]
        elif level == len(stack):
            stack.append(name_core)
        else:
            while len(stack) < level:
                stack.append("")
            stack.append(name_core)

        # Determine if this is a leaf example: next significant line not deeper
        j = next_sig_index(i)
        is_leaf = True
        if j is not None:
            next_indent = leading_spaces(lines[j])
            if next_indent > indent:
                # Child group/example exists; current is a container
                is_leaf = False

        if is_leaf:
            full_name = ".".join([seg for seg in stack if seg])
            if status_hint == TestStatus.FAILED.value:
                results[full_name] = TestStatus.FAILED.value
            elif status_hint == TestStatus.SKIPPED.value:
                results[full_name] = TestStatus.SKIPPED.value
            else:
                results[full_name] = TestStatus.PASSED.value

        i += 1

    # Override with failures discovered in the failures section
    for full in failed_fullnames:
        results[full] = TestStatus.FAILED.value

    return results

def parse_log_julia(log: str) -> dict[str, str]:  # noqa: PLR0912, PLR0915
    """Parse Julia Test output and return {test_name: status}.

    Parses the test summary table that appears at the end of Julia test runs.
    Format: "Test Summary: | Pass Fail Error Broken Total Time"

    Rules:
      * If a test has Error count > 0 -> ERROR
      * If a test has Fail count > 0 -> FAILED
      * Otherwise (only Pass or no failures) -> PASSED
      * Priority: ERROR > FAILED > PASSED
      * Tests can be hierarchical (indented with spaces)
    """
    results: dict[str, str] = {}

    # Regex to match test summary lines that look like "  name  | numbers ..."
    test_line_re = re.compile(r"^(\s*)(.+?)\s+\|(.+)$")

    in_summary = False
    has_pass_column = False
    has_fail_column = False
    has_error_column = False

    for raw in log.splitlines():
        # Detect start of test summary section and column headers
        if "Test Summary:" in raw:
            in_summary = True
            header_part = raw.split("|", 1)[1] if "|" in raw else raw
            has_pass_column = "Pass" in header_part
            has_fail_column = "Fail" in header_part
            has_error_column = "Error" in header_part
            continue

        if not in_summary:
            continue

        # Match test result lines
        if match := test_line_re.match(raw):
            test_name = match.group(2).strip()
            columns_text = match.group(3)

            # Parse columns - they appear in order: Pass, Fail, Error, Broken, Total, Time
            # Split by whitespace and filter out time values
            parts = columns_text.split()

            # Filter out time values (contain 's', 'm', or ':')
            numeric_parts = [p for p in parts if p.isdigit()]

            if len(numeric_parts) < 2:
                continue

            # The last numeric value is Total
            total = int(numeric_parts[-1])

            # Determine status based on what failures are present
            status = TestStatus.PASSED.value

            if len(numeric_parts) == 2:
                first_num = int(numeric_parts[0])
                leading_spaces = len(columns_text) - len(columns_text.lstrip())
                missing_pass_value = not has_pass_column or leading_spaces >= 10
                if missing_pass_value and has_error_column:
                    status = TestStatus.ERROR.value
                elif missing_pass_value and has_fail_column:
                    status = TestStatus.FAILED.value
                elif first_num != total:
                    status = TestStatus.ERROR.value

            elif len(numeric_parts) == 3:
                # Three numbers: Could be [Pass, Fail, Total] OR [Pass, Error, Total]
                # Depends on which columns are present in the header
                middle_count = int(numeric_parts[1])

                if middle_count > 0:
                    if has_error_column and not has_fail_column:
                        # Header has Error column but no Fail column: [Pass, Error, Total]
                        status = TestStatus.ERROR.value
                    elif has_fail_column and not has_error_column:
                        # Header has Fail column but no Error column: [Pass, Fail, Total]
                        status = TestStatus.FAILED.value
                    else:
                        # Both or neither - default to ERROR (more severe)
                        status = TestStatus.ERROR.value

            elif len(numeric_parts) == 4:
                # Four numbers: [Pass, Fail, Error, Total]
                fail_count = int(numeric_parts[1])
                error_count = int(numeric_parts[2])

                if error_count > 0:
                    status = TestStatus.ERROR.value
                elif fail_count > 0:
                    status = TestStatus.FAILED.value

            elif len(numeric_parts) >= 5:
                # Five or more: [Pass, Fail, Error, Broken, Total, ...]
                fail_count = int(numeric_parts[1])
                error_count = int(numeric_parts[2])

                if error_count > 0:
                    status = TestStatus.ERROR.value
                elif fail_count > 0:
                    status = TestStatus.FAILED.value

            results[test_name] = status

    return results

def parse_log_r(log: str) -> dict[str, str]:
    """Parse R testthat output and return {full_test_name: status}.

    Rules:
      * Parse test context lines like "✔ | 60 | expansion" (PASSED) or "✖ | 2 2 9 | render" (FAILED)
      * Also parse the "── Failed tests ──" section for detailed failure info
      * Lines like: "Failure ('test-file.R:8:5'): test name" -> FAILED
      * Lines like: "Error ('test-file.R:25:5'): test name" -> ERROR
    """
    results: dict[str, str] = {}

    # Regexes for parsing test context summary lines such as "✔ | 60 | expansion"
    passed_context_re = re.compile(r"^✔\s+\|[^|]+\|\s+(.+)$")
    failed_context_re = re.compile(r"^✖\s+\|[^|]+\|\s+(.+)$")

    # Regexes for parsing failed tests section
    failure_re = re.compile(r"^Failure\s+\([^)]+\):\s+(.+)$")
    error_re = re.compile(r"^Error\s+\([^)]+\):\s+(.+)$")

    timing_suffix_re = re.compile(r"\s*\[\s*\d+(?:\.\d+)?\s*[a-zA-Z]+\]$")

    def strip_timing_suffix(name: str) -> str:
        return timing_suffix_re.sub("", name).strip()

    # First pass: collect test context statuses (passed/failed contexts)
    for raw in log.splitlines():
        line = raw.strip()

        # Match passed test contexts
        if m := passed_context_re.match(line):
            context_name = strip_timing_suffix(m.group(1).strip())
            results[context_name] = TestStatus.PASSED.value
            continue

        # Match failed test contexts
        if m := failed_context_re.match(line):
            context_name = strip_timing_suffix(m.group(1).strip())
            results[context_name] = TestStatus.FAILED.value
            continue

    # Second pass: collect detailed failure information from failed tests section
    in_failed_section = False
    for raw in log.splitlines():
        line = raw.strip()

        # Detect start of failed tests section
        if line.startswith(("── Failed tests ──", "== Failed tests ==")):
            in_failed_section = True
            continue

        # Detect end of failed section (results summary or end markers)
        if in_failed_section and line.startswith(("[ FAIL", "══ Results ══")):
            break

        if in_failed_section and line:
            # Match failure lines
            if m := failure_re.match(line):
                test_name = strip_timing_suffix(m.group(1).strip())
                results[test_name] = TestStatus.FAILED.value
                continue
            # Match error lines
            if m := error_re.match(line):
                test_name = strip_timing_suffix(m.group(1).strip())
                results[test_name] = TestStatus.ERROR.value
                continue

    return results

def _clojure_path_to_namespace(path: str) -> str | None:
    path = path.strip().strip('"')
    if not re.search(r"\.clj[sc]?$", path):
        return None
    path = re.sub(r"\.clj[sc]?$", "", path)
    namespace = path.replace("/", ".").replace("_", "-")
    return namespace if "." in namespace else None

def _is_clojure_namespace(value: str) -> bool:
    return bool(
        re.fullmatch(r"[A-Za-z][A-Za-z0-9_.!?*+<>=/$-]*(?:\.[A-Za-z0-9_.!?*+<>=/$-]+)+", value)
    )

def parse_log_lein(log: str) -> dict[str, str]:  # noqa: C901, PLR0912, PLR0915
    """Parse Clojure test output into {test_namespace: status}.

    Supports Leiningen, clojure.test, and common Kaocha/Clojure CLI output.
    """
    results: dict[str, str] = {}
    current_namespace: str | None = None
    current_documentation_test: str | None = None
    command_targets: list[str] = []
    lein_re = re.compile(r"^lein test (.+)$")
    testing_re = re.compile(r"^Testing\s+(.+)$")
    success_summary_re = re.compile(
        r"^(?:Ran\s+)?\d+\s+tests?(?:\s+containing\s+\d+\s+assertions|,\s+\d+\s+assertions)?.*"
        r"0\s+failures(?:,\s+0\s+errors)?\.?$"
    )
    path_re = re.compile(r"([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+\.clj[sc]?)(?::\d+)?")
    case_status_re = re.compile(
        r"^(?P<mark>[\u221a\u2713\u00d7xX])\s+"
        r"(?P<name>.+?)(?:\s+(?P<suffix>FAIL|ERROR|PASS|SKIP))?$"
    )
    doc_status_re = re.compile(
        r"^(?P<name>[A-Za-z0-9_][A-Za-z0-9_ .!?*+<>=/$-]*?)\s+"
        r"(?P<statuses>(?:FAIL|ERROR|PASS|SKIP)(?:\s+(?:FAIL|ERROR|PASS|SKIP))*)$"
    )
    documentation_test_re = re.compile(
        r"^ {2}(?P<name>[A-Za-z0-9_!?*+<>=/$-]+)"
        r"(?P<statuses>(?:\s+(?:FAIL|ERROR|PASS|SKIP))*)\s*$"
    )
    failure_test_re = re.compile(
        r"^(?P<status>FAIL|ERROR) in \(?(?P<name>[A-Za-z0-9_.!?*+<>=/$-]+)"
    )
    failure_summary_re = re.compile(
        r"^\d+\s+tests?,\s+\d+\s+assertions?,\s+"
        r"(?P<errors>\d+)\s+errors?,\s+(?P<failures>\d+)\s+failures?\.?$"
    )

    def set_result(name: str | None, status: str) -> None:
        if not name:
            return
        previous = results.get(name)
        if previous == TestStatus.ERROR.value or (
            previous == TestStatus.FAILED.value and status != TestStatus.ERROR.value
        ):
            return
        results[name] = status

    def set_status(namespace: str | None, status: str) -> None:
        if not namespace or not _is_clojure_namespace(namespace):
            return
        set_result(namespace, status)

    def documentation_status(words: str) -> str:
        return next(
            (
                value
                for word, value in (
                    ("ERROR", TestStatus.ERROR.value),
                    ("FAIL", TestStatus.FAILED.value),
                    ("SKIP", TestStatus.SKIPPED.value),
                )
                if word in words.split()
            ),
            TestStatus.PASSED.value,
        )

    def remember_command_target(namespace: str | None) -> None:
        if not namespace or not _is_clojure_namespace(namespace):
            return
        if namespace not in command_targets:
            command_targets.append(namespace)

    def seed_passed_namespace(namespace: str | None) -> None:
        remember_command_target(namespace)
        if namespace and _is_clojure_namespace(namespace):
            results.setdefault(namespace, TestStatus.PASSED.value)

    for target in re.findall(r"(?:--focus|-n)\s+([A-Za-z0-9_.!?*+<>=/$-]+)", log):
        remember_command_target(target.strip())
    for target in re.findall(
        r":ns-regexes\s+['\"]?\[\s*\"([A-Za-z0-9_.!?*+<>=/$-]+)\"", log
    ):
        remember_command_target(target.strip())

    for raw in log.splitlines():
        clean_raw = ansi_escape(raw)
        line = clean_raw.strip()
        if not line:
            continue

        if re.search(r"(?i)\bAll \d+ tests were skipped\b", line):
            if current_namespace:
                for name in list(results):
                    if (
                        name == current_namespace
                        or name.startswith(f"{current_namespace}/")
                    ) and results[name] == TestStatus.PASSED.value:
                        results.pop(name)
            current_documentation_test = None
            continue

        if m := lein_re.match(line):
            payload = m.group(1).strip()
            if not payload:
                current_namespace = None
                current_documentation_test = None
                continue

            tokens = payload.split()
            if tokens and tokens[0] == ":only":
                only_target = " ".join(tokens[1:]).strip()
                if not only_target:
                    current_namespace = None
                    current_documentation_test = None
                    continue
                base = only_target.split("/", 1)[0].strip()
                if base:
                    seed_passed_namespace(base)
                    current_namespace = base
                    current_documentation_test = None
                else:
                    current_namespace = None
                    current_documentation_test = None
            else:
                for token in tokens:
                    base = token.strip()
                    if base:
                        seed_passed_namespace(base)
                        current_namespace = base
                        current_documentation_test = None
            continue

        if m := testing_re.match(line):
            namespace = m.group(1).strip()
            if _is_clojure_namespace(namespace):
                set_status(namespace, TestStatus.PASSED.value)
                current_namespace = namespace
                current_documentation_test = None
            continue

        if _is_clojure_namespace(line):
            set_status(line, TestStatus.PASSED.value)
            current_namespace = line
            current_documentation_test = None
            continue

        if m := documentation_test_re.match(clean_raw):
            if current_namespace:
                current_documentation_test = m.group("name")
                status = documentation_status(m.group("statuses"))
                set_result(
                    f"{current_namespace}/{current_documentation_test}",
                    status,
                )
                if status in {TestStatus.FAILED.value, TestStatus.ERROR.value}:
                    set_status(current_namespace, status)
            continue

        if m := case_status_re.match(line):
            if current_namespace:
                test_name = m.group("name").strip()
                status_suffix = (m.group("suffix") or "").upper()
                if status_suffix:
                    test_name = re.sub(
                        rf"\s+{re.escape(status_suffix)}$",
                        "",
                        test_name,
                        flags=re.IGNORECASE,
                    ).strip()
                full_name = f"{current_namespace} {test_name}"
                mark = m.group("mark")
                if mark in {"\u00d7", "x", "X"} or status_suffix in {"FAIL", "ERROR"}:
                    status = (
                        TestStatus.ERROR.value
                        if status_suffix == "ERROR"
                        else TestStatus.FAILED.value
                    )
                elif status_suffix == "SKIP":
                    status = TestStatus.SKIPPED.value
                else:
                    status = TestStatus.PASSED.value
                if current_documentation_test:
                    full_name = f"{current_namespace}/{current_documentation_test}"
                set_result(full_name, status)
                if status in {TestStatus.FAILED.value, TestStatus.ERROR.value}:
                    set_status(current_namespace, status)
            continue

        if m := doc_status_re.match(line):
            if current_namespace:
                status = documentation_status(m.group("statuses"))
                full_name = (
                    f"{current_namespace}/{current_documentation_test}"
                    if current_documentation_test
                    else f"{current_namespace} {m.group('name').strip()}"
                )
                set_result(full_name, status)
                if status in {TestStatus.FAILED.value, TestStatus.ERROR.value}:
                    set_status(current_namespace, status)
            continue

        if m := failure_test_re.match(line):
            status = (
                TestStatus.ERROR.value if m.group("status") == "ERROR" else TestStatus.FAILED.value
            )
            name = m.group("name")
            namespace = name.split("/", 1)[0] if "/" in name else current_namespace
            set_status(namespace, status)
            full_name = name if "/" in name else f"{namespace}/{name}"
            if full_name in results:
                set_result(full_name, status)
            if namespace is None and len(command_targets) == 1:
                set_status(command_targets[0], status)
            continue
        if line.startswith("FAIL in") and len(command_targets) == 1:
            results[command_targets[0]] = TestStatus.FAILED.value
            continue
        if line.startswith("ERROR in") and len(command_targets) == 1:
            results[command_targets[0]] = TestStatus.ERROR.value
            continue

        if success_summary_re.match(line) and not results:
            for namespace in command_targets:
                set_status(namespace, TestStatus.PASSED.value)
            continue
        if m := failure_summary_re.match(line):
            errors = int(m.group("errors"))
            failures = int(m.group("failures"))
            if current_namespace and (errors or failures):
                results[current_namespace] = (
                    TestStatus.ERROR.value if errors else TestStatus.FAILED.value
                )
            continue

        if re.search(
            r"(?i)(error|exception|failed loading|syntax error|could not locate)", line
        ):
            for path in path_re.findall(line):
                namespace = _clojure_path_to_namespace(path)
                if namespace:
                    results[namespace] = TestStatus.ERROR.value

    return results

def _iter_dart_protocol_events(log: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in log.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            decoded = json.loads(line)
        except json.JSONDecodeError:
            continue

        if isinstance(decoded, dict):
            events.append(decoded)
        elif isinstance(decoded, list):
            events.extend(item for item in decoded if isinstance(item, dict))
    return events

def _handle_dart_test_start(
    event: dict[str, Any], test_id_to_name: dict[int, str]
) -> None:
    test_info = event.get("test")
    if not isinstance(test_info, dict):
        return

    test_id = test_info.get("id")
    test_name = test_info.get("name")
    if test_id is None or not test_name or test_name.startswith("loading "):
        return

    test_id_to_name[test_id] = test_name

def _dart_done_status(event: dict[str, Any]) -> str | None:
    result = event.get("result")
    if result == "success":
        return TestStatus.PASSED.value
    if result == "failure":
        return TestStatus.FAILED.value
    if result == "error":
        return TestStatus.ERROR.value
    if event.get("skipped", False):
        return TestStatus.SKIPPED.value
    return None

def _handle_dart_test_done(
    event: dict[str, Any], test_id_to_name: dict[int, str], results: dict[str, str]
) -> None:
    test_id = event.get("testID")
    if test_id is None or event.get("hidden", False):
        return
    if test_id not in test_id_to_name:
        return

    status = _dart_done_status(event)
    if status is None:
        return

    test_name = test_id_to_name[test_id]
    results[test_name] = status

def parse_log_dart(log: str) -> dict[str, str]:
    """Parse Dart test output and return {test_name: status}.

    Dart test output is a stream of JSON objects with events.
    - testStart events have test.id and test.name
    - testDone events have testID and result (success, failure, error, or skipped)

    We map test IDs to names, then to their final result status.
    """
    results: dict[str, str] = {}
    test_id_to_name: dict[int, str] = {}

    for event in _iter_dart_protocol_events(log):
        event_type = event.get("type")
        if event_type == "testStart":
            _handle_dart_test_start(event, test_id_to_name)
            continue
        if event_type == "testDone":
            _handle_dart_test_done(event, test_id_to_name, results)

    return results

def parse_log_dart_v3(log: str) -> dict[str, str]:
    """Parse Dart/Flutter test output and return {full_test_name: status}.

    Rules:
      * Lines like: "00:01 +64: /path/to/test.dart: test name" -> PASSED
      * Lines like: "00:02 +88 -1: /path/to/test.dart: test name [E]" -> FAILED
      * Lines like: "00:02 +88 -1: test name [E]" -> FAILED
      * Lines like: "00:06 +200 -3: loading /path/to/test.dart [E]" -> ERROR
      * Lines like: "00:06 +200: loading /path/to/test.dart" -> PASSED

    The ``-N`` progress counter is cumulative for the whole suite. It must not
    be used to mark a later, individually successful test as failed.
    """
    results: dict[str, str] = {}

    progress_line_re = re.compile(
        r"^\d+:\d+\s+\+\d+(?:\s+-\d+)?:\s+(?P<body>.+)$"
    )
    absolute_test_re = re.compile(r"^(?P<path>/[^:]+\.dart):\s+(?P<name>.+)$")
    loading_re = re.compile(r"^loading\s+(?P<path>/[^:]+\.dart)$")
    summaries = {"Some tests failed.", "All tests passed!"}

    for raw in log.splitlines():
        line = raw.strip()
        if not line:
            continue

        if not (m := progress_line_re.match(line)):
            continue

        body = m.group("body")
        has_error_marker = body.endswith(" [E]")
        if has_error_marker:
            body = body.removesuffix(" [E]").rstrip()

        if loading := loading_re.match(body):
            if has_error_marker:
                results[loading.group("path")] = TestStatus.ERROR.value
            else:
                results.setdefault(loading.group("path"), TestStatus.PASSED.value)
            continue

        # Flutter's expanded reporter omits a file path when the command
        # selects a single test file. The remaining body is still its stable
        # test name and is suitable for before/after bucket comparison.
        if body in summaries:
            continue
        if absolute_test := absolute_test_re.match(body):
            full_test_name = (
                f"{absolute_test.group('path')}: {absolute_test.group('name').strip()}"
            )
        else:
            full_test_name = body

        if has_error_marker:
            results[full_test_name] = TestStatus.FAILED.value
        else:
            results.setdefault(full_test_name, TestStatus.PASSED.value)

    return results

def parse_log_scala(log: str) -> dict[str, str]:
    """Parse ScalaTest output and return {test_name: status}.

    Rules:
      * Lines like: "[info] - should <name> (<time>)" -> PASSED
      * Lines like: "[info] - should <name> *** FAILED *** (<time>)" -> FAILED
      * Lines like: "[info] - should <name> !!! CANCELED !!! (<time>)" -> SKIPPED
      * Lines like: "[info] - should <name> !!! IGNORED !!!" -> SKIPPED
    """
    results: dict[str, str] = {}

    # Regex patterns for ScalaTest output
    # Match failed tests: [info] - should test name *** FAILED *** (time)
    failed_re = re.compile(
        r"^\[info\]\s+-\s+(.*?)\s+\*\*\*\s+FAILED\s+\*\*\*\s+\([^)]+\)$"
    )
    # Match canceled tests: [info] - should test name !!! CANCELED !!! (time)
    canceled_re = re.compile(
        r"^\[info\]\s+-\s+(.*?)\s+!!!\s+CANCELED\s+!!!\s+\([^)]+\)$"
    )
    # Match ignored tests: [info] - should test name !!! IGNORED !!!
    ignored_re = re.compile(r"^\[info\]\s+-\s+(.*?)\s+!!!\s+IGNORED\s+!!!")
    # Match passed tests: [info] - should test name (time)
    passed_re = re.compile(r"^\[info\]\s+-\s+(.*?)\s+\([^)]+\)$")

    for raw in log.splitlines():
        line = raw.strip()
        if not line:
            continue

        # Check for failed tests first (most specific)
        if m := failed_re.match(line):
            results[m.group(1)] = TestStatus.FAILED.value
            continue

        # Check for canceled tests
        if m := canceled_re.match(line):
            results[m.group(1)] = TestStatus.SKIPPED.value
            continue

        # Check for ignored tests
        if m := ignored_re.match(line):
            results[m.group(1)] = TestStatus.SKIPPED.value
            continue

        # Check for passed tests (least specific, matches any test with timing)
        if m := passed_re.match(line):
            # Only set if not already marked as failed/skipped
            results.setdefault(m.group(1), TestStatus.PASSED.value)
            continue

    return results

def parse_log_scala_v3(log: str) -> dict[str, str]:
    """Parse Scala test output and return {full_test_name: status}.

    Handles ScalaTest "[info] - ..." lines and recognizes failure markers.
    Combines suite names with test names (e.g., "recover: should return the value").
    """
    results: dict[str, str] = {}

    status_map = {
        "PASSED": TestStatus.PASSED.value,
        "FAILED": TestStatus.FAILED.value,
        "ERROR": TestStatus.ERROR.value,
        "ABORTED": TestStatus.ERROR.value,
        "SKIPPED": TestStatus.SKIPPED.value,
        "IGNORED": TestStatus.SKIPPED.value,
        "CANCELED": TestStatus.SKIPPED.value,
        "CANCELLED": TestStatus.SKIPPED.value,
        "PENDING": TestStatus.SKIPPED.value,
    }

    test_line_re = re.compile(r"^\[info\]\s+-\s+(.*?)(?:\s+\*{3}\s+([A-Z]+)\s+\*{3})?$")
    suite_line_re = re.compile(r"^\[info\]\s+([^\-].*)$")

    current_suite = None

    for raw in log.splitlines():
        line = raw.strip()
        if not line.startswith("[info]"):
            continue

        # Check if this is a test line (starts with "- ")
        if line.startswith("[info] -"):
            if match := test_line_re.match(line):
                test_name = match.group(1).strip()
                # Remove timing information in parentheses at the end
                test_name = re.sub(r"\s*\(\d+\s+\w+\)$", "", test_name)

                status_token = match.group(2)

                # Combine suite name with test name if suite exists
                full_test_name = (
                    f"{current_suite}: {test_name}" if current_suite else test_name
                )

                if status_token:
                    normalized = status_token.upper()
                    status = status_map.get(normalized, normalized)
                    results[full_test_name] = status
                else:
                    results.setdefault(full_test_name, TestStatus.PASSED.value)
        # This might be a suite name line
        elif match := suite_line_re.match(line):
            potential_suite = match.group(1).strip()
            # Filter out non-suite lines (like "Run completed", "Total number", etc.)
            if potential_suite and not any(
                skip in potential_suite
                for skip in [
                    "Run completed",
                    "Total number",
                    "Suites:",
                    "Tests:",
                    "All tests",
                    "compiling",
                    "done compiling",
                    "loading",
                    "welcome to",
                    "set current",
                ]
            ):
                current_suite = potential_suite

    return results

def parse_log_ocaml(log: str) -> dict[str, str]:
    """Parse Alcotest/QCheck output and return {full_test_name: status}."""
    results: dict[str, str] = {}
    status_map: dict[str, str] = {
        "OK": TestStatus.PASSED.value,
        "PASS": TestStatus.PASSED.value,
        "FAIL": TestStatus.FAILED.value,
        "FAILED": TestStatus.FAILED.value,
        "ERROR": TestStatus.ERROR.value,
        "ERR": TestStatus.ERROR.value,
        "SKIP": TestStatus.SKIPPED.value,
        "SKIPPED": TestStatus.SKIPPED.value,
        "TODO": TestStatus.SKIPPED.value,
    }
    entry_re = re.compile(
        r"^\s*\[(?P<status>[A-Z]+)\]\s+(?P<suite>.*?)\s+(?P<index>\d+)\s+(?P<name>.+)$"
    )
    # Recognize Alcotest/QCheck status lines like "[OK] suite idx description".
    for raw in log.splitlines():
        line = raw.rstrip()
        match = entry_re.match(line)
        if not match:
            continue
        status_token = match.group("status")
        suite = match.group("suite").strip()
        index = match.group("index").strip()
        name = match.group("name").strip()
        test_name = " ".join(part for part in (suite, index, name) if part)
        mapped_status = status_map.get(status_token, TestStatus.ERROR.value)
        if mapped_status == TestStatus.PASSED.value:
            results.setdefault(test_name, mapped_status)
        else:
            results[test_name] = mapped_status
    return results

def parse_log_ocaml_v3(log: str) -> dict[str, str]:
    """Parse inline OCaml test output and return {test_case: status}.

    Rules:
      * Lines starting with "[OK]" (or similar pass tokens) mark the case as PASSED.
      * Lines starting with "[SKIP]" (or aliases) mark the case as SKIPPED unless it failed later.
      * Lines starting with failure tokens ("[FAIL]", "[ERROR]", "[CRASH]", "[KO]", etc.) mark the case as FAILED and override previous entries.
    """
    results: dict[str, str] = {}
    status_tokens: dict[str, str] = {
        "OK": TestStatus.PASSED.value,
        "PASS": TestStatus.PASSED.value,
        "PASSED": TestStatus.PASSED.value,
        "SUCCESS": TestStatus.PASSED.value,
        "SKIP": TestStatus.SKIPPED.value,
        "SKIPPED": TestStatus.SKIPPED.value,
        "TODO": TestStatus.SKIPPED.value,
        "PENDING": TestStatus.SKIPPED.value,
        "DISABLED": TestStatus.SKIPPED.value,
        "FAIL": TestStatus.FAILED.value,
        "FAILED": TestStatus.FAILED.value,
        "ERROR": TestStatus.FAILED.value,
        "EXCEPTION": TestStatus.FAILED.value,
        "CRASH": TestStatus.FAILED.value,
        "FATAL": TestStatus.FAILED.value,
        "KO": TestStatus.FAILED.value,
        "PANIC": TestStatus.FAILED.value,
    }
    status_line_re = re.compile(
        r"^\[(?P<token>[A-Za-z][A-Za-z0-9_-]*)\]\s+(?P<body>.+)$"
    )

    def update_status(name: str, status: str) -> None:
        if not name:
            return
        current = results.get(name)
        if current is None:
            results[name] = status
            return
        if OCAML_STATUS_PRECEDENCE.get(status, -1) >= OCAML_STATUS_PRECEDENCE.get(
            current, -1
        ):
            results[name] = status

    for raw_line in log.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("["):
            continue
        match = status_line_re.match(line)
        if not match:
            continue
        token = match.group("token").upper()
        status = status_tokens.get(token)
        if status is None:
            continue
        body = match.group("body")
        test_name = re.sub(r"\s+", " ", body).strip()
        if not test_name:
            continue
        update_status(test_name, status)

    return results

def _ocaml_test_section(log: str) -> str:
    normalized = ANSI_ESCAPE_RE.sub("", log)
    start_marker = "\n___TESTS_SECTION___\n"
    end_marker = "\n___TESTS_SECTION_END___"
    start = normalized.find(start_marker)
    if start < 0:
        return normalized
    start += len(start_marker)
    end = normalized.find(end_marker, start)
    return normalized[start:end] if end >= 0 else normalized[start:]

def parse_log_ocaml_v6(log: str) -> dict[str, str]:
    """Parse an opt-in aggregate OCaml command result from explicit evidence."""
    section = _ocaml_test_section(log)
    failure_patterns = (
        r"^.*\[(?:FAIL|FAILED)\](?!:)",
        r"^\s*FAIL(?:\s|:)",
        r"\bFAILED:",
        r"^\s*RESULT\s+.+\s+-\s+(?:FAIL|ERROR)\b",
        r"^\s*Fatal error:",
        r"^\s*Error:",
        r"<failure(?:\s|>)",
        r"<error(?:\s|>)",
        r"^\s*[1-9]\d*\s+(?:failures?!|unsuccessful\b)",
        r"^[.FES]*F[.FES]*$",
    )
    success_patterns = (
        r"^.*\[(?:OK|PASS|PASSED)\](?!:)",
        r"^\s*RESULT\s+.+\s+-\s+PASS\b",
        r"^\s*[Oo][Kk]\s{2,}",
        r"\bTest Successful\b",
        r"<testcase(?:\s|>)",
        r"^\s*[^\n:]+:\s*OK\s*$",
        r'"success"\s*:\s*[1-9]\d*',
        r"\bAll\b[^\n]*\btests passed!",
        r"^\.+$",
        r"\bpassed$",
    )
    flags = re.MULTILINE
    if any(re.search(pattern, section, flags) for pattern in failure_patterns):
        status = TestStatus.FAILED.value
    elif any(re.search(pattern, section, flags) for pattern in success_patterns):
        status = TestStatus.PASSED.value
    else:
        return {}
    return {"__ocaml_test_command__": status}

def parse_logs_r_junit(log: str) -> dict[str, str]:
    """Parse R testthat JUnit XML output and return {full_test_name: status}.

    Parses JUnit XML format from testthat::test_local(..., reporter = 'junit').
    Returns a dict mapping test names to their status (PASSED, FAILED, SKIPPED, ERROR).
    """
    results: dict[str, str] = {}

    try:
        # Find the XML content in the log
        xml_start = log.find("<?xml")
        if xml_start == -1:
            return results

        xml_content = log[xml_start:]
        # Try to find the end of XML (closing </testsuites>)
        xml_end = xml_content.find("</testsuites>")
        if xml_end != -1:
            xml_content = xml_content[: xml_end + len("</testsuites>")]

        root = ET.fromstring(xml_content)

        # Iterate through all testsuites and testcases
        for testsuite in root.findall(".//testsuite"):
            for testcase in testsuite.findall("testcase"):
                test_name = testcase.get("name", "")
                classname = testcase.get("classname", "")

                # Create full test name (classname::test_name)
                full_name = f"{classname}::{test_name}" if classname else test_name

                # Check for failure, error, or skipped elements
                if testcase.find("failure") is not None:
                    results[full_name] = TestStatus.FAILED.value
                elif testcase.find("error") is not None:
                    results[full_name] = TestStatus.ERROR.value
                elif testcase.find("skipped") is not None:
                    results[full_name] = TestStatus.SKIPPED.value
                else:
                    # No failure/error/skipped element means the test passed
                    results[full_name] = TestStatus.PASSED.value

    except ET.ParseError:
        # If XML parsing fails, return empty results
        pass

    return results

def parse_log_swift(log: str) -> dict[str, str]:
    """Parse Swift XCTest output and return {full_test_name: status}.

    Rules:
      * Lines like: "Test Case 'ClassName.testName' passed (X.X seconds)" -> PASSED
      * Lines like: "Test Case 'ClassName.testName' failed (X.X seconds)" -> FAILED
      * Extract test name from the quoted portion
    """
    results: dict[str, str] = {}

    # Regex to match test completion lines
    test_result_re = re.compile(
        r"^Test Case '([^']+)'\s+(passed|failed)\s+\([0-9.]+\s+seconds\)$"
    )

    for raw in log.splitlines():
        line = raw.strip()
        if not line:
            continue

        if m := test_result_re.match(line):
            test_name = m.group(1)
            status = m.group(2).upper()

            if status == "PASSED":
                results[test_name] = TestStatus.PASSED.value
            elif status == "FAILED":
                results[test_name] = TestStatus.FAILED.value

    return results

def _parse_swift_junit_testcases(log: str) -> dict[str, str]:
    results: dict[str, str] = {}
    start_marker = "<?xml"
    end_marker = "</testsuites>"
    pos = 0

    while pos < len(log):
        xml_start = log.find(start_marker, pos)
        if xml_start == -1:
            break

        xml_end = log.find(end_marker, xml_start)
        if xml_end == -1:
            pos = xml_start + len(start_marker)
            continue

        xml_end += len(end_marker)
        try:
            root = ET.fromstring(log[xml_start:xml_end])
        except ET.ParseError:
            pos = xml_end
            continue

        for testcase in root.findall(".//testcase"):
            name = (testcase.get("name") or "").strip()
            classname = (testcase.get("classname") or "").strip()
            if not name:
                continue

            full_name = f"{classname} {name}".strip() if classname else name
            if testcase.find("failure") is not None:
                status = TestStatus.FAILED.value
            elif testcase.find("error") is not None:
                status = TestStatus.ERROR.value
            elif testcase.find("skipped") is not None:
                status = TestStatus.SKIPPED.value
            else:
                status = TestStatus.PASSED.value
            results[full_name] = status

        pos = xml_end

    return results

def parse_log_swift_v2(log: str) -> dict[str, str]:
    results = parse_log_swift(log)
    results.update(_parse_swift_junit_testcases(log))
    return results

def _parse_swift_testing_testcases(log: str) -> dict[str, str]:
    results: dict[str, str] = {}
    result_re = re.compile(
        r'^[✔✘]\s+Test\s+(?:"(?P<quoted>[^"]+)"|(?P<plain>.+?))\s+'
        r"(?P<status>passed|failed)\s+after\b"
    )

    for raw in log.splitlines():
        match = result_re.match(ansi_escape(raw).strip())
        if match is None:
            continue
        name = (match.group("quoted") or match.group("plain")).strip()
        if match.group("quoted") is None and name.startswith("run with "):
            continue
        status = (
            TestStatus.PASSED.value
            if match.group("status") == "passed"
            else TestStatus.FAILED.value
        )
        results[name] = status

    return results

def _parse_swift_testing_command_status(log: str) -> dict[str, str]:
    status = None
    summary_re = re.compile(
        r"^[✔✘]\s+Test run with\s+\d+\s+tests?.*?\s+(passed|failed)\s+after\b"
    )
    for raw in log.splitlines():
        match = summary_re.match(ansi_escape(raw).strip())
        if match is not None:
            status = (
                TestStatus.PASSED.value
                if match.group(1) == "passed"
                else TestStatus.FAILED.value
            )

    if status is None:
        compile_error_re = re.compile(
            r"(?:\.swift:\d+:\d+:\s+error:|^\s*(?:error:|(?:clang|swiftc):?\s+error:))"
        )
        if any(compile_error_re.search(ansi_escape(line)) for line in log.splitlines()):
            status = TestStatus.FAILED.value

    return {"__swift_test_command__": status} if status is not None else {}

def parse_log_swift_v3(log: str) -> dict[str, str]:
    results = parse_log_swift_v2(log)
    results.update(_parse_swift_testing_testcases(log))
    results.update(_parse_swift_testing_command_status(log))
    return results

def parse_log_rebench_explicit_v1(log: str) -> dict[str, str]:
    results: dict[str, str] = {}
    exit_re = re.compile(r"^(?P<name>.+?)\s+exit status:\s*(?P<code>\d+)\s*$")
    result_re = re.compile(r"^RESULT:\s*(?P<status>PASS|FAIL)\b")

    for raw in log.splitlines():
        line = ansi_escape(raw).strip()
        if match := exit_re.match(line):
            results[match.group("name").strip()] = (
                TestStatus.PASSED.value
                if int(match.group("code")) == 0
                else TestStatus.FAILED.value
            )
        elif match := result_re.match(line):
            results["rebench explicit result"] = (
                TestStatus.PASSED.value
                if match.group("status") == "PASS"
                else TestStatus.FAILED.value
            )

    return results

def parse_log_csharp(log: str) -> dict[str, str]:
    """Parse xUnit.net output and return {full_test_name: status}.

    Rules:
      * Lines like: "  Passed <test_name> [<time>]" or without a duration -> PASSED
      * Lines like: "  Failed <test_name> [<time>]" or without a duration -> FAILED
      * Lines like: "  Skipped <test_name>" -> SKIPPED
      * Lines like: "[xUnit.net timestamp]     <test_name> [FAIL]" -> FAILED (overrides prior status)
    """
    results: dict[str, str] = {}

    # Regexes for xUnit.net output
    # A test display name may itself include brackets (for example ``[]``).
    # Only a final .NET time token is metadata, rather than any bracketed
    # suffix, so names remain exact both with and without a reported duration.
    duration_suffix = (
        r"(?:\[(?:<\s*)?\d+(?:\.\d+)?\s*(?:ms|s)\]"
        r"|\((?:\d+(?:\.\d+)?\s*(?:ms|s))(?:\s+\d+(?:\.\d+)?\s*(?:ms|s))*\))"
    )
    passed_re = re.compile(rf"^\s*[Pp]assed\s+(.+?)(?:\s+{duration_suffix})?$")
    failed_re = re.compile(rf"^\s*[Ff]ailed\s+(.+?)(?:\s+{duration_suffix})?$")
    skipped_re = re.compile(r"^\s*[Ss]kipped\s+(.+?)(?:\s+\[.+?\])?$")
    # Alternative failure format: [xUnit.net timestamp]     TestName [FAIL]
    xunit_fail_re = re.compile(r"^\[xUnit\.net\s+[\d:\.]+\]\s+(.+?)\s+\[FAIL\]$")

    for raw in log.splitlines():
        line = raw.rstrip()
        if not line:
            continue

        if m := xunit_fail_re.match(line):
            # This format indicates a failure, overrides any previous status
            results[m.group(1)] = TestStatus.FAILED.value
            continue

        if m := failed_re.match(line):
            results[m.group(1)] = TestStatus.FAILED.value
            continue

        if m := skipped_re.match(line):
            results[m.group(1)] = TestStatus.SKIPPED.value
            continue

        if m := passed_re.match(line):
            # Only set if not already marked as failed
            results.setdefault(m.group(1), TestStatus.PASSED.value)
            continue

    return results


NAME_TO_PARSER = {
    "parse_log_csharp": parse_log_csharp,
    "parse_log_dart": parse_log_dart,
    "parse_log_dart_v3": parse_log_dart_v3,
    "parse_log_elixir": parse_log_elixir,
    "parse_log_erlang": parse_log_erlang,
    "parse_log_gradle_custom": parse_log_gradle_custom,
    "parse_log_haskell_v2": parse_log_haskell_v2,
    "parse_log_julia": parse_log_julia,
    "parse_log_junit_strict": parse_log_junit_strict,
    "parse_log_lein": parse_log_lein,
    "parse_log_ocaml": parse_log_ocaml,
    "parse_log_ocaml_v3": parse_log_ocaml_v3,
    "parse_log_ocaml_v6": parse_log_ocaml_v6,
    "parse_log_r": parse_log_r,
    "parse_log_rebench_explicit_v1": parse_log_rebench_explicit_v1,
    "parse_log_scala": parse_log_scala,
    "parse_log_scala_v3": parse_log_scala_v3,
    "parse_log_swift_v2": parse_log_swift_v2,
    "parse_log_swift_v3": parse_log_swift_v3,
    "parse_log_tap": parse_log_tap,
    "parse_logs_r_junit": parse_logs_r_junit,
    "parse_lue_nvim": parse_lue_nvim,
}
