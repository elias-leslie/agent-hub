"""
Code hygiene analyzer for detecting technical debt and quality issues.

Detects:
- Mypy suppressions in pyproject.toml (disable_error_code entries)
- Dead code patterns (unused functions/variables based on naming conventions)
- Deprecated markers (TODO: remove, DEPRECATED, legacy, backwards-compat)
- Missing type annotations
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


@dataclass
class Finding:
    """A single code hygiene finding."""

    category: str  # "mypy_suppression", "dead_code", "deprecated", "missing_types"
    severity: str  # "low", "medium", "high"
    file_path: str
    line_number: int | None
    message: str
    context: str | None = None  # Relevant code snippet
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Result of code hygiene analysis."""

    findings: list[Finding]
    files_analyzed: int
    total_issues: int
    issues_by_category: dict[str, int]
    issues_by_severity: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "findings": [
                {
                    "category": f.category,
                    "severity": f.severity,
                    "file_path": f.file_path,
                    "line_number": f.line_number,
                    "message": f.message,
                    "context": f.context,
                    "metadata": f.metadata,
                }
                for f in self.findings
            ],
            "summary": {
                "files_analyzed": self.files_analyzed,
                "total_issues": self.total_issues,
                "by_category": self.issues_by_category,
                "by_severity": self.issues_by_severity,
            },
        }


