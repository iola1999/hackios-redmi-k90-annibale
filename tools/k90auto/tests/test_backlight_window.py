#!/usr/bin/env python3
"""Run the production brightness request handler with host-side IOKit substitutes."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'hackios-xnu-kernel/xnu/files/iokit/Kernel/MiniAppleARMBacklight.cpp'


def main():
    source = SOURCE.read_text()
    start = source.index('static void\nbl_take(')
    end = source.index('\n/* brightness and brightness-nits', start)
    constants = '\n'.join(re.findall(r'^#define kBL\w+.*$', source, re.M))
    prefix = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
struct OSObject { virtual ~OSObject() = default; };
struct OSNumber : OSObject {
 uint64_t value; explicit OSNumber(uint64_t v): value(v) {}
 uint64_t unsigned64BitValue() const { return value; }
};
struct OSDictionary : OSObject {
 std::map<std::string, OSObject *> values;
 OSObject *getObject(const char *key) { auto i = values.find(key); return i == values.end() ? nullptr : i->second; }
};
#define OSDynamicCast(type, object) dynamic_cast<type *>(object)
#define NSEC_PER_MSEC 1000000ULL
static uint64_t tick = 1, applied_nits;
static unsigned writes;
static uint32_t redwood_backlight_level;
struct Service { void publish(uint64_t, uint64_t nits) { applied_nits = nits; writes++; } } service;
static struct {
 bool initialized = true, slider_initialized = false;
 uint64_t last_slider_pos = 0, user_until = 0;
 Service *service = &::service;
 char line[320];
} bl;
static uint64_t mach_absolute_time() { return tick; }
static void nanoseconds_to_absolutetime(uint64_t n, uint64_t *out) { *out = n; }
static void proc_selfname(char *out, size_t n) { snprintf(out,n,"test"); }
static int proc_selfpid() { return 1; }
static size_t list_keys(char *, size_t, size_t used, OSDictionary *) { return used; }
static void bl_log() {}
static bool MiniIOMobileFramebufferDCS(uint32_t) { return true; }
static void MiniIOMobileFramebufferDim(uint32_t) {}
static int MiniIOMobileFramebufferDimShown() { return -1; }
static uint64_t fixed_nits(uint64_t n) { return (n << 16) / 1000; }
'''
    tests = r'''
int main() {
 OSNumber slider(65536), nits(100ULL << 16);
 OSDictionary position, backlight, framebuffer;
 position.values["DisplayBrightnessSliderPosition"] = &slider;
 backlight.values["brightness-nits"] = &nits;
 framebuffer.values["IOMFBBrightnessLevel"] = &nits;
 bl_take(&framebuffer, nullptr, "IOMFBBrightnessLevel");
 assert(writes == 0);
 bl_take(&position, "brightness", "brightness-nits");
 assert(writes == 0 && bl.user_until == 0);
 slider.value = 32768;
 bl_take(&position, "brightness", "brightness-nits");
 assert(writes == 1 && applied_nits == 202500);
 uint64_t deadline = bl.user_until;
 tick += 10 * NSEC_PER_MSEC;
 bl_take(&backlight, "brightness", "brightness-nits");
 assert(writes == 2 && applied_nits == 100000 && bl.user_until == deadline);
 nits.value = 80ULL << 16;
 tick = deadline;
 bl_take(&framebuffer, nullptr, "IOMFBBrightnessLevel");
 assert(writes == 3 && applied_nits == 80000 && bl.user_until == deadline);
 tick = deadline + 1;
 nits.value = 200ULL << 16;
 bl_take(&framebuffer, nullptr, "IOMFBBrightnessLevel");
 bl_take(&backlight, "brightness", "brightness-nits");
 assert(writes == 3 && applied_nits == 80000);
 slider.value += 32;
 bl_take(&position, "brightness", "brightness-nits");
 assert(writes == 3 && bl.user_until == deadline);
 puts("backlight slider-window tests passed");
}
'''
    with tempfile.TemporaryDirectory(prefix='backlight-window-') as directory:
        path = Path(directory)
        (path / 'test.cpp').write_text(constants + '\n' + prefix + source[start:end] + tests)
        subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-but-set-variable', '-fsanitize=address,undefined',
                        str(path / 'test.cpp'), '-o', str(path / 'test')], check=True)
        subprocess.run([str(path / 'test')], check=True)


if __name__ == '__main__':
    main()
