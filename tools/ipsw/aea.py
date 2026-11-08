#!/usr/bin/env python3
"""Decrypt an Apple Encrypted Archive (AEA1) of an IPSW: aea.py IN.aea OUT.

The pure-Python counterpart of macOS's `aea decrypt -key-value base64:KEY`, so the disk images can be
decrypted on Linux as well. The archive key comes from aea-key.py beside this script, which asks
Apple's key server named in the file. Only what IPSW disk images use is supported:
profile 1 (symmetric encryption, no signature), segments stored as they are or compressed with
LZFSE. LZFSE is decoded by the system's library: libcompression on macOS, liblzfse on Linux (the
liblzfse1 package of Debian and Ubuntu). Every cluster, segment and the padding are authenticated
(HMAC-SHA256) and every segment's checksum is checked before it is written.

The layout and key derivations follow blacktop/ipsw's pkg/aea (MIT licence, decrypt.go and
encrypt.go): HKDF-SHA256 keys named AEA_AMK (main), AEA_RHEK (root header), AEA_CK and AEA_CHEK
(cluster), AEA_SK (segment) and AEA_PAK (padding); AES-256-CTR for root header, segment headers
and segment data.
"""
import argparse
import base64
import ctypes
import ctypes.util
import hashlib
import hmac
import struct
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF, HKDFExpand

PROFILE_SYMMETRIC = 1
LZFSE = ord("e")
CHECKSUM_BYTES = {0: 0, 2: 32}  # none, SHA-256 (IPSW disk images use SHA-256)


def hkdf(key, info, length=80, salt=None):
    return HKDF(hashes.SHA256(), length, salt, info).derive(key)


def header_key(material):
    """(mac key, AES key, CTR initial counter block) of an 80-byte key material."""
    return material[:32], material[32:64], material[64:80]


def ctr(key, iv, data):
    decryptor = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
    return decryptor.update(data) + decryptor.finalize()


def mac(key, data, prefix=b""):
    """AEA's HMAC: over prefix, data and the prefix's length as 8 little-endian bytes."""
    h = hmac.new(key, prefix, hashlib.sha256)
    h.update(data)
    h.update(struct.pack("<Q", len(prefix)))
    return h.digest()


def lzfse_decoder():
    """decode(data, size) -> bytes, by the system's LZFSE implementation."""
    args = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p]
    path = ctypes.util.find_library("compression")
    if path:  # macOS: compression_decode_buffer(dst, dst_size, src, src_size, scratch, algorithm)
        fn, extra = ctypes.CDLL(path).compression_decode_buffer, (0x801,)  # COMPRESSION_LZFSE
        fn.argtypes = args + [ctypes.c_int]
    else:
        path = ctypes.util.find_library("lzfse")
        check(path, "no LZFSE library: install liblzfse1 (apt) or lzfse (dnf, pacman)")
        fn, extra = ctypes.CDLL(path).lzfse_decode_buffer, ()
        fn.argtypes = args
    fn.restype = ctypes.c_size_t

    def decode(data, size):
        dst = ctypes.create_string_buffer(size + 1)  # one byte more tells a full buffer from a cut stream
        n = fn(dst, size + 1, data, len(data), None, *extra)
        check(n == size, f"LZFSE segment decoded to {n} bytes, expected {size}")
        return dst.raw[:size]
    return decode


def check(ok, what):
    if not ok:
        raise SystemExit(f"aea.py: {what}")


