"""The 25 business document types Jarvis must recognise (from the name or the title)."""
import sys; sys.path.insert(0, "scripts")
import docsearch as d
ok = bad = 0
CASES = [
 ("Invoice 1234.pdf", "Invoice No INV-1234 Total PKR 5,000", "invoice"),
 ("Sales Invoice INV-22.pdf", "", "sales invoice"),
 ("Proforma Invoice PI-9.pdf", "", "proforma invoice"),
 ("scan001.pdf", "PROFORMA INVOICE No PI-77 Date 2026-10-01 total 90,000", "proforma invoice"),
 ("Receipt 55.jpg", "", "receipt"),
 ("Credit Note CN-12.pdf", "", "credit note"),
 ("Debit Note DN-3.pdf", "", "debit note"),
 ("Statement of Account - Khan Traders.pdf", "", "statement of account"),
 ("doc.pdf", "STATEMENT OF ACCOUNT Khan Traders period Jan-Mar balance 120,000", "statement of account"),
 ("Purchase Requisition PR-4.docx", "", "purchase requisition"),
 ("PO-1001.pdf", "Purchase Order PO-1001 supplier ABC", "purchase order"),
 ("Quotation QT-5.pdf", "", "quotation"),
 ("Price Quote steel.pdf", "", "quotation"),
 ("Sales Order SO-8.pdf", "", "sales order"),
 ("Delivery Note DN-44.pdf", "", "delivery challan"),
 ("Bill of Lading MSKU123.pdf", "", "bill of lading"),
 ("NDA - ABC Ltd.pdf", "", "nda"),
 ("agreement.pdf", "NON-DISCLOSURE AGREEMENT between A and B. invoice date payable", "nda"),
 ("Supplier Contract Steel Co.pdf", "", "vendor contract"),
 ("Terms of Service.pdf", "", "terms of service"),
 ("MoU with Bilal Steel.docx", "", "mou"),
 ("x.pdf", "MEMORANDUM OF UNDERSTANDING between Apricot and Khan", "mou"),
 ("Trade License 2026.pdf", "", "license or permit"),
 ("Articles of Incorporation.pdf", "", "articles of incorporation"),
 ("Business Plan 2027.pdf", "", "business plan"),
 ("Meeting Minutes 5 Nov.docx", "", "meeting minutes"),
 ("Company Bylaws.pdf", "", "bylaws"),
 ("Employment Contract - Ali.pdf", "", "employment contract"),
 ("Job Description Accountant.docx", "", "job description"),
 ("Employee Handbook 2026.pdf", "", "employee handbook"),
 ("Performance Appraisal Sara.xlsx", "", "performance appraisal"),
 ("CV Ahmed.pdf", "Curriculum Vitae experience in sales invoices", ""),
]
for name, text, want in CASES:
    got = d.classify(name, text)
    if got == want: ok += 1
    else: bad += 1; print("FAIL", name, "->", repr(got), "wanted", repr(want))
print(f"{ok} ok, {bad} failed"); sys.exit(1 if bad else 0)
