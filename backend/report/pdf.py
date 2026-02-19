"""Optional PDF report generator."""

from __future__ import annotations

import base64
import io


def generate_pdf(markdown_text: str) -> str:
    """Convert markdown to PDF and return base64-encoded string.

    Requires weasyprint or similar. Returns base64 string.
    """
    try:
        import markdown
        from weasyprint import HTML

        html_content = f"""
        <html><head><style>
        body {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; padding: 40px; color: #333; }}
        h1 {{ font-size: 24px; border-bottom: 2px solid #333; padding-bottom: 8px; }}
        h2 {{ font-size: 18px; margin-top: 24px; }}
        h3 {{ font-size: 14px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f5f5f5; }}
        code {{ background: #f5f5f5; padding: 2px 4px; }}
        </style></head><body>
        {markdown.markdown(markdown_text, extensions=['tables'])}
        </body></html>
        """

        buf = io.BytesIO()
        HTML(string=html_content).write_pdf(buf)
        return base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        raise ImportError("PDF export requires 'weasyprint' and 'markdown' packages")
