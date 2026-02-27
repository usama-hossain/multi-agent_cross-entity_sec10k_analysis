import os
from io import BytesIO
from xhtml2pdf import pisa

class HTMLToPDFService:
    def convert_html_bytes(self, html_content: bytes) -> bytes:
        html_string = html_content.decode("utf-8", errors="ignore")
        output = BytesIO()
        result = pisa.CreatePDF(src=html_string, dest=output)
        if result.err:
            raise RuntimeError("Failed to convert HTML to PDF.")
        return output.getvalue()

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
