"""Small always-on-top explainer window (pywebview + Chart.js from CDN).
Each visual opens in its own process so it never blocks the voice loop."""
import json
import subprocess
import sys

HTML = """<!doctype html><html><head><meta charset=utf-8>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>body{font-family:Segoe UI,sans-serif;margin:14px;background:#10131a;color:#e8ecf4}
h2{margin:0 0 8px;font-size:18px}p{line-height:1.5;font-size:15px}</style></head><body>
<h2 id=t></h2><canvas id=c height=170></canvas><p id=b></p>
<script>
const d=__DATA__;document.getElementById('t').textContent=d.title;
if(d.kind==='definition'){document.getElementById('c').remove()}
else{new Chart(document.getElementById('c'),{type:d.kind,data:{labels:d.labels,
datasets:[{data:d.values,backgroundColor:'#4f8cff',borderColor:'#4f8cff'}]},
options:{plugins:{legend:{display:false}}}})}
document.getElementById('b').textContent=d.body||'';
</script></body></html>"""


def show(kind, title, labels=None, values=None, body=None):
    payload = json.dumps(
        {"kind": kind, "title": title, "labels": labels or [], "values": values or [], "body": body or ""}
    )
    subprocess.Popen([sys.executable, __file__, payload])


if __name__ == "__main__":
    import webview  # pip install pywebview

    data = json.loads(sys.argv[1])
    webview.create_window(
        data["title"], html=HTML.replace("__DATA__", json.dumps(data)),
        width=380, height=340, on_top=True,
    )
    webview.start()
