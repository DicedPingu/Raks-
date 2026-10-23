#!/usr/bin/env python3
"""Create the versioned Raks host bundle (.tar.gz and .zip) plus SHA-256 checksums.

Usage: python3 scripts/package_release.py [--out dist] [--tag v0.1.0] [--apk path/to.apk ...]
The version comes from VERSION in host/server.py; --tag (if given) must match it as "v<VERSION>".
Checksums for the bundle (and any --apk files, copied into --out) go to SHA256SUMS.txt.
"""
import argparse
import hashlib
import io
import os
import re
import shutil
import sys
import tarfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCLUDE = ["host", "client", "presets", "docs", "contrib", "run.sh", "install.sh", "config.json", "LICENSE", "README.md"]
EXECUTABLE = {"run.sh", "install.sh", "host/raks_host.py"}


def read_version():
    src = open(os.path.join(ROOT, "host", "server.py"), encoding="utf-8").read()
    m = re.search(r'^VERSION\s*=\s*"(\d+\.\d+\.\d+)"', src, re.M)
    if not m:
        sys.exit("cannot read VERSION from host/server.py")
    return m.group(1)


def collect():
    files = []
    for item in INCLUDE:
        p = os.path.join(ROOT, item)
        if os.path.isfile(p):
            files.append(item)
        elif os.path.isdir(p):
            for d, dirs, names in os.walk(p):
                dirs[:] = sorted(x for x in dirs if x not in ("__pycache__", ".pytest_cache"))
                for n in sorted(names):
                    if n.endswith((".pyc", ".log")):
                        continue
                    files.append(os.path.relpath(os.path.join(d, n), ROOT).replace(os.sep, "/"))
        else:
            sys.exit("missing release item: " + item)
    return files


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(out, version):
    base = "raks-%s" % version
    files = collect()
    os.makedirs(out, exist_ok=True)
    tgz, zp = os.path.join(out, base + ".tar.gz"), os.path.join(out, base + ".zip")
    version_txt = (version + "\n").encode()
    with tarfile.open(tgz, "w:gz") as t:
        for f in files:
            ti = t.gettarinfo(os.path.join(ROOT, f), "%s/%s" % (base, f))
            ti.uid = ti.gid = 0; ti.uname = ti.gname = ""; ti.mtime = 0
            ti.mode = 0o755 if f in EXECUTABLE else 0o644
            with open(os.path.join(ROOT, f), "rb") as fh:
                t.addfile(ti, fh)
        ti = tarfile.TarInfo("%s/VERSION" % base); ti.size = len(version_txt); ti.mode = 0o644
        t.addfile(ti, io.BytesIO(version_txt))
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files + ["VERSION"]:
            zi = zipfile.ZipInfo("%s/%s" % (base, f), (1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = (0o755 if f in EXECUTABLE else 0o644) << 16
            z.writestr(zi, version_txt if f == "VERSION" else open(os.path.join(ROOT, f), "rb").read())
    return [tgz, zp]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--tag", help="release tag, must equal v<VERSION>")
    ap.add_argument("--apk", action="append", default=[], help="APK to copy into --out and checksum")
    a = ap.parse_args()
    version = read_version()
    if a.tag and a.tag != "v" + version:
        sys.exit("tag %s does not match host/server.py VERSION %s (expected v%s)" % (a.tag, version, version))
    assets = build(a.out, version)
    for apk in a.apk:
        dst = os.path.join(a.out, os.path.basename(apk))
        if os.path.abspath(apk) != os.path.abspath(dst):
            shutil.copy(apk, dst)
        assets.append(dst)
    with open(os.path.join(a.out, "SHA256SUMS.txt"), "w") as f:
        for p in assets:
            f.write("%s  %s\n" % (sha256(p), os.path.basename(p)))
    print("\n".join(assets + [os.path.join(a.out, "SHA256SUMS.txt")]))


if __name__ == "__main__":
    main()
