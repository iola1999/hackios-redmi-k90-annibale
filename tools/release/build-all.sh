#!/bin/bash
# Build everything tools/release/build-release.py packs, in a fresh clone of the workspace
# (docs/development.md §10). The inputs that are not in the repositories have to be in place first:
#   hackios-xnu-kernel/out/ipsw/v57/26/{os,systemos,appos}.dmg   the IPSW's images (§3)
#   hackios-xnu-userland/fw-gpu, fw-camera, hackios-xnu-kernel/out/fw-{wifi,bt,iris}   the phone's (§4)
#   $LOADER_IMAGE (default hackios-xnu-kernel/out/handoff-loader-v19.img)   the reference loader image
#   the hackios-dev Docker image (docker/build.sh) and the host tools of the Mesa build
# The kernel builds in the background while the userland and the AIR library do. Each phase writes
# out/release-build/<phase>.log and prints its time.
# usage: tools/release/build-all.sh [PHASE ...]
#        phases: ios kernel userland mesa package loader android (default: all of them)
set -e
cd "$(dirname "$0")/../.."
R=$PWD
K=$R/hackios-xnu-kernel
U=$R/hackios-xnu-userland
LOADER_IMAGE=${LOADER_IMAGE:-hackios-xnu-kernel/out/handoff-loader-v19.img}
LOGS=$R/out/release-build
mkdir -p "$LOGS"

# A phase runs as a background job: in the condition of an if or after || bash ignores set -e inside
# the function, and a failed step would not stop it.
phase() {
	local name=$1 t0 rc=0
	t0=$(date +%s)
	echo "== $name"
	"$name" > "$LOGS/$name.log" 2>&1 &
	wait $! || rc=$?
	if [ $rc != 0 ]; then
		tail -20 "$LOGS/$name.log" >&2
		echo "== $name failed after $(( $(date +%s) - t0 )) s; log: $LOGS/$name.log" >&2
		return 1
	fi
	echo "== $name done in $(( $(date +%s) - t0 )) s"
}

ios() { bash "$U/ios26/fetch.sh"; }  # a check when the extraction is there already

kernel() (
	cd "$K"
	[ -d xnu-src/xnu-12377.121.6 ] || xnu26/apply.sh
	xnu26/deps-macos.sh --stage1
	xnu26/build-macos.sh exporthdrs installhdrs
	xnu26/deps-macos.sh --stage2
	xnu26/build-macos.sh
	# a copy rather than register-kernel.py, which refuses a name it has used: this phase runs again
	cp xnu-src/xnu-12377.121.6/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837 out/xnu12377-local.bin
)

userland() (
	cd "$U/userland"
	IOS=../ios26 COMPILE_ONLY=1 SHARE=1 bash build.sh
	FLASHBOOT=1 FLASHBOOT_ONLY=1 CRYPTEXES=flash bash build.sh
)

mesa() {
	docker run --rm -v "$R":/work -w /work/hackios-xnu-userland hackios-dev:latest bash -c \
		'PREPARE=1 VERSION=26.2.5 SHA256=794b3d1729075dae7ebd47c7283b7ca0cdb5dec668f7f11cc0a5d82f6138a0a5 REBASE=26 tools/mk-mesa.sh'
	[ -d "$K/out/ios26-resume/mesa-arm64e" ] || python3 tools/k90auto/setup-mesa-arm64e.py
	python3 tools/k90auto/build-air.py
}

package() { SHARE=1 python3 tools/k90auto/package.py; }

loader() {
	(cd "$K" && EXTRA_CFLAGS=-DDIRECT_PHONE_PLAT BUILD_ID=$(git log -1 --format=%H -- xnuloader) xnuloader/build.sh)
	python3 "$K/xnuloader/mkstandalone.py" --no-lz4 --kernel "$K/out/xnu12377-local.bin" \
		--ramdisk "$K/out/ios26-resume/bbmetal-device/root.apfs" --boot-image "$U/userland/flashboot.apfs" \
		-o "$K/out/standalone-payload.bin"
	python3 "$K/tools/reseal-loader-img.py" "$LOADER_IMAGE" "$K/out/standalone-payload.bin" -o "$K/out/boot-a-ios.img"
}

android() { bash "$K/tools/android/build.sh"; }

if [ $# -gt 0 ]; then
	for name in "$@"; do phase "$name"; done
	exit 0
fi
missing=
for f in "$K"/out/ipsw/v57/26/{os,systemos,appos}.dmg "$U/fw-gpu/gen80000_zap.mbn" \
	"$U"/fw-camera/com.qti.sensormodule.annibale_{sunny_ov20b40_front,aac_ovx8000_wide}_i.bin \
	"$K/out/fw-wifi/amss20.bin" "$K/out/fw-bt/hmtbtfw20.tlv" "$K/out/fw-iris/vpu35_4v.mbn" "$LOADER_IMAGE"; do
	[ -f "$f" ] || missing="$missing $f"
done
[ -z "$missing" ] || { echo "build-all.sh: missing inputs (docs/development.md §3, §4):$missing" >&2; exit 1; }

phase ios
phase kernel &
kernel_pid=$!
phase userland
phase mesa
phase package
wait $kernel_pid
phase loader
phase android
echo "next: python3 tools/release/build-release.py vX.Y.Z --kernel hackios-xnu-kernel/out/xnu12377-local.bin" \
	"--loader-image $LOADER_IMAGE --expect-boot hackios-xnu-kernel/out/boot-a-ios.img"
