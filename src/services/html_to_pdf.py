import os
import re
import tempfile
from io import BytesIO
from bs4 import BeautifulSoup
from xhtml2pdf import pisa

class HTMLToPDFService:
    def _sanitize_html_for_xhtml2pdf(self, html_string: str) -> str:
        parser = "xml" if html_string.lstrip().startswith("<?xml") else "lxml"
        soup = BeautifulSoup(html_string, parser)

        for tag in soup.find_all(["script", "iframe", "object", "embed"]):
            tag.decompose()

        for tag in soup.find_all(["table", "tr", "td", "th"]):
            if tag.has_attr("height"):
                del tag["height"]
            if tag.has_attr("style"):
                style_parts = [
                    part.strip()
                    for part in tag["style"].split(";")
                    if part.strip() and not part.strip().lower().startswith("height:")
                ]
                if style_parts:
                    tag["style"] = "; ".join(style_parts)
                else:
                    del tag["style"]

        for tag in soup.find_all(style=True):
            style_value = tag.get("style", "")
            sanitized_style = re.sub(r"url\((?:\s*['\"]?)\s*(?:https?:)?//[^\)]+\)", "none", style_value, flags=re.IGNORECASE)
            tag["style"] = sanitized_style

        for tag in soup.find_all(href=True):
            href = (tag.get("href") or "").strip().lower()
            if href.startswith(("http://", "https://", "//")):
                if tag.name == "link":
                    tag.decompose()
                else:
                    del tag["href"]

        for img in soup.find_all("img"):
            src = (img.get("src") or "").strip().lower()
            if src and not src.startswith(("http://", "https://", "data:")):
                img.decompose()
            elif src.startswith(("http://", "https://", "//")):
                img.decompose()

        return str(soup)

    def _render_pdf_with_playwright(self, html_string: str) -> bytes:
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = os.path.join(temp_dir, "input.html")

            with open(html_path, "w", encoding="utf-8") as html_file:
                html_file.write(html_string)

            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
                    )
                except Exception as ex:
                    message = str(ex)
                    if "libasound.so.2" in message:
                        raise RuntimeError(
                            "Playwright Chromium is missing OS dependency libasound.so.2. "
                            "Install browser deps (e.g., 'python -m playwright install --with-deps chromium')."
                        ) from ex
                    raise
                context = browser.new_context()
                page = context.new_page()

                def route_handler(route):
                    request_url = route.request.url.lower()
                    if request_url.startswith(("http://", "https://", "//")):
                        route.abort()
                    else:
                        route.continue_()

                page.route("**/*", route_handler)
                page.goto(f"file://{html_path}", wait_until="load", timeout=120000)
                pdf_bytes = page.pdf(
                    format="A4",
                    print_background=True,
                    prefer_css_page_size=True,
                    margin={"top": "0.5in", "right": "0.5in", "bottom": "0.5in", "left": "0.5in"},
                )
                context.close()
                browser.close()

                return pdf_bytes

    def _render_pdf(self, html_string: str) -> bytes:
        output = BytesIO()
        result = pisa.CreatePDF(src=html_string, dest=output)
        if result.err:
            raise RuntimeError("Failed to convert HTML to PDF.")
        return output.getvalue()

    def convert_html_bytes(self, html_content: bytes) -> bytes:
        html_string = html_content.decode("utf-8", errors="ignore")
        sanitized_html = self._sanitize_html_for_xhtml2pdf(html_string)

        try:
            return self._render_pdf_with_playwright(sanitized_html)
        except Exception:
            return self._render_pdf(sanitized_html)

    def convert(self, html_file_path: str, output_pdf_path: str = None) -> str:
        """Converts a local HTML file to PDF and returns the output path."""
        if not os.path.exists(html_file_path):
            raise FileNotFoundError(f"File not found: {html_file_path}")

        if output_pdf_path is None:
            base = os.path.splitext(html_file_path)[0]
            output_pdf_path = base + ".pdf"

        file_size = os.path.getsize(html_file_path)
        print(f"📄 Converting: {os.path.basename(html_file_path)} ({file_size} bytes)")

        with open(html_file_path, "rb") as html_file:
            pdf_bytes = self.convert_html_bytes(html_file.read())

        with open(output_pdf_path, "wb") as pdf_file:
            pdf_file.write(pdf_bytes)

        pdf_size = os.path.getsize(output_pdf_path)
        print(f"✅ PDF saved: {output_pdf_path} ({pdf_size} bytes)")

        return output_pdf_path


if __name__ == "__main__":
    service = HTMLToPDFService()

    target_file = "/workspaces/codespaces-blank/Project1/data/raw/sec-edgar-filings/DUK/10-K/0001326160-25-000072/primary-document.html"
    output_file = "/workspaces/codespaces-blank/Project1/data/raw/sec-edgar-filings/DUK/10-K/0001326160-25-000072/primary-document.pdf"

    try:
        pdf_path = service.convert(target_file, output_file)
        print(f"Conversion complete: {pdf_path}")
    except Exception as e:
        print(f"Error during conversion: {e}")
