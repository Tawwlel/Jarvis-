"""Desktop and Start-menu shortcuts named "Jarvis" with the Apricot Digital logo (not Python's).

The shortcut also carries Jarvis's own app id (ApricotDigital.Jarvis, the same one jarvis_app.py sets), so a
pinned Jarvis and the running Jarvis share one taskbar button with the Jarvis logo.

Windows-only; safe to call at every start (it only writes when a shortcut is missing or points somewhere old).
    python scripts/shortcuts.py          # create / repair
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "assets" / "jarvis.ico"
SCRIPT = ROOT / "scripts" / "jarvis_app.py"
APP_ID = "ApricotDigital.Jarvis"
NAME = "Jarvis"

# Creates the .lnk through the Windows shell, then stamps the app id on it (IPropertyStore).
_PS = r'''
$ErrorActionPreference = "Stop"
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
[StructLayout(LayoutKind.Sequential, Pack=4)] public struct PROPERTYKEY { public Guid fmtid; public uint pid; }
[StructLayout(LayoutKind.Explicit)] public struct PROPVARIANT { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }
[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPropertyStore { void GetCount(out uint c); void GetAt(uint i, out PROPERTYKEY k);
  void GetValue(ref PROPERTYKEY k, out PROPVARIANT v); void SetValue(ref PROPERTYKEY k, ref PROPVARIANT v); void Commit(); }
[ComImport, Guid("0000010b-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPersistFile { void GetClassID(out Guid g); [PreserveSig] int IsDirty();
  void Load([MarshalAs(UnmanagedType.LPWStr)] string f, uint m); void Save([MarshalAs(UnmanagedType.LPWStr)] string f, bool r);
  void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string f); void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string f); }
[ComImport, Guid("00021401-0000-0000-C000-000000000046")] public class ShellLink {}
[ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IShellLinkW { void GetPath(IntPtr a, int b, IntPtr c, uint d); void GetIDList(out IntPtr p); void SetIDList(IntPtr p);
  void GetDescription(IntPtr a, int b); void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string s);
  void GetWorkingDirectory(IntPtr a, int b); void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string s);
  void GetArguments(IntPtr a, int b); void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string s);
  void GetHotkey(out short h); void SetHotkey(short h); void GetShowCmd(out int c); void SetShowCmd(int c);
  void GetIconLocation(IntPtr a, int b, out int i); void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string s, int i);
  void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string s, uint r); void Resolve(IntPtr h, uint f);
  void SetPath([MarshalAs(UnmanagedType.LPWStr)] string s); }
public static class Lnk {
  public static void Make(string lnk, string target, string args, string dir, string icon, string desc, string appId) {
    var l = (IShellLinkW)new ShellLink();
    l.SetPath(target); l.SetArguments(args); l.SetWorkingDirectory(dir); l.SetIconLocation(icon, 0); l.SetDescription(desc);
    var ps = (IPropertyStore)l;
    var key = new PROPERTYKEY { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
    var v = new PROPVARIANT { vt = 31, p = Marshal.StringToCoTaskMemUni(appId) };
    ps.SetValue(ref key, ref v); ps.Commit();
    ((IPersistFile)l).Save(lnk, true);
    Marshal.FreeCoTaskMem(v.p);
  }
}
"@
foreach ($lnk in $env:J_LNKS.Split("|")) {
  New-Item -ItemType Directory -Force -Path (Split-Path $lnk) | Out-Null
  [Lnk]::Make($lnk, $env:J_TARGET, $env:J_ARGS, $env:J_DIR, $env:J_ICON, "Jarvis by Apricot Digital", $env:J_APPID)
}
'''


def _pythonw() -> str:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    if w.exists():
        return str(w)
    return shutil.which("pythonw") or str(exe)


def places() -> list[Path]:
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    desk = home / "Desktop"
    for od in sorted(home.glob("OneDrive*")):  # Desktop is often redirected into OneDrive
        if (od / "Desktop").is_dir():
            desk = od / "Desktop"
            break
    start = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return [desk / f"{NAME}.lnk", start / f"{NAME}.lnk"]


def ensure(force: bool = False) -> str:
    if sys.platform != "win32":
        return "not Windows"
    if not ICON.exists():
        return "icon missing"
    stamp = ROOT / "data" / "shortcuts.txt"
    want = f"{_pythonw()}|{SCRIPT}|{ICON}"
    lnks = places()
    try:
        if not force and all(p.exists() for p in lnks) and stamp.read_text(encoding="utf-8") == want:
            return "ok"
    except Exception:
        pass
    env = dict(os.environ, J_LNKS="|".join(str(p) for p in lnks), J_TARGET=_pythonw(), J_ARGS=f'"{SCRIPT}"',
               J_DIR=str(ROOT), J_ICON=str(ICON), J_APPID=APP_ID)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _PS], env=env,
                           capture_output=True, text=True, timeout=90, creationflags=0x08000000)
        if r.returncode != 0:
            return "failed: " + (r.stderr or r.stdout)[-300:]
        stamp.parent.mkdir(exist_ok=True)
        stamp.write_text(want, encoding="utf-8")
        return "made"
    except Exception as e:
        return f"failed: {e}"


def store_python() -> bool:
    """Microsoft Store Python: Windows shows the Python logo on the taskbar for every app it runs, whatever the
    app asks for. python.org Python (or Jarvis's bundled runtime) doesn't have this problem."""
    return "WindowsApps" in sys.executable or "PythonSoftwareFoundation" in sys.base_prefix


if __name__ == "__main__":
    print("shortcuts:", ensure(force=True))
    if store_python():
        print("Note: this is the Microsoft Store Python, so the taskbar may still show the Python logo. "
              "Install Python from python.org to show the Jarvis logo there too.")
