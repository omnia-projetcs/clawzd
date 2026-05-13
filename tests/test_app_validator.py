"""
Tests for app_validator — validates HTML/CSS/JS before publishing.

Covers:
  - Valid code passes
  - Broken HTML (unclosed tags, missing structure) is caught
  - Broken CSS (unbalanced braces) is caught
  - Broken JS (syntax errors) is caught via Node.js --check
  - Combined validate_app_files integrates all checks
  - Executor rejects invalid code and returns errors to the LLM
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

_TEMP_DATA = tempfile.mkdtemp(prefix="clawzd_test_val_")
os.environ.setdefault("DATA_DIR", _TEMP_DATA)
import config
config.DATA_DIR = _TEMP_DATA


from app.core.app_validator import (
    validate_html,
    validate_css,
    validate_js,
    validate_app_files,
)


# ====================================================================
# HTML Validation
# ====================================================================

class TestValidateHtml(unittest.TestCase):

    def test_valid_full_html(self):
        html = '<!DOCTYPE html><html><head><title>T</title></head><body><h1>Hi</h1></body></html>'
        errs = validate_html(html, "index.html")
        self.assertEqual(errs, [], f"Valid HTML should pass: {errs}")

    def test_missing_doctype(self):
        html = '<html><head></head><body></body></html>'
        errs = validate_html(html, "index.html")
        self.assertTrue(any("DOCTYPE" in e for e in errs), "Should flag missing DOCTYPE")

    def test_missing_head(self):
        html = '<!DOCTYPE html><html><body></body></html>'
        errs = validate_html(html, "index.html")
        self.assertTrue(any("head" in e.lower() for e in errs), "Should flag missing <head>")

    def test_missing_body(self):
        html = '<!DOCTYPE html><html><head></head></html>'
        errs = validate_html(html, "index.html")
        self.assertTrue(any("body" in e.lower() for e in errs), "Should flag missing <body>")

    def test_unclosed_div(self):
        html = '<!DOCTYPE html><html><head></head><body><div><p>text</p></body></html>'
        errs = validate_html(html, "index.html")
        self.assertTrue(any("nclosed" in e.lower() or "div" in e.lower() for e in errs),
                        f"Should flag unclosed <div>: {errs}")

    def test_extra_closing_tag(self):
        html = '<!DOCTYPE html><html><head></head><body></div></body></html>'
        errs = validate_html(html, "index.html")
        self.assertTrue(len(errs) > 0, "Should flag extra closing tag")

    def test_void_tags_ok(self):
        """Self-closing tags like <br>, <img>, <input> should not cause errors."""
        html = '<!DOCTYPE html><html><head><meta charset="UTF-8"><link rel="stylesheet" href="s.css"></head><body><br><img src="x.png"><input type="text"><hr></body></html>'
        errs = validate_html(html, "index.html")
        self.assertEqual(errs, [], f"Void tags should not cause errors: {errs}")

    def test_empty_html(self):
        errs = validate_html("", "index.html")
        self.assertTrue(any("empty" in e.lower() for e in errs))

    def test_non_index_html_relaxed(self):
        """Non-index.html files should not require DOCTYPE/html/head/body."""
        html = '<div class="widget"><p>Hello</p></div>'
        errs = validate_html(html, "widget.html")
        self.assertEqual(errs, [], "Non-index HTML should be lenient on structure")


# ====================================================================
# CSS Validation
# ====================================================================

class TestValidateCss(unittest.TestCase):

    def test_valid_css(self):
        css = "body { color: red; background: #000; } .box { display: flex; }"
        errs = validate_css(css)
        self.assertEqual(errs, [], f"Valid CSS should pass: {errs}")

    def test_unclosed_brace(self):
        css = "body { color: red; .box { display: flex; }"
        errs = validate_css(css)
        self.assertTrue(any("unclosed" in e.lower() or "brace" in e.lower() for e in errs),
                        f"Should flag unclosed brace: {errs}")

    def test_extra_closing_brace(self):
        css = "body { color: red; } } .box { display: flex; }"
        errs = validate_css(css)
        self.assertTrue(any("extra" in e.lower() or "brace" in e.lower() for e in errs),
                        f"Should flag extra closing brace: {errs}")

    def test_empty_css_ok(self):
        """Empty CSS is acceptable (template may not need styles)."""
        errs = validate_css("")
        self.assertEqual(errs, [])

    def test_css_with_comments(self):
        css = "/* Reset */ * { margin: 0; padding: 0; box-sizing: border-box; } /* End */"
        errs = validate_css(css)
        self.assertEqual(errs, [], f"CSS with comments should pass: {errs}")

    def test_media_queries_ok(self):
        css = "@media (max-width: 768px) { .container { width: 100%; } }"
        errs = validate_css(css)
        self.assertEqual(errs, [], f"Media queries should pass: {errs}")


# ====================================================================
# JavaScript Validation
# ====================================================================

class TestValidateJs(unittest.TestCase):

    def test_valid_js(self):
        js = 'const x = 42;\nconsole.log("Hello", x);\nfunction add(a, b) { return a + b; }'
        errs = validate_js(js)
        self.assertEqual(errs, [], f"Valid JS should pass: {errs}")

    def test_syntax_error_missing_paren(self):
        js = 'function broken( { return 1; }'
        errs = validate_js(js)
        self.assertTrue(len(errs) > 0, f"Should catch missing paren: {errs}")

    def test_syntax_error_unexpected_token(self):
        js = 'const x = ;'
        errs = validate_js(js)
        self.assertTrue(len(errs) > 0, f"Should catch unexpected token: {errs}")

    def test_unclosed_brace(self):
        js = 'function test() { if (true) { console.log("x");'
        errs = validate_js(js)
        self.assertTrue(len(errs) > 0, f"Should catch unclosed brace: {errs}")

    def test_empty_js_ok(self):
        errs = validate_js("")
        self.assertEqual(errs, [])

    def test_valid_es6(self):
        js = '''
const arr = [1, 2, 3];
const doubled = arr.map(x => x * 2);
const obj = { ...{a: 1}, b: 2 };
class Game {
  constructor() { this.score = 0; }
  update() { this.score++; }
}
'''
        errs = validate_js(js)
        self.assertEqual(errs, [], f"ES6 code should pass: {errs}")

    def test_template_literals_ok(self):
        js = 'const msg = `Hello ${name}, you have ${count} items`;'
        errs = validate_js(js)
        self.assertEqual(errs, [], f"Template literals should pass: {errs}")


# ====================================================================
# Combined validate_app_files
# ====================================================================

class TestValidateAppFiles(unittest.TestCase):

    def test_valid_app(self):
        files = {
            "index.html": '<!DOCTYPE html><html><head><title>App</title><link rel="stylesheet" href="style.css"></head><body><div id="app"></div><script src="app.js"></script></body></html>',
            "style.css": "body { margin: 0; background: #0f172a; color: #e2e8f0; }",
            "app.js": 'document.getElementById("app").textContent = "Hello World";',
        }
        result = validate_app_files(files)
        self.assertTrue(result["valid"], f"Valid app should pass: {result['errors']}")
        self.assertEqual(result["errors"], [])

    def test_broken_html_blocks_app(self):
        files = {
            "index.html": "<html><body><div>",  # missing DOCTYPE, unclosed div
            "style.css": "body { color: red; }",
            "app.js": 'console.log("ok");',
        }
        result = validate_app_files(files)
        self.assertFalse(result["valid"], "Broken HTML should block app creation")
        self.assertTrue(len(result["errors"]) > 0)

    def test_broken_js_blocks_app(self):
        files = {
            "index.html": '<!DOCTYPE html><html><head></head><body></body></html>',
            "app.js": 'function broken( { return; }',  # syntax error
        }
        result = validate_app_files(files)
        self.assertFalse(result["valid"], "Broken JS should block app creation")

    def test_broken_css_blocks_app(self):
        files = {
            "index.html": '<!DOCTYPE html><html><head></head><body></body></html>',
            "style.css": "body { color: red; .broken {",  # unclosed
        }
        result = validate_app_files(files)
        self.assertFalse(result["valid"], "Broken CSS should block app creation")

    def test_only_html_no_css_js_ok(self):
        """App with only index.html should still pass."""
        files = {
            "index.html": '<!DOCTYPE html><html><head><title>Simple</title></head><body><h1>Hello</h1></body></html>',
        }
        result = validate_app_files(files)
        self.assertTrue(result["valid"], f"HTML-only app should pass: {result['errors']}")


# ====================================================================
# Integration: executor rejects bad code
# ====================================================================

class TestExecutorValidation(unittest.TestCase):
    """Test that the executor blocks invalid code from being published."""

    def test_executor_rejects_broken_js(self):
        """create_app with broken JS should return error, not create the app."""
        import asyncio
        from app.tools.executor import execute_tool

        params = {
            "name": "Broken App",
            "files": {
                "index.html": '<!DOCTYPE html><html><head></head><body></body></html>',
                "app.js": "function broken( { return; }",
            },
        }
        result = asyncio.get_event_loop().run_until_complete(
            execute_tool("create_app", params, {})
        )
        self.assertIn("error", result, "Should return an error for broken JS")
        self.assertIn("validation", result["error"].lower())

    def test_executor_accepts_valid_code(self):
        """create_app with valid code should succeed."""
        import asyncio
        from app.core import app_builder
        app_builder.APPS_DIR = os.path.join(_TEMP_DATA, "apps")
        os.makedirs(app_builder.APPS_DIR, exist_ok=True)

        from app.tools.executor import execute_tool

        params = {
            "name": "Good App",
            "files": {
                "index.html": '<!DOCTYPE html><html><head><title>Good</title></head><body><h1>Works</h1></body></html>',
                "style.css": "body { margin: 0; }",
                "app.js": 'console.log("app loaded");',
            },
        }
        result = asyncio.get_event_loop().run_until_complete(
            execute_tool("create_app", params, {})
        )
        self.assertNotIn("error", result, f"Valid code should succeed: {result}")
        self.assertIn("id", result)
        self.assertTrue(result["id"].startswith("app-"))

    def test_executor_rejects_broken_update(self):
        """update_app with broken CSS should return error."""
        import asyncio
        from app.core import app_builder
        app_builder.APPS_DIR = os.path.join(_TEMP_DATA, "apps")
        os.makedirs(app_builder.APPS_DIR, exist_ok=True)

        from app.tools.executor import execute_tool

        # First create a valid app
        create_result = asyncio.get_event_loop().run_until_complete(
            execute_tool("create_app", {
                "name": "Update Test",
                "files": {
                    "index.html": '<!DOCTYPE html><html><head></head><body></body></html>',
                    "style.css": "body { color: red; }",
                },
            }, {})
        )
        app_id = create_result["id"]

        # Try to update with broken CSS
        update_result = asyncio.get_event_loop().run_until_complete(
            execute_tool("update_app", {
                "app_id": app_id,
                "files": {"style.css": "body { color: red; .broken {"},
            }, {})
        )
        self.assertIn("error", update_result, "Should reject broken CSS on update")


def cleanup():
    if os.path.isdir(_TEMP_DATA):
        shutil.rmtree(_TEMP_DATA, ignore_errors=True)


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2, exit=False)
    finally:
        cleanup()
