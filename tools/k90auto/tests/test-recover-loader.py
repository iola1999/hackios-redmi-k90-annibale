#!/usr/bin/env python3
"""Check loader recovery identity and RAM state without sending device commands."""
from pathlib import Path
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "recover-loader.py"


class RecoveryTests(unittest.TestCase):
    def invoke(self, devices, *, result="idle", ramdisk="idle 0 0 0", product="xnuloader",
               runtime=False, stop_result="hung-held 100 0", capture_failed=False, android=False,
               android_devices=None, lk_product="annibale", lk_userspace="no",
               lk_b_successful="yes", lk_b_unbootable="no", android_boot_completed="1",
                loader_image="", android_transition_refused=False, legacy_terminal_recovery=False,
                 after_boot_devices=None, reboot_lk_refused=False, reboot_lk_stays_loader=False,
                 boot_result="idle", boot_ramdisk="idle 0 0 0", boot_product="xnuloader"):
        sent = []
        state = {"ramdisk": ramdisk, "result": result, "reset": False}

        def execute(argv, **kwargs):
            sent.append(argv)
            if argv == ["fastboot", "devices"]:
                if state["reset"] and after_boot_devices is not None:
                    index = state.get("boot_enumerations", 0)
                    out = after_boot_devices[min(index, len(after_boot_devices) - 1)]
                    state["boot_enumerations"] = index + 1
                elif android and state["reset"]:
                    out = "xnuloader\tfastboot\n" if state.get("gap_seen") else ""
                    state["gap_seen"] = True
                elif android and state.get("bootloader"):
                    out = "test-android\tfastboot\n"
                else:
                    out = devices
            elif argv == ["adb", "devices"]:
                out = (android_devices if android_devices is not None else
                       "List of devices attached\n" + ("test-android\tdevice\n" if android else "\tdevice\n"))
            elif android and argv[:4] == ["adb", "-s", "test-android", "shell"]:
                self.assertEqual(argv[4], "getprop")
                out = {"ro.product.device": "annibale", "ro.boot.slot_suffix": "_b",
                       "sys.boot_completed": android_boot_completed}[argv[5]] + "\n"
            elif android and argv == ["adb", "-s", "test-android", "reboot", "bootloader"]:
                state["bootloader"] = True
                out = ""
            elif android and argv[:4] == ["fastboot", "-s", "test-android", "getvar"]:
                key = argv[-1]
                values = {"product": lk_product, "is-userspace": lk_userspace,
                          "current-slot": "a" if state.get("active") else "b",
                          "slot-retry-count:a": "7" if state.get("active") else "0",
                          "slot-unbootable:a": "no" if state.get("active") else "yes",
                          "slot-successful:a": "no", "slot-successful:b": lk_b_successful,
                          "slot-unbootable:b": lk_b_unbootable}
                out = f"(bootloader) {key}: {values[key]}\n"
            elif android and argv == ["fastboot", "-s", "test-android", "set_active", "a"]:
                state["active"] = True
                out = "OKAY\n"
            elif android and argv == ["fastboot", "-s", "test-android", "reboot"]:
                self.assertTrue(state.get("active"))
                state["reset"] = True
                out = "OKAY\n"
            elif android and loader_image and argv == ["fastboot", "-s", "test-android", "boot", loader_image]:
                self.assertTrue(state.get("active"))
                state.update(reset=True, result=boot_result, ramdisk=boot_ramdisk, product=boot_product)
                out = "OKAY\n"
            elif argv[:4] == ["fastboot", "-s", "xnuloader", "getvar"]:
                key = argv[-1]
                values = {"product": state.get("product", product), "result": state["result"], "build-id": "test-build",
                          "ramdisk-state": state["ramdisk"], "ramdisk-protocol": "1"}
                out = f"(bootloader) {key}: {values[key]}\nFinished.\n"
            elif argv == ["fastboot", "-s", "xnuloader", "oem", "recovery"]:
                if legacy_terminal_recovery and runtime and not state["reset"] and state["result"].startswith("returned "):
                    state["result"] = "idle"
                    out = "OKAY\n"
                else:
                    out = ("FAILED (remote: kernel resources are unavailable for recovery)\n"
                           if runtime and not state["reset"] else "OKAY\n")
            elif argv == ["fastboot", "-s", "xnuloader", "oem", "ramdisk", "none"]:
                state["ramdisk"] = "idle 0 0 0"
                out = "OKAY\n"
            elif argv == ["fastboot", "-s", "xnuloader", "oem", "stop"]:
                state["result"] = stop_result
                out = "OKAY\n"
            elif argv == ["fastboot", "-s", "xnuloader", "oem", "android"]:
                self.assertTrue(android)
                if android_transition_refused or not state["result"].startswith("returned "):
                    out = "FAILED (remote: kernel resources are unavailable for Android)\n"
                else:
                    state["bootloader"] = True
                    out = "OKAY\n"
            elif argv == ["fastboot", "-s", "xnuloader", "oem", "log"]:
                out = "OKAY\n"
            elif argv[:4] == ["fastboot", "-s", "xnuloader", "get_staged"]:
                Path(argv[-1]).write_text("saved log\n")
                out = "FAILED (remote: snapshot unavailable)\n" if capture_failed else "OKAY\n"
            elif argv == ["fastboot", "-s", "xnuloader", "reboot"]:
                state.update(reset=True, result="idle", ramdisk="idle 0 0 0")
                out = "OKAY\n"
            elif argv == ["fastboot", "-s", "xnuloader", "reboot-bootloader"]:
                if reboot_lk_refused:
                    out = "FAILED (remote: LK reboot target preparation failed)\n"
                else:
                    state["bootloader"] = not reboot_lk_stays_loader
                    out = "OKAY\n"
            else:
                self.fail(f"Unexpected device command: {argv}")
            return subprocess.CompletedProcess(argv, 0, out)

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "argv", [str(SOURCE), str(Path(directory) / "record")]), \
                patch.dict(os.environ, {"ANDROID_SERIAL": "test-android", "K90_STOP_WAIT": "5",
                                        "LOADER_IMAGE": loader_image}), \
                patch("subprocess.run", side_effect=execute), \
                patch("time.sleep"), patch("time.monotonic", side_effect=range(0, 10000)):
            try:
                runpy.run_path(str(SOURCE), run_name="__main__")
            except SystemExit as error:
                outcome = error.code
            except AssertionError:
                outcome = 1
            else:
                outcome = 0
        return outcome, sent

    def test_idle_clears_staged_ram_and_verifies_it(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", ramdisk="ready 400000 400000 300000000")
        self.assertEqual(rc, 0)
        self.assertIn(["fastboot", "-s", "xnuloader", "oem", "ramdisk", "none"], sent)

    def test_empty_android_serial_only_polls(self):
        rc, sent = self.invoke("\tfastboot\n")
        self.assertEqual(rc, 1)
        self.assertTrue(all(argv in (["fastboot", "devices"], ["adb", "devices"]) for argv in sent))

    def test_mixed_empty_fastboot_serial_only_polls(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n\tfastboot\n")
        self.assertEqual(rc, 1)
        self.assertTrue(all(argv == ["fastboot", "devices"] for argv in sent))

    def test_mixed_empty_android_serial_only_polls(self):
        rc, sent = self.invoke("", android=True,
                               android_devices="List of devices attached\ntest-android\tdevice\n\tdevice\n")
        self.assertEqual(rc, 1)
        self.assertTrue(all(argv in (["fastboot", "devices"], ["adb", "devices"]) for argv in sent))

    def test_duplicate_loader_stops_before_queries(self):
        rc, sent = self.invoke("xnuloader\tfastboot\nxnuloader\tfastboot\n")
        self.assertEqual(rc, 1)
        self.assertEqual(sent, [["fastboot", "devices"]])

    def test_loader_and_native_identity_stop_before_queries(self):
        rc, sent = self.invoke("xnuloader\tfastboot\ntest-android\tfastboot\n")
        self.assertEqual(rc, 1)
        self.assertEqual(sent, [["fastboot", "devices"]])

    def test_wrong_identity_is_not_changed(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", product="annibale")
        self.assertEqual(rc, 1)
        self.assertFalse(any("oem" in argv for argv in sent))

    def test_invalid_idle_or_ramdisk_state_cannot_pass(self):
        for kwargs in ({"result": "idle 1 0"}, {"result": "idle\nresult: running"},
                       {"ramdisk": "unknown"}, {"ramdisk": "idle 0 0 0 extra"}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.invoke("xnuloader\tfastboot\n", **kwargs)[0], 1)

    def test_runtime_preserves_terminal_logs_before_reset(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True,
                               result="running 0 0", ramdisk="ready 400000 400000 300000000")
        self.assertEqual(rc, 0)
        stop = sent.index(["fastboot", "-s", "xnuloader", "oem", "stop"])
        reset = sent.index(["fastboot", "-s", "xnuloader", "reboot"])
        snapshots = [i for i, argv in enumerate(sent) if "get_staged" in argv]
        self.assertEqual(len(snapshots), 2)
        self.assertTrue(all(stop < i < reset for i in snapshots))
        self.assertEqual(sent[reset + 1], ["fastboot", "devices"])
        self.assertEqual(sent[reset + 2], ["fastboot", "-s", "xnuloader", "oem", "recovery"])

    def test_runtime_without_quiescence_preserves_state(self):
        for terminal in ("running 0 0", "hung-held 100 1", "unknown", "idle 0 0"):
            with self.subTest(terminal=terminal):
                rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True,
                                       result="running 0 0", stop_result=terminal)
                self.assertEqual(rc, 1)
                self.assertFalse(any("reboot" in argv for argv in sent))
                self.assertTrue(any("get_staged" in argv for argv in sent))

    def test_failed_terminal_capture_prevents_reset(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True,
                               result="returned 100 0", capture_failed=True)
        self.assertEqual(rc, 1)
        self.assertFalse(any("reboot" in argv for argv in sent))

    def test_hexadecimal_terminal_address_can_be_recovered(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True, result="returned 10ab 0")
        self.assertEqual(rc, 0)
        self.assertIn(["fastboot", "-s", "xnuloader", "reboot"], sent)

    def test_android_b_recovery_checks_a_retry_readback(self):
        rc, sent = self.invoke("", android=True)
        self.assertEqual(rc, 0)
        self.assertIn(["fastboot", "-s", "test-android", "getvar", "is-userspace"], sent)
        self.assertIn(["fastboot", "-s", "test-android", "getvar", "slot-retry-count:a"], sent)
        self.assertIn(["fastboot", "-s", "test-android", "set_active", "a"], sent)
        self.assertFalse(any("flash" in argv for argv in sent))

    def test_android_b_loader_image_uses_temporary_boot(self):
        rc, sent = self.invoke("", android=True, loader_image="test-loader-only.img")
        self.assertEqual(rc, 0)
        self.assertIn(["fastboot", "-s", "test-android", "boot", "test-loader-only.img"], sent)
        self.assertIn(["fastboot", "-s", "test-android", "getvar", "slot-unbootable:b"], sent)
        self.assertNotIn(["fastboot", "-s", "test-android", "reboot"], sent)
        self.assertFalse(any("flash" in argv or "stage" in argv for argv in sent))

    def test_identified_lk_can_boot_loader_without_android(self):
        rc, sent = self.invoke("test-android\tfastboot\n", android=True,
                               loader_image="test-loader-only.img")
        self.assertEqual(rc, 0)
        self.assertIn(["fastboot", "-s", "test-android", "boot", "test-loader-only.img"], sent)
        self.assertFalse(any(argv[0]=="adb" for argv in sent))

    def test_lk_to_loader_does_not_require_empty_enumeration(self):
        rc, sent = self.invoke("test-android\tfastboot\n", android=True,
                               loader_image="test-loader-only.img",
                               after_boot_devices=["test-android\tfastboot\n", "xnuloader\tfastboot\n"])
        self.assertEqual(rc, 0)
        boot = sent.index(["fastboot", "-s", "test-android", "boot", "test-loader-only.img"])
        self.assertEqual(sent[boot + 1:boot + 4], [
            ["fastboot", "devices"], ["fastboot", "devices"],
            ["fastboot", "-s", "xnuloader", "oem", "recovery"]])

    def test_lk_to_loader_rejects_ambiguous_enumeration(self):
        for devices in ("xnuloader\tfastboot\ntest-android\tfastboot\n",
                        "xnuloader\tfastboot\nxnuloader\tfastboot\n",
                        "xnuloader\tfastboot\nother-device\tfastboot\n"):
            with self.subTest(devices=devices):
                rc, sent = self.invoke("test-android\tfastboot\n", android=True,
                                       loader_image="test-loader-only.img", after_boot_devices=[devices])
                self.assertEqual(rc, 1)
                self.assertNotIn(["fastboot", "-s", "xnuloader", "oem", "recovery"], sent)

    def test_runtime_reset_rejects_ambiguous_enumeration(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True,
                               result="returned 10ab 0",
                               after_boot_devices=["xnuloader\tfastboot\ntest-android\tfastboot\n"])
        self.assertEqual(rc, 1)
        self.assertNotIn(["fastboot", "-s", "xnuloader", "oem", "recovery"], sent)

    def test_runtime_loader_image_preserves_ram_until_native_boot(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True, android=True,
                               result="running 0 0", stop_result="returned 10ab 0",
                               ramdisk="ready 400000 400000 300000000",
                               loader_image="test-loader-only.img")
        self.assertEqual(rc, 0)
        transition = sent.index(["fastboot", "-s", "xnuloader", "oem", "android"])
        snapshots = [i for i, argv in enumerate(sent) if "get_staged" in argv]
        self.assertEqual(len(snapshots), 2)
        self.assertTrue(all(i < transition for i in snapshots))
        self.assertFalse(any("flash" in argv or "stage" in argv or "reboot" in argv for argv in sent))
        self.assertNotIn(["fastboot", "-s", "xnuloader", "oem", "ramdisk", "none"], sent)

    def test_refused_android_transition_stops_runtime_recovery(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True, android=True,
                               result="returned 10ab 0", ramdisk="ready 400000 400000 300000000",
                               loader_image="test-loader-only.img", android_transition_refused=True)
        self.assertEqual(rc, 1)
        self.assertEqual(sent[-1], ["fastboot", "-s", "xnuloader", "oem", "android"])
        self.assertFalse(any("reboot" in argv or "set_active" in argv or "flash" in argv for argv in sent))

    def test_held_loader_image_saves_logs_and_uses_identified_lk(self):
        for initial, terminal in (("returned-held 10ab 0", "returned-held 10ab 0"),
                                  ("hung-held 10ab 0", "hung-held 10ab 0"),
                                  ("running 0 0", "returned-held 10ab 0"),
                                  ("running 0 0", "hung-held 10ab 0")):
            with self.subTest(initial=initial, terminal=terminal):
                rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True, android=True,
                                       result=initial, stop_result=terminal,
                                       ramdisk="ready 400000 400000 300000000",
                                       loader_image="test-loader-only.img")
                self.assertEqual(rc, 0)
                transition = sent.index(["fastboot", "-s", "xnuloader", "reboot-bootloader"])
                snapshots = [i for i, argv in enumerate(sent) if "get_staged" in argv]
                self.assertEqual(len(snapshots), 2)
                serial_log = sent.index(["fastboot", "-s", "xnuloader", "oem", "log"])
                self.assertLess(snapshots[0], serial_log)
                self.assertLess(serial_log, snapshots[1])
                self.assertLess(snapshots[1], transition)
                self.assertEqual(sent[transition + 1], ["fastboot", "devices"])
                lk = sent.index(["fastboot", "-s", "test-android", "getvar", "product"])
                boot = sent.index(["fastboot", "-s", "test-android", "boot", "test-loader-only.img"])
                recovery = sent.index(["fastboot", "-s", "xnuloader", "oem", "recovery"])
                self.assertLess(transition, lk)
                self.assertLess(lk, boot)
                self.assertLess(boot, recovery)
                self.assertIn(["fastboot", "-s", "xnuloader", "getvar", "ramdisk-state"], sent[recovery:])
                self.assertNotIn(["fastboot", "-s", "xnuloader", "oem", "android"], sent)
                self.assertNotIn(["fastboot", "-s", "xnuloader", "oem", "ramdisk", "none"], sent)
                self.assertFalse(any(argv[0] == "adb" or "flash" in argv or "stage" in argv for argv in sent))

    def test_held_lk_transition_failure_stops_after_saved_logs(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True, android=True,
                               result="returned-held 10ab 0", loader_image="test-loader-only.img",
                               reboot_lk_refused=True)
        self.assertEqual(rc, 1)
        self.assertEqual(sent[-1], ["fastboot", "-s", "xnuloader", "reboot-bootloader"])
        self.assertEqual(sum("get_staged" in argv for argv in sent), 2)
        self.assertFalse(any("set_active" in argv or "boot" in argv or "oem" in argv and argv[-1] == "recovery"
                             for argv in sent))

    def test_held_lk_ack_without_identity_does_not_change_resources(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True, android=True,
                               result="returned-held 10ab 0", loader_image="test-loader-only.img",
                               reboot_lk_stays_loader=True)
        self.assertEqual(rc, 1)
        self.assertEqual(sum("reboot-bootloader" in argv for argv in sent), 1)
        self.assertFalse(any("set_active" in argv or "boot" in argv or "recovery" in argv or "none" in argv
                             for argv in sent))

    def test_held_capture_failure_prevents_lk_transition(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True, android=True,
                               result="returned-held 10ab 0", loader_image="test-loader-only.img",
                               capture_failed=True)
        self.assertEqual(rc, 1)
        self.assertFalse(any("reboot-bootloader" in argv or "set_active" in argv or "boot" in argv
                             for argv in sent))

    def test_held_lk_requires_identity_and_b_safety_before_slot_selection(self):
        for values in ({"lk_product": "other"}, {"lk_userspace": "yes"},
                       {"lk_b_successful": "no"}, {"lk_b_unbootable": "yes"}):
            with self.subTest(values=values):
                rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True, android=True,
                                       result="returned-held 10ab 0", loader_image="test-loader-only.img",
                                       **values)
                self.assertEqual(rc, 1)
                self.assertIn(["fastboot", "-s", "test-android", "getvar", "product"], sent)
                self.assertFalse(any("set_active" in argv or "boot" in argv for argv in sent))

    def test_held_loader_image_requires_final_identity_idle_and_ram_state(self):
        for values in ({"boot_product": "other"}, {"boot_result": "returned-held 10ab 0"},
                       {"boot_ramdisk": "unknown"}):
            with self.subTest(values=values):
                rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True, android=True,
                                       result="returned-held 10ab 0", loader_image="test-loader-only.img",
                                       **values)
                self.assertEqual(rc, 1)
                self.assertIn(["fastboot", "-s", "test-android", "boot", "test-loader-only.img"], sent)
                self.assertNotIn(["fastboot", "-s", "xnuloader", "oem", "ramdisk", "none"], sent)
                self.assertEqual(sum("reboot-bootloader" in argv for argv in sent), 1)

    def test_terminal_recovery_ack_cannot_clear_resident_before_native_boot(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", runtime=True, android=True,
                               result="returned 10ab 0", ramdisk="ready 400000 400000 300000000",
                               loader_image="test-loader-only.img", legacy_terminal_recovery=True)
        self.assertEqual(rc, 0)
        boot = sent.index(["fastboot", "-s", "test-android", "boot", "test-loader-only.img"])
        recovery = sent.index(["fastboot", "-s", "xnuloader", "oem", "recovery"])
        self.assertGreater(recovery, boot)
        self.assertNotIn(["fastboot", "-s", "xnuloader", "oem", "ramdisk", "none"], sent)

    def test_android_return_rejects_wrong_lk_product_before_slot_selection(self):
        for product in ("other", "annibale-extra", "annibale\nproduct: other"):
            with self.subTest(product=product):
                rc, sent = self.invoke("", android=True, lk_product=product)
                self.assertEqual(rc, 1)
                self.assertFalse(any("set_active" in argv for argv in sent))
                self.assertNotIn(["fastboot", "-s", "test-android", "reboot"], sent)

    def test_android_return_rejects_userspace_fastboot_before_slot_selection(self):
        for userspace in ("yes", "", "unknown"):
            with self.subTest(userspace=userspace):
                rc, sent = self.invoke("", android=True, lk_userspace=userspace)
                self.assertEqual(rc, 1)
                self.assertIn(["fastboot", "-s", "test-android", "getvar", "is-userspace"], sent)
                self.assertFalse(any("set_active" in argv for argv in sent))
                self.assertNotIn(["fastboot", "-s", "test-android", "reboot"], sent)

    def test_android_return_requires_boot_completed_before_reboot(self):
        for completed in ("", "0", "1 extra"):
            with self.subTest(completed=completed):
                rc, sent = self.invoke("", android=True, android_boot_completed=completed)
                self.assertEqual(rc, 1)
                self.assertNotIn(["adb", "-s", "test-android", "reboot", "bootloader"], sent)

    def test_android_return_requires_successful_bootable_b_before_slot_selection(self):
        for values in ({"lk_b_successful": "no"}, {"lk_b_successful": "yes extra"},
                       {"lk_b_successful": "yes\nslot-successful:b: no"},
                       {"lk_b_unbootable": "yes"}, {"lk_b_unbootable": "unknown"},
                       {"lk_b_unbootable": "no\nslot-unbootable:b: yes"}):
            with self.subTest(values=values):
                rc, sent = self.invoke("", android=True, **values)
                self.assertEqual(rc, 1)
                self.assertFalse(any("set_active" in argv for argv in sent))
                self.assertNotIn(["fastboot", "-s", "test-android", "reboot"], sent)


if __name__ == "__main__":
    unittest.main()