class CodeHygieneAnalyzer:
    """Analyzer for code hygiene and technical debt detection."""

    # Patterns for deprecated code markers
    DEPRECATED_PATTERNS: ClassVar[list[str]] = [
        r"TODO:\s*remove",
        r"DEPRECATED",
        r"@deprecated",
        r"# legacy",
        r"# backwards[- ]compat",
        r"# backward[- ]compat",
        r"FIXME:\s*remove",
    ]

    # Patterns for potential dead code
    DEAD_CODE_PATTERNS: ClassVar[list[str]] = [
        r"def\s+_unused_\w+",  # Functions named _unused_*
        r"def\s+_old_\w+",  # Functions named _old_*
        r"class\s+_Unused\w+",  # Classes named _Unused*
        r"class\s+_Old\w+",  # Classes named _Old*
    ]

    def __init__(self, root_path: Path | str):
        """
        Initialize the analyzer.

        Args:
            root_path: Root directory to analyze
        """
        self.root_path = Path(root_path)
        self.findings: list[Finding] = []
        self.files_analyzed = 0

    def analyze(self, patterns: list[str] | None = None) -> AnalysisResult:
        """
        Run comprehensive code hygiene analysis.

        Args:
            patterns: Optional list of file patterns to analyze (e.g., ["*.py", "pyproject.toml"])
                     If None, analyzes all Python files and pyproject.toml

        Returns:
            AnalysisResult with all findings and statistics
        """
        self.findings = []
        self.files_analyzed = 0

        if patterns is None:
            patterns = ["*.py", "pyproject.toml"]

        # Analyze pyproject.toml for mypy suppressions
        pyproject_path = self.root_path / "pyproject.toml"
        if pyproject_path.exists():
            self._analyze_pyproject(pyproject_path)

        # Analyze Python files
        for pattern in patterns:
            if pattern.endswith(".py"):
                for py_file in self.root_path.rglob(pattern):
                    if self._should_analyze_file(py_file):
                        self._analyze_python_file(py_file)

        # Calculate statistics
        issues_by_category: dict[str, int] = {}
        issues_by_severity: dict[str, int] = {}

        for finding in self.findings:
            issues_by_category[finding.category] = issues_by_category.get(finding.category, 0) + 1
            issues_by_severity[finding.severity] = issues_by_severity.get(finding.severity, 0) + 1

        return AnalysisResult(
            findings=self.findings,
            files_analyzed=self.files_analyzed,
            total_issues=len(self.findings),
            issues_by_category=issues_by_category,
            issues_by_severity=issues_by_severity,
        )

    def _should_analyze_file(self, file_path: Path) -> bool:
        """Check if file should be analyzed (exclude test files, migrations, etc.)."""
        exclude_patterns = [
            "__pycache__",
            ".venv",
            "venv",
            "node_modules",
            ".git",
            "migrations",
        ]

        path_str = str(file_path)
        return not any(pattern in path_str for pattern in exclude_patterns)

    def _analyze_pyproject(self, pyproject_path: Path) -> None:
        """Analyze pyproject.toml for mypy suppressions."""
        try:
            content = pyproject_path.read_text()
            self.files_analyzed += 1

            # Look for disable_error_code entries
            in_mypy_section = False
            for line_num, line in enumerate(content.splitlines(), start=1):
                if "[tool.mypy" in line:
                    in_mypy_section = True
                elif line.startswith("[") and in_mypy_section:
                    in_mypy_section = False

                if in_mypy_section and "disable_error_code" in line:
                    # Extract the disabled codes
                    match = re.search(r"disable_error_code\s*=\s*\[([^\]]+)\]", line)
                    if match:
                        codes = match.group(1)
                        self.findings.append(
                            Finding(
                                category="mypy_suppression",
                                severity="medium",
                                file_path=str(pyproject_path.relative_to(self.root_path)),
                                line_number=line_num,
                                message=f"Mypy error codes disabled: {codes}",
                                context=line.strip(),
                                metadata={"disabled_codes": codes},
                            )
                        )

        except Exception as e:
            logger.warning(f"Error analyzing {pyproject_path}: {e}")

    def _analyze_python_file(self, file_path: Path) -> None:
        """Analyze a Python file for hygiene issues."""
        try:
            content = file_path.read_text()
            self.files_analyzed += 1
            lines = content.splitlines()

            for line_num, line in enumerate(lines, start=1):
                # Check for deprecated markers
                for pattern in self.DEPRECATED_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        self.findings.append(
                            Finding(
                                category="deprecated",
                                severity="high",
                                file_path=str(file_path.relative_to(self.root_path)),
                                line_number=line_num,
                                message=f"Deprecated code marker found: {pattern}",
                                context=line.strip(),
                            )
                        )

                # Check for dead code patterns
                for pattern in self.DEAD_CODE_PATTERNS:
                    if re.search(pattern, line):
                        self.findings.append(
                            Finding(
                                category="dead_code",
                                severity="medium",
                                file_path=str(file_path.relative_to(self.root_path)),
                                line_number=line_num,
                                message=f"Potential dead code detected: {pattern}",
                                context=line.strip(),
                            )
                        )

            # Check for missing type annotations in function definitions
            self._check_missing_types(file_path, lines)

        except Exception as e:
            logger.warning(f"Error analyzing {file_path}: {e}")

    def _check_missing_types(self, file_path: Path, lines: list[str]) -> None:
        """Check for missing type annotations in function definitions."""
        # Pattern to match function definitions without return type annotations
        # Excludes __init__, __str__, __repr__ and other dunder methods
        func_pattern = re.compile(r"^\s*def\s+(?!__[a-z_]+__\b)(\w+)\s*\([^)]*\)(?!\s*->):")

        for line_num, line in enumerate(lines, start=1):
            match = func_pattern.match(line)
            if match:
                func_name = match.group(1)
                # Skip test functions and private helpers
                if not func_name.startswith("test_") and not func_name.startswith("_"):
                    self.findings.append(
                        Finding(
                            category="missing_types",
                            severity="low",
                            file_path=str(file_path.relative_to(self.root_path)),
                            line_number=line_num,
                            message=f"Function '{func_name}' missing return type annotation",
                            context=line.strip(),
                            metadata={"function_name": func_name},
                        )
                    )


def analyze_code_hygiene(
    root_path: Path | str, patterns: list[str] | None = None
) -> AnalysisResult:
    """
    Convenience function to run code hygiene analysis.

    Args:
        root_path: Root directory to analyze
        patterns: Optional list of file patterns to analyze

    Returns:
        AnalysisResult with findings and statistics
    """
    analyzer = CodeHygieneAnalyzer(root_path)
    return analyzer.analyze(patterns)
