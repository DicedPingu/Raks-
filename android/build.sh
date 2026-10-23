#!/bin/sh
# Build the Raks Android wrapper with the plain Android SDK command-line tools (no Gradle/AGP needed).
# Output: android/build/raks-<version>-debug.apk (signed with a throwaway debug key, NOT a production signature).
# Needs: JDK 17+, ANDROID_HOME (or ANDROID_SDK_ROOT) with platform android-34+ and build-tools.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
[ -d "$SDK" ] || { echo "Set ANDROID_HOME to the Android SDK" >&2; exit 1; }
VERSION="$(sed -n 's/^VERSION = "\([0-9][0-9.]*\)".*/\1/p' "$ROOT/host/server.py")"
[ -n "$VERSION" ] || { echo "cannot read VERSION from host/server.py" >&2; exit 1; }
IFS=. read -r MAJ MIN PAT <<EOT
$VERSION
EOT
VCODE=$((MAJ * 10000 + MIN * 100 + PAT))
BT="$(ls -d "$SDK"/build-tools/*/ | sort -V | tail -1)"; BT="${BT%/}"
PLATFORM="$(ls -d "$SDK"/platforms/android-[0-9]* | sort -V | tail -1)"
for n in 34 35 36; do [ -f "$SDK/platforms/android-$n/android.jar" ] && PLATFORM="$SDK/platforms/android-$n" && break; done
ANDROID_JAR="$PLATFORM/android.jar"
B="$HERE/build"
OUT="${1:-$B/raks-$VERSION-debug.apk}"
rm -rf "$B/stage"; mkdir -p "$B/stage/assets" "$B/stage/classes" "$B/stage/dex" "$B/stage/res"

# Same client + presets as the PWA, packaged for offline use (service worker is pointless inside the app).
cp -r "$ROOT/client" "$B/stage/assets/client"; rm -f "$B/stage/assets/client/sw.js"
cp -r "$ROOT/presets" "$B/stage/assets/presets"
cp -r "$HERE/src/res/." "$B/stage/res/"

"$BT/aapt2" compile --dir "$B/stage/res" -o "$B/stage/res.zip"
"$BT/aapt2" link -o "$B/stage/unsigned.apk" -I "$ANDROID_JAR" --manifest "$HERE/src/AndroidManifest.xml" \
  --min-sdk-version 24 --target-sdk-version 34 --version-code "$VCODE" --version-name "$VERSION" \
  -A "$B/stage/assets" "$B/stage/res.zip"
javac --release 8 -Xlint:-options -classpath "$ANDROID_JAR" -d "$B/stage/classes" $(find "$HERE/src/java" -name '*.java')
"$BT/d8" --min-api 24 --lib "$ANDROID_JAR" --output "$B/stage/dex" $(find "$B/stage/classes" -name '*.class')
(cd "$B/stage/dex" && zip -q -u ../unsigned.apk classes.dex)
"$BT/zipalign" -f 4 "$B/stage/unsigned.apk" "$B/stage/aligned.apk"

KS="${RAKS_DEBUG_KEYSTORE:-$B/debug.keystore}"
[ -f "$KS" ] || keytool -genkeypair -keystore "$KS" -storepass android -keypass android -alias raks-debug \
  -dname "CN=Raks Debug,O=Debug" -keyalg RSA -keysize 2048 -validity 10000 >/dev/null 2>&1
mkdir -p "$(dirname "$OUT")"
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android --ks-key-alias raks-debug --out "$OUT" "$B/stage/aligned.apk"
"$BT/apksigner" verify "$OUT"
echo "Built $OUT"
