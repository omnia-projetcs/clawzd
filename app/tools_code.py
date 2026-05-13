"""
Clawzd — Code execution and auditing tools.
Runs Python code in a sandboxed subprocess with resource limits.
Integrates PyCodeAudit scanners: Semgrep, Trivy, detect-secrets, dep-scan
alongside pylint, bandit, and radon for comprehensive OWASP/CIS auditing.
"""
import subprocess
import tempfile
import textwrap
import shutil
import os
import re
import uuid
import json
import resource
import logging
from pathlib import Path
from typing import Dict, List, Optional
from collections import Counter
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from config import DATA_DIR, WORKSPACE_DIR
import difflib
router = APIRouter()
logger = logging.getLogger("clawzd.tools_code")

REPORTS_DIR = os.path.join(DATA_DIR, "audit_reports")


class LocalCodeExecutor:
    """Execute Python code in an isolated subprocess with timeout and memory limits.

    Automatically detects missing imports and pip-installs them before execution.
    """

    # Map of common import names to their pip package names (when they differ)
    IMPORT_TO_PIP: Dict[str, str] = {
        "cv2": "opencv-python",
        "PIL": "Pillow",
        "sklearn": "scikit-learn",
        "skimage": "scikit-image",
        "bs4": "beautifulsoup4",
        "yaml": "pyyaml",
        "dateutil": "python-dateutil",
        "docx": "python-docx",
        "pptx": "python-pptx",
        "dotenv": "python-dotenv",
        "gi": "PyGObject",
        "attr": "attrs",
        "wx": "wxPython",
        "serial": "pyserial",
        "usb": "pyusb",
        "Crypto": "pycryptodome",
        "jose": "python-jose",
        "magic": "python-magic",
        "lxml": "lxml",
        "yahooquery": "yahooquery",
        "ta": "ta",
        "mplfinance": "mplfinance",
        "plotly": "plotly",
        "ccxt": "ccxt",
        "fredapi": "fredapi",
        "stockstats": "stockstats",
        "finta": "finta",
        "cufflinks": "cufflinks",
        "newsapi": "newsapi-python",
        "tweepy": "tweepy",
        "requests_cache": "requests-cache",
    }

    # Packages to always pre-install when first needed
    DEFAULT_PACKAGES = [
        "pandas", "numpy", "matplotlib", "requests", "urllib3",
        "seaborn", "scipy", "Pillow", "beautifulsoup4", "lxml",
        "openpyxl", "python-dateutil", "yahooquery", "ta",
        "mplfinance", "plotly", "ccxt", "scikit-learn",
        "sympy", "statsmodels", "tabulate", "kaleido",
        "requests-cache",
    ]

    # Standard library modules (no pip install needed)
    STDLIB_MODULES = {
        "os", "sys", "re", "json", "math", "time", "datetime", "random",
        "collections", "itertools", "functools", "operator", "string",
        "io", "pathlib", "shutil", "tempfile", "glob", "fnmatch",
        "csv", "sqlite3", "hashlib", "hmac", "base64", "binascii",
        "struct", "codecs", "unicodedata", "textwrap", "difflib",
        "logging", "warnings", "traceback", "unittest", "doctest",
        "typing", "abc", "copy", "pprint", "enum", "dataclasses",
        "contextlib", "decimal", "fractions", "statistics", "cmath",
        "socket", "http", "urllib", "email", "html", "xml",
        "threading", "multiprocessing", "subprocess", "signal",
        "argparse", "configparser", "getpass", "platform", "uuid",
        "calendar", "locale", "gettext", "zlib", "gzip", "bz2",
        "zipfile", "tarfile", "pickle", "shelve", "marshal",
        "webbrowser", "ssl", "ftplib", "smtplib", "imaplib",
        "poplib", "xmlrpc", "pdb", "profile", "timeit", "resource",
        "array", "queue", "heapq", "bisect", "weakref", "types",
        "inspect", "dis", "ast", "token", "tokenize", "keyword",
        "linecache", "code", "codeop", "compileall",
        "_thread", "concurrent", "asyncio", "selectors", "mmap",
    }

    _defaults_installed = False

    def __init__(self, timeout: int = 120, max_memory_mb: int = 4096):
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self._python = self._find_python()

    @staticmethod
    def _find_python() -> str:
        """Locate the venv Python interpreter."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        venv_python = os.path.join(project_root, ".venv", "bin", "python")
        if os.path.isfile(venv_python):
            return venv_python
        return "python3"

    # ------------------------------------------------------------------ #
    #  Import detection & auto-install
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_imports(code: str) -> set:
        """Extract top-level module names from import statements."""
        modules = set()
        import_re = re.compile(
            r"^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE
        )
        for match in import_re.finditer(code):
            modules.add(match.group(1))
        return modules

    def _check_missing(self, modules: set) -> list:
        """Return list of modules that are not importable."""
        missing = []
        for mod in modules:
            if mod in self.STDLIB_MODULES:
                continue
            try:
                result = subprocess.run(
                    [self._python, "-c", f"import {mod}"],
                    capture_output=True, timeout=10,
                )
                if result.returncode != 0:
                    missing.append(mod)
            except Exception:
                missing.append(mod)
        return missing

    def _pip_install(self, packages: list) -> Dict:
        """Pip-install a list of packages. Returns install log."""
        if not packages:
            return {"installed": [], "errors": []}
        installed = []
        errors = []
        for pkg in packages:
            pip_name = self.IMPORT_TO_PIP.get(pkg, pkg)
            logger.info("Auto-installing missing package: %s (pip: %s)", pkg, pip_name)
            try:
                result = subprocess.run(
                    [self._python, "-m", "pip", "install", "--quiet", pip_name],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0:
                    installed.append(pip_name)
                else:
                    err_msg = result.stderr.strip()[-200:]
                    errors.append(f"{pip_name}: {err_msg}")
                    logger.warning("Failed to install %s: %s", pip_name, err_msg)
            except subprocess.TimeoutExpired:
                errors.append(f"{pip_name}: install timed out")
            except Exception as e:
                errors.append(f"{pip_name}: {e}")
        return {"installed": installed, "errors": errors}

    def _ensure_defaults(self):
        """Install default data-science packages once."""
        if LocalCodeExecutor._defaults_installed:
            return
        logger.info("Installing default packages: %s", self.DEFAULT_PACKAGES)
        result = self._pip_install(self.DEFAULT_PACKAGES)
        if result["errors"]:
            logger.warning("Some default packages failed to install: %s", result["errors"])
        else:
            logger.info("All default packages installed successfully")
        # Set flag even with partial failures — _check_missing will catch stragglers
        LocalCodeExecutor._defaults_installed = True

    # ------------------------------------------------------------------ #
    #  Main execute
    # ------------------------------------------------------------------ #
    # Preamble injected before user code when matplotlib is detected.
    # Forces Agg backend and monkey-patches plt.show() AND plt.savefig()
    # to capture figures as PNGs. The savefig patch also redirects writes
    # to non-writable paths (e.g. /mnt/data/ from ChatGPT-style code).
    _MPL_PREAMBLE = textwrap.dedent("""\
        import os as _os, sys as _sys
        _os.environ.setdefault("MPLBACKEND", "Agg")
        import matplotlib as _mpl
        _mpl.use("Agg")
        import matplotlib.pyplot as _plt
        import matplotlib.figure as _mfig
        _omni_plot_dir = _os.environ.get("_OMNI_PLOT_DIR", ".")
        _omni_plot_counter = [0]

        # Patch savefig to ALWAYS capture a copy in our plot dir
        _orig_savefig = _mfig.Figure.savefig
        def _patched_savefig(self, fname, *a, **kw):
            fname_str = str(fname)
            parent = _os.path.dirname(fname_str)
            # If the target dir doesn't exist, redirect to our plot dir
            if parent and not _os.path.isdir(parent):
                base = _os.path.basename(fname_str)
                fname = _os.path.join(_omni_plot_dir, base)
            try:
                _orig_savefig(self, fname, *a, **kw)
            except (OSError, PermissionError):
                base = _os.path.basename(str(fname))
                fname = _os.path.join(_omni_plot_dir, base)
                _orig_savefig(self, fname, *a, **kw)
            # Always save an extra copy in the capture dir for inline display
            capture_name = _os.path.basename(str(fname))
            capture_path = _os.path.join(_omni_plot_dir, capture_name)
            if _os.path.abspath(str(fname)) != _os.path.abspath(capture_path):
                try:
                    _orig_savefig(self, capture_path, *a, **kw)
                except Exception:
                    pass
        _mfig.Figure.savefig = _patched_savefig

        # Patch show to capture all open figures
        _orig_show = _plt.show
        def _patched_show(*a, **kw):
            for _fnum in _plt.get_fignums():
                _fig = _plt.figure(_fnum)
                _omni_plot_counter[0] += 1
                _path = _os.path.join(_omni_plot_dir, f"plot_{_omni_plot_counter[0]}.png")
                _orig_savefig(_fig, _path, dpi=150, bbox_inches="tight", facecolor=_fig.get_facecolor())
            _plt.close("all")
        _plt.show = _patched_show
    """)

    @staticmethod
    def _uses_matplotlib(code: str) -> bool:
        """Check if code imports or uses matplotlib."""
        return bool(re.search(r'\bmatplotlib\b|\bplt\b|\bpyplot\b', code))

    @staticmethod
    def _sanitize_code(code: str, tmpdir: str) -> str:
        """Rewrite known bad paths in user code.

        Many LLMs (especially ChatGPT-trained) produce code that writes to
        /mnt/data/ which doesn't exist locally.  We transparently redirect
        such paths to the execution tmpdir.
        """
        # Replace /mnt/data/ references with the tmpdir
        code = code.replace('/mnt/data/', f'{tmpdir}/')
        code = code.replace('"/mnt/data"', f'"{tmpdir}"')
        code = code.replace("'/mnt/data'", f"'{tmpdir}'")
        return code

    def execute(self, code: str) -> Dict:
        """Run code and return stdout, stderr, and return code.

        Automatically detects and installs missing Python packages.
        If the code uses matplotlib, plots are captured as base64 PNG images.
        """
        # Ensure default packages are available on first run
        self._ensure_defaults()

        # Detect and install any additional missing imports
        imports = self._extract_imports(code)
        missing = self._check_missing(imports)
        install_info = None
        if missing:
            logger.info("Missing modules detected: %s — auto-installing...", missing)
            install_info = self._pip_install(missing)

        exec_id = str(uuid.uuid4())[:8]
        # Environment variables to prevent OpenBLAS/numpy memory issues
        env = os.environ.copy()
        env["OPENBLAS_NUM_THREADS"] = "1"
        env["MKL_NUM_THREADS"] = "1"
        env["OMP_NUM_THREADS"] = "1"

        has_mpl = self._uses_matplotlib(code)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Sanitize known bad paths (e.g. /mnt/data/ from ChatGPT)
            code = self._sanitize_code(code, tmpdir)

            # If matplotlib is used, inject the capture preamble
            if has_mpl:
                env["_OMNI_PLOT_DIR"] = tmpdir
                final_code = self._MPL_PREAMBLE + "\n" + code
            else:
                final_code = code

            script = os.path.join(tmpdir, f"script_{exec_id}.py")
            with open(script, "w") as f:
                f.write(final_code)
            try:
                result = subprocess.run(
                    [self._python, script],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=tmpdir,
                    env=env,
                )
                response = {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                }
                if install_info and install_info["installed"]:
                    response["auto_installed"] = install_info["installed"]

                # Collect any saved plot/chart images as base64
                if has_mpl:
                    import base64 as _b64
                    images = []
                    # Capture ALL image files generated in the tmpdir
                    # (not just plot_* — LLMs often use custom names like chart_btc.png)
                    image_exts = ('.png', '.jpg', '.jpeg', '.svg')
                    plot_files = sorted(
                        f for f in os.listdir(tmpdir)
                        if f.lower().endswith(image_exts) and not f.startswith("script_")
                    )
                    for pf in plot_files:
                        ppath = os.path.join(tmpdir, pf)
                        with open(ppath, "rb") as img_f:
                            images.append(_b64.b64encode(img_f.read()).decode())
                    if images:
                        response["images"] = images

                return response
            except subprocess.TimeoutExpired:
                return {"error": f"Timeout after {self.timeout}s", "returncode": -1}
            except Exception as e:
                return {"error": str(e), "returncode": -1}


class CodeAuditor:
    """Audit code using pylint, bandit, radon + PyCodeAudit scanners.

    Supports two modes:
    - quick: pylint + bandit + radon on a Python code snippet
    - full: all scanners (semgrep, trivy, detect-secrets, depscan,
            pylint, bandit, radon) on a directory or Git repo URL
    """

    # ------------------------------------------------------------------ #
    #  Quick audit (legacy — snippet-based)
    # ------------------------------------------------------------------ #
    def quick_audit(self, code: str) -> Dict:
        """Run pylint, bandit, radon on a code snippet."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_path = f.name
        results = {}
        try:
            tools = [
                ("pylint", ["pylint", "--output-format=json", temp_path]),
                ("bandit", ["bandit", "-f", "json", temp_path]),
                ("radon", ["radon", "cc", "-j", temp_path]),
            ]
            for name, cmd in tools:
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                    results[name] = proc.stdout or proc.stderr
                except FileNotFoundError:
                    results[name] = f"{name} not installed"
                except subprocess.TimeoutExpired:
                    results[name] = f"{name} timed out"
                except Exception as e:
                    results[name] = f"Error: {e}"
        finally:
            os.unlink(temp_path)
        return results

    # Keep backward compat
    def audit(self, code: str) -> Dict:
        return self.quick_audit(code)

    # ------------------------------------------------------------------ #
    #  Full audit — PyCodeAudit scanners
    # ------------------------------------------------------------------ #
    def _clone_repo(self, repo_url: str) -> Path:
        """Clone a git repo to a temporary directory."""
        tmp_dir = Path(tempfile.mkdtemp(prefix="clawzd_audit_"))
        logger.info("Cloning repo %s ...", repo_url)
        try:
            import git
            git.Repo.clone_from(repo_url, tmp_dir)
        except ImportError:
            # Fallback to git CLI
            subprocess.run(["git", "clone", repo_url, str(tmp_dir)],
                           capture_output=True, check=True, timeout=120)
        return tmp_dir

    def run_semgrep(self, path: Path) -> List[Dict]:
        """Run Semgrep with OWASP + extended rules."""
        logger.info("Running Semgrep (OWASP + extended rules)...")
        cmd = [
            "semgrep", "scan",
            "--config", "p/owasp-top-ten",
            "--config", "p/default",
            "--config", "p/secrets",
            "--config", "p/ci",
            "--exclude", ".venv", "--exclude", "venv", "--exclude", "node_modules", "--exclude", ".git",
            "--json", "--metrics=off",
            str(path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    check=False, timeout=300)
            if result.returncode not in (0, 1):
                logger.warning("Semgrep exited with code %d", result.returncode)
                return []
            data = json.loads(result.stdout) if result.stdout.strip() else {}
            findings = data.get("results", [])
            logger.info("Semgrep: %d vulnerabilities found", len(findings))
            return findings
        except FileNotFoundError:
            logger.warning("Semgrep not installed — skipping")
            return []
        except subprocess.TimeoutExpired:
            logger.warning("Semgrep timed out")
            return []
        except Exception as e:
            logger.error("Semgrep error: %s", e)
            return []

    def run_trivy(self, path: Path) -> List[Dict]:
        """Run Trivy (vuln + CIS misconfig + secrets + licenses)."""
        logger.info("Running Trivy...")
        json_file = path / "trivy-report.json"
        cmd = [
            "trivy", "fs",
            "--scanners", "vuln,secret,misconfig,license",
            "--skip-dirs", ".venv", "--skip-dirs", "venv", "--skip-dirs", "node_modules", "--skip-dirs", ".git",
            "--format", "json",
            "--output", str(json_file),
            "--severity", "LOW,MEDIUM,HIGH,CRITICAL",
            str(path),
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True,
                           check=False, timeout=300)
        except FileNotFoundError:
            logger.warning("Trivy not installed — skipping")
            return []
        except subprocess.TimeoutExpired:
            logger.warning("Trivy timed out")
            return []
        except Exception as e:
            logger.error("Trivy error: %s", e)
            return []

        if not json_file.exists():
            return []

        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)
            findings = []
            for res in data.get("Results", []):
                target = res.get("Target", "N/A")
                for v in res.get("Vulnerabilities", []):
                    findings.append({
                        "tool": "trivy", "type": "sca",
                        "severity": v.get("Severity", "MEDIUM").upper(),
                        "file": f"{target} ({v.get('PkgName')})",
                        "line": None,
                        "message": f"{v.get('PkgName')} {v.get('InstalledVersion')} → {v.get('VulnerabilityID')}",
                        "owasp": "A06:2021 - Vulnerable and Outdated Components",
                        "description": v.get("Title", ""),
                    })
                for m in res.get("Misconfigurations", []):
                    findings.append({
                        "tool": "trivy", "type": "misconfig",
                        "severity": m.get("Severity", "MEDIUM").upper(),
                        "file": target,
                        "line": m.get("Location", {}).get("StartLine"),
                        "message": f"{m.get('ID')} - {m.get('Title', m.get('Message', ''))}",
                        "owasp": "A05:2021 - Security Misconfiguration (CIS)",
                        "description": m.get("Message", ""),
                    })
                for s in res.get("Secrets", []):
                    findings.append({
                        "tool": "trivy", "type": "secret",
                        "severity": "HIGH",
                        "file": target,
                        "line": s.get("StartLine"),
                        "message": f"Secret : {s.get('RuleID')}",
                        "owasp": "A02:2021 - Cryptographic Failures",
                        "description": s.get("Category", ""),
                    })
            logger.info("Trivy: %d findings", len(findings))
            return findings
        except Exception as e:
            logger.error("Trivy parse error: %s", e)
            return []
        finally:
            # Clean up temp report file
            if json_file.exists():
                json_file.unlink(missing_ok=True)

    def run_detect_secrets(self, path: Path) -> List[Dict]:
        """Scan for hardcoded secrets using detect-secrets CLI."""
        logger.info("Running detect-secrets...")
        cmd = ["detect-secrets", "scan", "--all-files", "--exclude-files", r"\.venv/|venv/|node_modules/|\.git/", "--json"]
        try:
            result = subprocess.run(cmd, cwd=path, capture_output=True,
                                    text=True, check=False, timeout=120)
        except FileNotFoundError:
            logger.warning("detect-secrets not installed — skipping")
            return []
        except subprocess.TimeoutExpired:
            logger.warning("detect-secrets timed out")
            return []
        except Exception as e:
            logger.error("detect-secrets error: %s", e)
            return []

        try:
            data = json.loads(result.stdout) if result.stdout.strip() else {}
            findings = []
            for filepath, secrets in data.items():
                if not isinstance(secrets, list):
                    continue
                for secret in secrets:
                    findings.append({
                        "tool": "detect-secrets", "type": "secret",
                        "severity": "HIGH",
                        "file": filepath,
                        "line": secret.get("line_number"),
                        "message": f"{secret.get('type', 'SECRET')} detected",
                        "owasp": "A02:2021 - Cryptographic Failures",
                        "description": secret.get("type", ""),
                    })
            logger.info("detect-secrets: %d secrets found", len(findings))
            return findings
        except Exception:
            return []

    def run_depscan(self, path: Path) -> List[Dict]:
        """Run OWASP dep-scan for dependency vulnerabilities."""
        logger.info("Running OWASP dep-scan...")
        reports_dir = path / "reports"
        reports_dir.mkdir(exist_ok=True)
        json_file = reports_dir / "depscan.json"
        cmd = ["depscan", "--src", str(path), "-o", str(json_file)]
        try:
            subprocess.run(cmd, capture_output=True, check=False, timeout=300)
        except FileNotFoundError:
            logger.warning("depscan not installed — skipping")
            return []
        except subprocess.TimeoutExpired:
            logger.warning("depscan timed out")
            return []
        except Exception as e:
            logger.error("depscan error: %s", e)
            return []

        if not json_file.exists():
            return []

        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)
            vulns = data.get("vulnerabilities", []) or data.get("results", [])
            logger.info("dep-scan: %d vulnerabilities found", len(vulns))
            return vulns
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    #  Normalization
    # ------------------------------------------------------------------ #
    def normalize_findings(
        self,
        semgrep_results: List,
        depscan_results: List,
        secrets_results: List,
        trivy_results: List,
    ) -> List[Dict]:
        """Normalize all scanner outputs into a unified format."""
        findings = []
        # Semgrep
        for r in semgrep_results:
            findings.append({
                "tool": "semgrep", "type": "sast",
                "severity": r.get("extra", {}).get("severity", "MEDIUM").upper(),
                "file": r.get("path", ""),
                "line": r.get("start", {}).get("line"),
                "message": r.get("extra", {}).get("message", ""),
                "owasp": r.get("extra", {}).get("metadata", {}).get("owasp", "N/A"),
                "description": r.get("extra", {}).get("message", ""),
            })
        # dep-scan
        for r in depscan_results:
            pkg = r.get("package") or r.get("name") or {}
            name = pkg.get("name") if isinstance(pkg, dict) else str(pkg)
            version = pkg.get("version", "Unknown") if isinstance(pkg, dict) else "Unknown"
            findings.append({
                "tool": "depscan", "type": "sca",
                "severity": r.get("severity", "MEDIUM").upper(),
                "file": name, "line": None,
                "message": f"{name} {version} - {r.get('id', 'N/A')}",
                "owasp": "A06:2021 - Vulnerable and Outdated Components",
                "description": r.get("description", ""),
            })
        # detect-secrets & trivy are already normalized
        findings.extend(secrets_results)
        findings.extend(trivy_results)
        return findings

    # ------------------------------------------------------------------ #
    #  HTML Report
    # ------------------------------------------------------------------ #
    def _save_json_report(self, json_file: Path, findings: List[Dict], path: Path, ts: str, total: int) -> None:
        """Helper to save the findings as a JSON report."""
        with open(json_file, "w", encoding="utf-8") as jf:
            json.dump({"findings": findings, "scanned_path": str(path),
                        "timestamp": ts, "total": total}, jf, indent=2, ensure_ascii=False)

    def _build_html_rows(self, findings: List[Dict]) -> str:
        """Helper to build HTML table rows for findings."""
        rows = ""
        for f in findings:
            sev_class = f"severity-{f.get('severity', 'MEDIUM').lower()}"
            file_short = str(f.get("file", ""))[:60]
            if len(str(f.get("file", ""))) > 60:
                file_short += "..."
            msg_short = str(f.get("message", ""))[:90]
            if len(str(f.get("message", ""))) > 90:
                msg_short += "..."
            rows += (
                f'<tr><td>{f.get("tool","")}</td><td>{f.get("type","")}</td>'
                f'<td><span class="badge {sev_class}">{f.get("severity","MEDIUM")}</span></td>'
                f'<td><small>{file_short}</small></td>'
                f'<td>{f.get("line") or "-"}</td>'
                f'<td>{msg_short}</td></tr>\n'
            )
        return rows

    def _build_html_template(self, path: Path, total: int, ts: str, c: Counter, rows: str) -> str:
        """Helper to assemble the complete HTML document."""
        return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clawzd Audit Report — {path.name}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