def decrypt(src, dst, key):
    size = src.stat().st_size
    with open(src, "rb") as f, open(dst, "wb") as out:
        magic, profile_scrypt, auth_size = struct.unpack("<4sII", f.read(12))
        check(magic == b"AEA1", "not an AEA1 file")
        check(profile_scrypt & 0xFFFFFF == PROFILE_SYMMETRIC, f"profile {profile_scrypt & 0xFFFFFF} is not supported")
        auth = f.read(auth_size)
        salt = f.read(32)
        main = hkdf(key, b"AEA_AMK" + struct.pack("<I", profile_scrypt), len(key), salt)
        root_mac, root_data, cluster_mac = f.read(32), f.read(48), f.read(32)
        rh_mac, rh_key, rh_iv = header_key(hkdf(main, b"AEA_RHEK"))
        # over the first cluster's HMAC, the auth data and the root header, then their two lengths summed
        h = hmac.new(rh_mac, cluster_mac + auth + root_data + struct.pack("<Q", 32 + auth_size), hashlib.sha256)
        check(hmac.compare_digest(root_mac, h.digest()), "root header HMAC (wrong key?)")
        file_size, encrypted_size, segment_size, per_cluster, compression, checksum = struct.unpack(
            "<QQIIBB", ctr(rh_key, rh_iv, root_data)[:26])
        check(encrypted_size == size, f"file is {size} bytes, the archive says {encrypted_size}")
        check(checksum in CHECKSUM_BYTES and 0 < segment_size <= 256 << 20 and 0 < per_cluster <= 256 << 10,
              "unsupported root header")
        decode = lzfse_decoder() if compression == LZFSE else None
        entry = 8 + CHECKSUM_BYTES[checksum]
        written, cluster = 0, 0
        while written < file_size:
            ck = hkdf(main, b"AEA_CK" + struct.pack("<I", cluster), 32)
            ch_mac, ch_key, ch_iv = header_key(hkdf(ck, b"AEA_CHEK"))
            headers = f.read(entry * per_cluster)
            macs = f.read(32 + 32 * per_cluster)
            check(hmac.compare_digest(cluster_mac, mac(ch_mac, headers, macs)), f"cluster {cluster} HMAC")
            cluster_mac = macs[:32]
            headers = ctr(ch_key, ch_iv, headers)
            prk = hmac.new(b"\0" * 32, ck, hashlib.sha256).digest()  # HKDF-Extract with no salt
            for index in range(per_cluster):
                plain_size, stored_size = struct.unpack_from("<II", headers, index * entry)
                expected = min(segment_size, file_size - written)
                check(plain_size == expected, f"cluster {cluster} segment {index}: size {plain_size}, expected {expected}")
                if expected == 0:
                    check(stored_size == 0, f"cluster {cluster} segment {index} is not empty")
                    continue
                data = f.read(stored_size)
                check(len(data) == stored_size, "the file ends early")
                s_mac, s_key, s_iv = header_key(HKDFExpand(hashes.SHA256(), 80, b"AEA_SK" + struct.pack("<I", index)).derive(prk))
                check(hmac.compare_digest(macs[32 + 32 * index:64 + 32 * index], mac(s_mac, data)),
                      f"cluster {cluster} segment {index} HMAC")
                data = ctr(s_key, s_iv, data)
                if stored_size != plain_size:
                    check(decode is not None, f"compression {chr(compression)!r} is not supported; use macOS's aea")
                    data = decode(data, plain_size)
                want = headers[index * entry + 8:(index + 1) * entry]
                if checksum == 2:
                    check(hashlib.sha256(data).digest() == want, f"cluster {cluster} segment {index} checksum")
                out.write(data)
                written += len(data)
            cluster += 1
        pad_mac = header_key(hkdf(main, b"AEA_PAK"))[0]
        h = hmac.new(pad_mac, b"", hashlib.sha256)
        while chunk := f.read(1 << 20):
            h.update(chunk)
        check(hmac.compare_digest(cluster_mac, h.digest()), "padding HMAC")
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    key = subprocess.run([sys.executable, Path(__file__).with_name("aea-key.py"), args.input],
                                     check=True, capture_output=True, text=True).stdout.strip()
    written = decrypt(args.input, args.output, base64.b64decode(key))
    print(f"aea.py: {args.output}: {written} bytes")


if __name__ == "__main__":
    main()
