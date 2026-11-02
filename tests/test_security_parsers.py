"""Bounded benign parser inputs; patched-binary evidence is a separate release gate."""
import io
import unittest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from knowledge.attachments import pdf_text


class PdfImport(unittest.TestCase):
    def test_benign_text_blank_and_malformed_pdf(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=200, height=200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 10 100 Td (Synthetic parser fixture) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        output = io.BytesIO()
        writer.write(output)
        self.assertLess(len(output.getvalue()), 2048)
        self.assertIn('Synthetic parser fixture', pdf_text(output.getvalue()))
        blank = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.write(blank)
        with self.assertRaisesRegex(ValueError, 'no text layer'):
            pdf_text(blank.getvalue())
        with self.assertRaises(ValueError):
            pdf_text(b'%PDF-1.7\nsynthetic truncated document')
