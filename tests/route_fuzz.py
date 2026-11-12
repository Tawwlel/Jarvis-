import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import agents
CASES = {
 "finder": ["find the Khan Traders invoice","Khan Traders ki invoice dikhao","kal wali quotation kahan hai","show me last week's receipts",
  "open the latest invoice","mujhe Bilal Steel ki quotation chahiye","search my documents for agreement","photos from Ali","list all purchase orders",
  "WhatsApp se invoice nikalo","get me the bill from Hassan Motors","delivery challan dhoond do","where is the contract","latest receipt dikhao",
  "invoices above 2 lakh","اشرف کی انوائس دکھاؤ","کل کی رسید ڈھونڈو","sab se purani quotation","gather the invoices into one folder","find file named report",
  "open the first one","invoice from March","find invoices on WhatsApp","do I have a receipt for petrol","pdf of the agreement"],
 "accounts": ["total sales this month","Khan Traders ki kul sales kitni hai?","how much is the total of all invoices","what is the tax on INV-9001",
  "kul raqam kitni hai","sum of March invoices","invoice details of INV-9001","ٹوٹل کتنا ہے","how much did we invoice Ali Enterprises","learn this invoice layout"],
 "whatsapp": ["link WhatsApp","connect my whatsapp","check WhatsApp for new files","sync whatsapp","what new documents came on WhatsApp","import old files from my iPhone",
  "How much did Khan Traders pay on whatsapp","WhatsApp ko link karo","واٹس ایپ لنک کرو","new files on whatsapp today","fetch whatsapp documents","iphone backup import karo"],
 "email": ["check my email","any new mail","email digest","inbox summary","mera email dekho","ای میل چیک کرو","change the digest time to 8","emails from the last 24 hours"],
 "organizer": ["remind me in 10 minutes to call Ali","set a reminder for tomorrow 9am","yaad dilao ke kal meeting hai","add a task buy toner","what is on my to-do list",
  "take a note: Ali wants 40 pipes","what's on my calendar today","do I have meetings tomorrow","schedule a meeting with Bilal","mark the task done","یاد دہانی لگاؤ","میٹنگ کب ہے"],
 "librarian": ["scan everything","yes, scan everything","scan now","scan status","refresh every 6 hours","scan my computer and whatsapp","اسکین کرو"],
 "clerk": ["delete the file old.pdf","rename the file report.docx","move the folder to Desktop","create a file notes.txt","edit the document draft"],
 "keeper": ["back up Jarvis now","backup bana do","restore from backup","make a backup","بیک اپ بناؤ"],
 "guide": ["how do I set up WhatsApp","WhatsApp kaise connect karun","setup kaise karun","how can I add my email","settings change karo","سیٹپ کیسے کروں؟","how to install the key","help me set up"],
 "jarvis": ["hello","what time is it","show my agents","what can you do","remember my name is Talal","good morning","thanks","tell me a joke","who are you"],
}
bad = []
for want, qs in CASES.items():
    for q in qs:
        got = agents.pick(q)
        if got != want:
            bad.append((q, want, got))
n = sum(len(v) for v in CASES.values())
for b in bad: print("MISROUTE", b)
print(f"{n - len(bad)}/{n} routed correctly")
sys.exit(1 if bad else 0)