body {{ font-family: 'Segoe UI', sans-serif; }}
.severity-critical {{ background-color: #dc3545; color: white; }}
.severity-high {{ background-color: #fd7e14; color: white; }}
.severity-medium {{ background-color: #ffc107; }}
.severity-low {{ background-color: #17a2b8; color: white; }}
</style>
</head>
<body class="bg-light">
<div class="container py-4">
<h1 class="display-5 text-center mb-2">🔍 Clawzd Audit Report</h1>
<p class="text-center text-muted">Scan: <strong>{path}</strong> | {total} findings | {ts}</p>
<div class="row g-3 mb-4">
<div class="col-md-3"><div class="card text-center"><div class="card-body"><h5>Total</h5><h2>{total}</h2></div></div></div>
<div class="col-md-3"><div class="card text-center"><div class="card-body"><h5>CRITICAL</h5><h2 class="text-danger">{c.get('CRITICAL',0)}</h2></div></div></div>
<div class="col-md-3"><div class="card text-center"><div class="card-body"><h5>HIGH</h5><h2 class="text-warning">{c.get('HIGH',0)}</h2></div></div></div>
<div class="col-md-3"><div class="card text-center"><div class="card-body"><h5>MEDIUM</h5><h2>{c.get('MEDIUM',0)}</h2></div></div></div>
</div>
<div class="card mb-4"><div class="card-header">Severity Distribution</div>
<div class="card-body"><canvas id="chart" height="120"></canvas></div></div>
<div class="card"><div class="card-header">Findings Details</div>
<div class="card-body p-0">
<table class="table table-hover mb-0"><thead class="table-dark">
<tr><th>Tool</th><th>Type</th><th>Severity</th><th>File</th><th>Line</th><th>Vulnerability</th></tr>
</thead><tbody>{rows}</tbody></table></div></div>
</div>
<script>
new Chart(document.getElementById('chart'), {{
type:'pie', data:{{labels:['CRITICAL','HIGH','MEDIUM','LOW'],
datasets:[{{data:[{c.get('CRITICAL',0)},{c.get('HIGH',0)},{c.get('MEDIUM',0)},{c.get('LOW',0)}],
backgroundColor:['#dc3545','#fd7e14','#ffc107','#17a2b8']}}]}},
options:{{responsive:true}}}});
</script>
</body></html>"""

    def generate_html_report(self, findings: List[Dict], path: Path, report_id: str) -> Path:
        """Generate a self-contained HTML report with Bootstrap + Chart.js."""
        os.makedirs(REPORTS_DIR, exist_ok=True)
        html_file = Path(REPORTS_DIR) / f"{report_id}.html"
        json_file = Path(REPORTS_DIR) / f"{report_id}.json"

        # Sort findings by severity: CRITICAL > HIGH > MEDIUM > LOW
        _sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        findings = sorted(findings, key=lambda f: _sev_order.get(f.get("severity", "MEDIUM"), 99))
        severity_count = Counter(f.get("severity", "MEDIUM") for f in findings)
        total = len(findings)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Save JSON
        self._save_json_report(json_file, findings, path, ts, total)

        # Build findings rows
        rows = self._build_html_rows(findings)

        # Build HTML
        html = self._build_html_template(path, total, ts, severity_count, rows)

        with open(html_file, "w", encoding="utf-8") as hf:
            hf.write(html)
        logger.info("HTML report generated: %s", html_file)
        return html_file

    # ------------------------------------------------------------------ #
    #  Run pylint / bandit / radon on all Python files in a directory
    # ------------------------------------------------------------------ #
    def run_pylint_dir(self, path: Path) -> List[Dict]:
        """Run pylint on all Python files in a directory."""
        py_files = list(path.rglob("*.py"))
        # Exclude common non-project dirs
        excludes = {".venv", "venv", ".env", "__pycache__", "node_modules", ".git", "chroma_db", "data"}
        py_files = [f for f in py_files if not any(ex in f.parts for ex in excludes)]
        if not py_files:
            return []
        logger.info("Running pylint on %d Python files...", len(py_files))
        findings = []
        # Run pylint on batches to avoid argument length limits
        batch_size = 20
        for i in range(0, len(py_files), batch_size):
            batch = [str(f) for f in py_files[i:i + batch_size]]
            try:
                proc = subprocess.run(
                    ["pylint", "--output-format=json", "--disable=C0114,C0115,C0116",
                     "--max-line-length=120", "--jobs=0"] + batch,
                    capture_output=True, text=True, timeout=120, cwd=str(path),
                )
                if proc.stdout.strip():
                    try:
                        issues = json.loads(proc.stdout)
                        for issue in issues:
                            sev_map = {"fatal": "CRITICAL", "error": "HIGH",
                                       "warning": "MEDIUM", "convention": "LOW",
                                       "refactor": "LOW", "info": "LOW"}
                            findings.append({
                                "tool": "pylint", "type": "quality",
                                "severity": sev_map.get(issue.get("type", ""), "MEDIUM"),
                                "file": issue.get("path", ""),
                                "line": issue.get("line"),
                                "message": f"[{issue.get('message-id', '')}] {issue.get('message', '')}",
                                "owasp": "N/A",
                                "description": issue.get("symbol", ""),
                            })
                    except json.JSONDecodeError:
                        pass
            except FileNotFoundError:
                logger.warning("pylint not installed — skipping")
                return []
            except subprocess.TimeoutExpired:
                logger.warning("pylint timed out on batch %d", i // batch_size)
            except Exception as e:
                logger.error("pylint error: %s", e)
        logger.info("pylint: %d findings", len(findings))
        return findings

    def run_bandit_dir(self, path: Path) -> List[Dict]:
        """Run bandit on all Python files in a directory."""
        logger.info("Running bandit on %s...", path)
        findings = []
        try:
            proc = subprocess.run(
                ["bandit", "-r", str(path), "-f", "json",
                 "--exclude", ".venv,venv,.env,__pycache__,node_modules,.git,chroma_db,data"],
                capture_output=True, text=True, timeout=120,
            )
            output = proc.stdout.strip()
            if output:
                try:
                    data = json.loads(output)
                    for issue in data.get("results", []):
                        sev_map = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}
                        findings.append({
                            "tool": "bandit", "type": "security",
                            "severity": sev_map.get(issue.get("issue_severity", ""), "MEDIUM"),
                            "file": issue.get("filename", ""),
                            "line": issue.get("line_number"),
                            "message": f"[{issue.get('test_id', '')}] {issue.get('issue_text', '')}",
                            "owasp": "N/A",
                            "description": issue.get("issue_text", ""),
                        })
                except json.JSONDecodeError:
                    pass
        except FileNotFoundError:
            logger.warning("bandit not installed — skipping")
        except subprocess.TimeoutExpired:
            logger.warning("bandit timed out")
        except Exception as e:
            logger.error("bandit error: %s", e)
        logger.info("bandit: %d findings", len(findings))
        return findings

    def run_radon_dir(self, path: Path) -> List[Dict]:
        """Run radon complexity check on all Python files in a directory."""
        logger.info("Running radon on %s...", path)
        findings = []
        try:
            proc = subprocess.run(
                ["radon", "cc", "-s", "-j",
                 "--exclude", ".venv,venv,.env,__pycache__,node_modules,.git,chroma_db,data",
                 str(path)],
                capture_output=True, text=True, timeout=120,
            )
            output = proc.stdout.strip()
            if output:
                try:
                    data = json.loads(output)
                    for filepath, blocks in data.items():
                        if not isinstance(blocks, list):
                            continue
                        for block in blocks:
                            rank = block.get("rank", "A")
                            if rank in ("A", "B"):
                                continue  # Only report C+ complexity
                            sev = {"C": "LOW", "D": "MEDIUM", "E": "HIGH", "F": "CRITICAL"}.get(rank, "MEDIUM")
                            findings.append({
                                "tool": "radon", "type": "complexity",
                                "severity": sev,
                                "file": filepath,
                                "line": block.get("lineno"),
                                "message": f"{block.get('type', '')} '{block.get('name', '')}' — complexity {block.get('complexity', '?')} (rank {rank})",
                                "owasp": "N/A",
                                "description": f"Cyclomatic complexity rank {rank}",
                            })
                except json.JSONDecodeError:
                    pass
        except FileNotFoundError:
            logger.warning("radon not installed — skipping")
        except subprocess.TimeoutExpired:
            logger.warning("radon timed out")
        except Exception as e:
            logger.error("radon error: %s", e)
        logger.info("radon: %d findings", len(findings))
        return findings

    # ------------------------------------------------------------------ #
    #  Full audit orchestration
    # ------------------------------------------------------------------ #
    def full_audit(self, target: str, progress_cb=None) -> Dict:
        """Run all available scanners on a directory or Git URL.

        Scanners: pylint, bandit, radon (always), then semgrep, trivy,
        detect-secrets, depscan (if installed).
        """
        cleanup = False
        if target.startswith(("http://", "https://")):
            scan_path = self._clone_repo(target)
            cleanup = True
        else:
            scan_path = Path(target).resolve()
            if not scan_path.exists():
                return {"error": f"Path not found: {target}"}

        report_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:6]
        scanners_used = []

        try:
            logger.info("Full audit started on: %s", scan_path)
            if progress_cb: progress_cb({"status": "progress", "message": f"Starting audit on {scan_path}"})

            # --- Core scanners (pylint / bandit / radon) ---
            if progress_cb: progress_cb({"status": "progress", "message": "Running Pylint (code quality)..."})
            pylint_res = self.run_pylint_dir(scan_path)
            if pylint_res:
                scanners_used.append("pylint")
                if progress_cb: progress_cb({"status": "progress", "message": f"Pylint: {len(pylint_res)} issues found"})

            if progress_cb: progress_cb({"status": "progress", "message": "Running Bandit (Python security)..."})
            bandit_res = self.run_bandit_dir(scan_path)
            if bandit_res:
                scanners_used.append("bandit")
                if progress_cb: progress_cb({"status": "progress", "message": f"Bandit: {len(bandit_res)} vulnerabilities found"})

            if progress_cb: progress_cb({"status": "progress", "message": "Running Radon (cyclomatic complexity)..."})
            radon_res = self.run_radon_dir(scan_path)
            if radon_res:
                scanners_used.append("radon")
                if progress_cb: progress_cb({"status": "progress", "message": f"Radon: {len(radon_res)} complex functions found"})

            # --- Advanced scanners (optional, may not be installed) ---
            if progress_cb: progress_cb({"status": "progress", "message": "Running Semgrep (advanced SAST)..."})
            semgrep_res = self.run_semgrep(scan_path)
            if semgrep_res:
                scanners_used.append("semgrep")
                if progress_cb: progress_cb({"status": "progress", "message": f"Semgrep: {len(semgrep_res)} issues found"})

            if progress_cb: progress_cb({"status": "progress", "message": "Running Trivy (SCA & Misconfig)..."})
            trivy_res = self.run_trivy(scan_path)
            if trivy_res:
                scanners_used.append("trivy")
                if progress_cb: progress_cb({"status": "progress", "message": f"Trivy: {len(trivy_res)} vulnerabilities found"})

            if progress_cb: progress_cb({"status": "progress", "message": "Searching for secrets with detect-secrets..."})
            secrets_res = self.run_detect_secrets(scan_path)
            if secrets_res:
                scanners_used.append("detect-secrets")
                if progress_cb: progress_cb({"status": "progress", "message": f"detect-secrets: {len(secrets_res)} secrets detected"})

            if progress_cb: progress_cb({"status": "progress", "message": "Checking dependencies with dep-scan..."})
            depscan_res = self.run_depscan(scan_path)
            if depscan_res:
                scanners_used.append("depscan")
                if progress_cb: progress_cb({"status": "progress", "message": f"dep-scan: {len(depscan_res)} vulnerabilities found"})

            if progress_cb: progress_cb({"status": "progress", "message": "Generating global report..."})

            # Merge all findings
            findings = pylint_res + bandit_res + radon_res
            findings += self.normalize_findings(semgrep_res, depscan_res, secrets_res, trivy_res)

            # Sort findings by severity: CRITICAL > HIGH > MEDIUM > LOW
            _sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
            findings.sort(key=lambda f: _sev_order.get(f.get("severity", "MEDIUM"), 99))

            severity_count = Counter(f.get("severity", "MEDIUM") for f in findings)
            tool_count = Counter(f.get("tool", "unknown") for f in findings)

            # Generate reports
            self.generate_html_report(findings, scan_path, report_id)

            logger.info("Full audit complete: %d findings from %s", len(findings), scanners_used)

            return {
                "report_id": report_id,
                "scanned_path": str(scan_path),
                "total_findings": len(findings),
                "severity": dict(severity_count),
                "by_tool": dict(tool_count),
                "scanners_used": scanners_used,
                "findings": findings,
                "report_html_url": f"/code/audit/report/{report_id}?format=html",
                "report_json_url": f"/code/audit/report/{report_id}?format=json",
            }
        finally:
            if cleanup:
                shutil.rmtree(scan_path, ignore_errors=True)


executor = LocalCodeExecutor()
auditor = CodeAuditor()


@router.post("/execute")
async def execute_code(request: Request):
    """Execute Python code in sandbox."""
    data = await request.json()
    code = data.get("code", "")
    if not code.strip():
        return {"error": "No code provided", "returncode": -1}
    return executor.execute(code)


@router.post("/audit")
async def audit_code(request: Request):
    """Audit code — supports two modes.

    Body params:
    - mode: "quick" (default) or "full"
    - code: Python code snippet (for quick mode)
    - target: directory path or Git URL (for full mode)
    - stream: boolean (optional) to stream progress via NDJSON
    """
    data = await request.json()
    mode = data.get("mode", "quick")
    stream = data.get("stream", False)

    if mode == "full":
        target = data.get("target", "")
        if not target:
            return JSONResponse({"error": "target is required for full audit"}, 400)
            
        if stream:
            import threading
            import queue
            q = queue.Queue()
            
            def cb(msg):
                q.put(msg)
                
            def worker():
                try:
                    result = auditor.full_audit(target, progress_cb=cb)
                    
                    # --- Save audit results to audit.md in workspace ---
                    try:
                        from config import WORKSPACE_DIR
                        from datetime import datetime, timezone
                        audit_md_path = os.path.join(WORKSPACE_DIR, "audit.md")
                        os.makedirs(WORKSPACE_DIR, exist_ok=True)
                        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                        md_lines = [f"# Code Audit Report\n", f"*Generated: {timestamp}*\n\n"]
                        if isinstance(result, dict) and "findings" in result:
                            md_lines.append("## Findings Summary\n\n")
                            for f in result.get("findings", [])[:20]:
                                sev = f.get("severity", "info").lower()
                                icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(sev, "⚪")
                                md_lines.append(f"- {icon} **{sev.upper()}**: {f.get('message', '')}\n")
                        with open(audit_md_path, "w") as f:
                            f.writelines(md_lines)
                    except Exception:
                        pass
                        
                    q.put({"status": "done", "result": result})
                except Exception as e:
                    q.put({"status": "error", "error": str(e)})

            threading.Thread(target=worker, daemon=True).start()

            from fastapi.responses import StreamingResponse
            async def generate():
                while True:
                    try:
                        msg = q.get(timeout=0.1)
                        yield json.dumps(msg) + "\n"
                        if msg.get("status") in ("done", "error"):
                            break
                    except queue.Empty:
                        yield " \n" # Keepalive
            return StreamingResponse(generate(), media_type="application/x-ndjson")
        else:
            result = auditor.full_audit(target)
    else:
        code = data.get("code", "")
        if not code.strip():
            return {"error": "No code provided"}
        result = auditor.audit(code)

    # --- Save audit results to audit.md in workspace ---
    try:
        from config import WORKSPACE_DIR
        from datetime import datetime, timezone
        audit_md_path = os.path.join(WORKSPACE_DIR, "audit.md")
        os.makedirs(WORKSPACE_DIR, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        md_lines = [f"# Code Audit Report\n", f"*Generated: {timestamp}*\n\n"]

        if isinstance(result, dict):
            # Quick audit format
            if "pylint" in result:
                md_lines.append("## Pylint (Quality)\n```\n")
                md_lines.append(str(result.get("pylint", {}).get("output", ""))[:2000])
                md_lines.append("\n```\n\n")
            if "bandit" in result:
                md_lines.append("## Bandit (Security)\n```\n")
                md_lines.append(str(result.get("bandit", {}).get("output", ""))[:2000])
                md_lines.append("\n```\n\n")
            if "radon" in result:
                md_lines.append("## Radon (Complexity)\n```\n")
                md_lines.append(str(result.get("radon", {}).get("output", ""))[:2000])
                md_lines.append("\n```\n\n")
            if "findings" in result:
                md_lines.append("## Findings Summary\n\n")
                for f in result.get("findings", [])[:20]:
                    sev = f.get("severity", "info")
                    icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(sev.lower(), "⚪")
                    md_lines.append(f"- {icon} **{sev.upper()}**: {f.get('message', '')}\n")

        with open(audit_md_path, "w") as f:
            f.writelines(md_lines)
    except Exception:
        pass  # Non-critical

    return result


@router.get("/audit/history")
async def audit_history():
    """List all past audit reports with summary metadata."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    reports = []
    for fname in sorted(os.listdir(REPORTS_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        report_id = fname[:-5]  # strip .json
        fpath = os.path.join(REPORTS_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
            findings = data.get("findings", [])
            sev_count = Counter(f.get("severity", "MEDIUM") for f in findings)
            reports.append({
                "report_id": report_id,
                "timestamp": data.get("timestamp", ""),
                "scanned_path": data.get("scanned_path", ""),
                "total": data.get("total", len(findings)),
                "severity": dict(sev_count),
                "has_html": os.path.exists(os.path.join(REPORTS_DIR, f"{report_id}.html")),
            })
        except Exception:
            # Corrupt JSON — list it with minimal info
            reports.append({
                "report_id": report_id,
                "timestamp": "",
                "scanned_path": "",
                "total": 0,
                "severity": {},
                "has_html": os.path.exists(os.path.join(REPORTS_DIR, f"{report_id}.html")),
            })
    return {"reports": reports}


@router.get("/audit/report/{report_id}")
async def get_audit_report(report_id: str, format: str = "html"):
    """Download a generated audit report (HTML or JSON)."""
    ext = "html" if format == "html" else "json"
    report_path = os.path.join(REPORTS_DIR, f"{report_id}.{ext}")
    if not os.path.exists(report_path):
        return JSONResponse({"error": "Report not found"}, 404)
    media = "text/html" if ext == "html" else "application/json"
    return FileResponse(report_path, media_type=media,
                        filename=f"clawzd-audit-{report_id}.{ext}")


class FileSnapshotManager:
    """Maintain per-file undo history so AI edits can be reverted.

    Stores snapshots in data/snapshots/ as JSON files.  Each file keeps up
    to MAX_SNAPSHOTS entries (FIFO).  Snapshots are taken automatically by
    CodeEditor.edit_file() before any write.
    """

    MAX_SNAPSHOTS = 50

    def __init__(self):
        self._dir = os.path.join(DATA_DIR, "snapshots")
        os.makedirs(self._dir, exist_ok=True)

    def _key(self, file_path: str) -> str:
        """Convert a workspace-relative path to a safe filename key."""
        return file_path.replace("/", "__").replace("\\", "__")

    def _history_path(self, file_path: str) -> str:
        return os.path.join(self._dir, self._key(file_path) + ".json")

    def _load_history(self, file_path: str) -> List[Dict]:
        hp = self._history_path(file_path)
        if not os.path.exists(hp):
            return []
        try:
            with open(hp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_history(self, file_path: str, history: List[Dict]):
        hp = self._history_path(file_path)
        with open(hp, "w", encoding="utf-8") as f:
            json.dump(history[-self.MAX_SNAPSHOTS:], f, ensure_ascii=False)

    def save(self, file_path: str):
        """Snapshot the current content of *file_path* (workspace-relative)."""
        full_path = os.path.join(WORKSPACE_DIR, file_path)
        if not os.path.isfile(full_path):
            return
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            history = self._load_history(file_path)
            history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": content,
            })
            self._save_history(file_path, history)
            logger.debug("Snapshot saved for %s (%d entries)", file_path, len(history))
        except Exception as e:
            logger.warning("Failed to snapshot %s: %s", file_path, e)

    def undo(self, file_path: str) -> Dict:
        """Restore the most recent snapshot for *file_path*."""
        history = self._load_history(file_path)
        if not history:
            return {"error": f"No undo history for '{file_path}'."}
        snapshot = history.pop()
        self._save_history(file_path, history)
        full_path = os.path.join(WORKSPACE_DIR, file_path)
        try:
            # Read current content for diff
            current = ""
            if os.path.isfile(full_path):
                with open(full_path, "r", encoding="utf-8") as f:
                    current = f.read()
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(snapshot["content"])
            diff = list(difflib.unified_diff(
                current.splitlines(keepends=True),
                snapshot["content"].splitlines(keepends=True),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                n=3,
            ))
            return {
                "status": "success",
                "file_path": file_path,
                "message": f"Reverted to snapshot from {snapshot['timestamp']}.",
                "remaining_snapshots": len(history),
                "diff": "".join(diff),
            }
        except Exception as e:
            return {"error": f"Undo failed: {e}"}

    def undo_last(self) -> Dict:
        """Undo the most recent edit across ALL files (global undo)."""
        latest_file = None
        latest_ts = ""
        # Find the file with the most recent snapshot
        for fname in os.listdir(self._dir):
            if not fname.endswith(".json"):
                continue
            fp = os.path.join(self._dir, fname)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    history = json.load(f)
                if history and history[-1]["timestamp"] > latest_ts:
                    latest_ts = history[-1]["timestamp"]
                    latest_file = fname.removesuffix(".json").replace("__", "/")
            except Exception:
                continue
        if not latest_file:
            return {"error": "No undo history available."}
        return self.undo(latest_file)

    def list_history(self, file_path: str) -> Dict:
        """List available snapshots for a file."""
        history = self._load_history(file_path)
        return {
            "file_path": file_path,
            "snapshots": len(history),
            "entries": [
                {"index": i, "timestamp": h["timestamp"], "size": len(h["content"])}
                for i, h in enumerate(history)
            ],
        }


snapshot_manager = FileSnapshotManager()


class CodeEditor:
    """Tool for surgical file editing and reading to avoid full-file rewrites."""

    # File type detection map (extension -> language name for syntax highlighting)
    _EXT_MAP: dict[str, str] = {
        "py": "python", "js": "javascript", "ts": "typescript",
        "jsx": "jsx", "tsx": "tsx", "html": "html", "css": "css",
        "json": "json", "yaml": "yaml", "yml": "yaml",
        "md": "markdown", "sh": "bash", "sql": "sql",
        "txt": "text", "rs": "rust", "go": "go",
        "java": "java", "cpp": "cpp", "c": "c", "rb": "ruby",
    }
    # Max lines returned per read_file call (prevents overwhelming the LLM context)
    _MAX_LINES_PER_READ: int = 500

    @staticmethod
    def read_file(file_path: str, start_line: int = 1, end_line: Optional[int] = None) -> Dict:
        """Read a file and return its contents with line numbers.

        Enhanced with pagination metadata (has_more, file_type, tokens_approx)
        inspired by Claude Code's FileReadTool.
        """
        full_path = os.path.join(WORKSPACE_DIR, file_path)
        if not os.path.exists(full_path):
            return {"error": f"File '{file_path}' not found."}
        if not os.path.isfile(full_path):
            return {"error": f"'{file_path}' is not a regular file."}

        # Detect file type from extension
        ext = os.path.splitext(file_path)[-1].lstrip(".").lower()
        file_type = CodeEditor._EXT_MAP.get(ext, ext or "text")

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)
            start_idx = max(0, start_line - 1)

            if end_line is None:
                # Default: read up to _MAX_LINES_PER_READ from start
                end_idx = min(total_lines, start_idx + CodeEditor._MAX_LINES_PER_READ)
            else:
                end_idx = min(total_lines, end_line)

            has_more = end_idx < total_lines

            # Format with line numbers to help the AI
            formatted_lines = []
            for i, line in enumerate(lines[start_idx:end_idx], start=start_idx + 1):
                formatted_lines.append(f"{i:4d} | {line}")

            content = "".join(formatted_lines)
            actual_start = start_idx + 1
            actual_end = start_idx + len(formatted_lines)

            return {
                "file_path": file_path,
                "file_type": file_type,
                "total_lines": total_lines,
                "shown_lines": f"{actual_start}-{actual_end}",
                "has_more": has_more,
                "next_start_line": actual_end + 1 if has_more else None,
                "tokens_approx": len(content) // 4,
                "content": content,
            }
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}


    @staticmethod
    def edit_file(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> Dict:
        """Surgically replace old_string with new_string in a file."""
        full_path = os.path.join(WORKSPACE_DIR, file_path)
        
        # Handle file creation
        if not os.path.exists(full_path):
            if old_string:
                return {"error": f"File '{file_path}' does not exist. To create a new file, leave old_string empty."}
            
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            try:
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(new_string)
                return {
                    "status": "success",
                    "file_path": file_path,
                    "message": "File created.",
                    "diff": f"--- /dev/null\n+++ {file_path}\n@@ -0,0 +1 @@\n+{new_string}"
                }
            except Exception as e:
                return {"error": f"Failed to create file: {e}"}

        # Handle existing file edit
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Snapshot before modifying (for undo support)
            snapshot_manager.save(file_path)
                
            if old_string == "":
                if content.strip() != "":
                    return {"error": "Cannot use empty old_string on a non-empty file."}
                # Empty file, can replace empty string with new_string
            elif old_string not in content:
                # Try handling trailing newlines gracefully
                if old_string + "\n" in content:
                    old_string += "\n"
                elif old_string.rstrip("\n") in content:
                    old_string = old_string.rstrip("\n")
                else:
                    return {"error": "old_string not found in file. Please ensure exact match, including spaces/indentation."}
                    
            count = content.count(old_string) if old_string else 0
            if count > 1 and not replace_all:
                return {"error": f"old_string found {count} times in file. Make the old_string more unique to match only one occurrence, or set replace_all=True."}
                
            new_content = content.replace(old_string, new_string) if replace_all or not old_string else content.replace(old_string, new_string, 1)
            
            # Generate diff
            diff = list(difflib.unified_diff(
                content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                n=3
            ))
            diff_text = "".join(diff)
            
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            # Count meaningful changes for the frontend diff viewer
            lines_added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
            lines_removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

            return {
                "status": "success",
                "file_path": file_path,
                "message": f"Replaced {count if replace_all else 1} occurrence(s)." if old_string else "Wrote to empty file.",
                "diff": diff_text,
                "lines_added": lines_added,
                "lines_removed": lines_removed,
                "lines_changed": lines_added + lines_removed,
                "show_diff": bool(diff_text),  # hint to frontend to render diff viewer
            }
        except Exception as e:
            return {"error": f"Failed to edit file: {e}"}

editor = CodeEditor()