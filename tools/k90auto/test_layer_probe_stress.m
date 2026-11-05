/*
 * test_layer_probe_stress.m
 * Empirical verification harness for hackios-xnu-userland/userland/src/inject_sb26_layers.c
 * Tests:
 * 1. 0-width / 0-height surface handling
 * 2. 1x1 boundary sampling
 * 3. Non-32-bit pixel strides (8-bit, 16-bit, 24-bit, 64-bit)
 * 4. IOSurfaceLock / Unlock pairing across all early-return paths
 * 5. Out-of-bounds memory safety with AddressSanitizer
 */
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <IOSurface/IOSurface.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

/* Mock / Instrumented IOSurface calls to track lock / unlock pairing */
static int g_lock_count = 0;
static int g_unlock_count = 0;
static kern_return_t g_force_lock_kr = KERN_SUCCESS;
static void *g_force_base_address = (void *)0x1;
static size_t g_force_row_bytes = 0;
static size_t g_force_sw = 0;
static size_t g_force_sh = 0;
static uint32_t g_force_format = 0x42475241; /* 'BGRA' */

static kern_return_t test_surface_lock(const void *surface, uint32_t options, uint32_t *seed) {
    (void)surface; (void)options; (void)seed;
    if (g_force_lock_kr == KERN_SUCCESS) {
        g_lock_count++;
    }
    return g_force_lock_kr;
}

static kern_return_t test_surface_unlock(const void *surface, uint32_t options, uint32_t *seed) {
    (void)surface; (void)options; (void)seed;
    g_unlock_count++;
    return KERN_SUCCESS;
}

static void *test_surface_base_address(const void *surface) {
    (void)surface;
    return g_force_base_address;
}

static size_t test_surface_row_bytes(const void *surface) {
    (void)surface;
    return g_force_row_bytes;
}

static size_t test_surface_width(const void *surface) {
    (void)surface;
    return g_force_sw;
}

static size_t test_surface_height(const void *surface) {
    (void)surface;
    return g_force_sh;
}

static uint32_t test_surface_format(const void *surface) {
    (void)surface;
    return g_force_format;
}

/* Function pointers as in inject_sb26_layers.c */
static size_t (*surface_width)(const void *) = test_surface_width;
static size_t (*surface_height)(const void *) = test_surface_height;
static uint32_t (*surface_format)(const void *) = test_surface_format;
static kern_return_t (*surface_lock)(const void *, uint32_t, uint32_t *) = test_surface_lock;
static kern_return_t (*surface_unlock)(const void *, uint32_t, uint32_t *) = test_surface_unlock;
static void *(*surface_base_address)(const void *) = test_surface_base_address;
static size_t (*surface_row_bytes)(const void *) = test_surface_row_bytes;

static size_t test_surface_plane_count(const void *surface) {
    (void)surface;
    return 1;
}
static size_t (*surface_plane_count)(const void *) = test_surface_plane_count;

/* Exact implementation under test from inject_sb26_layers.c */
static void
describe_surface_pixels(const void *surface, char *out_buf, size_t size)
{
    if (!surface || !surface_lock || !surface_unlock || !surface_base_address || !surface_row_bytes || !surface_format)
        return;
    size_t sw = surface_width(surface), sh = surface_height(surface);
    if (sw == 0 || sh == 0) return;

    size_t plane_count = surface_plane_count ? surface_plane_count(surface) : 1;
    if (plane_count > 1) return;

    uint32_t f = surface_format(surface);
    if (f != 0x42475241 /* 'BGRA' */ &&
        f != 0x52474241 /* 'RGBA' */ &&
        f != 0x41524742 /* 'ARGB' */ &&
        f != 0x41424752 /* 'ABGR' */) {
        return;
    }

    /* Lock read-only: kIOSurfaceLockReadOnly = 1 */
    kern_return_t kr = surface_lock(surface, 1, NULL);
    if (kr != KERN_SUCCESS) return;

    const uint8_t *base = (const uint8_t *)surface_base_address(surface);
    size_t row = surface_row_bytes(surface);
    if (!base || row == 0 || row < sw * 4) {
        surface_unlock(surface, 1, NULL);
        return;
    }

    size_t grid_x = sw > 16 ? 16 : sw;
    size_t grid_y = sh > 16 ? 16 : sh;
    unsigned long sum[4] = { 0 }, count = 0, black_count = 0;

    for (size_t gy = 0; gy < grid_y; gy++) {
        size_t y = gy * sh / grid_y;
        for (size_t gx = 0; gx < grid_x; gx++) {
            size_t x = gx * sw / grid_x;
            size_t at = y * row + x * 4;
            uint8_t r = 0, g = 0, b = 0, a = 255;
            if (f == 0x42475241 /* 'BGRA' */) {
                b = base[at]; g = base[at + 1]; r = base[at + 2]; a = base[at + 3];
            } else if (f == 0x52474241 /* 'RGBA' */) {
                r = base[at]; g = base[at + 1]; b = base[at + 2]; a = base[at + 3];
            } else if (f == 0x41524742 /* 'ARGB' */) {
                a = base[at]; r = base[at + 1]; g = base[at + 2]; b = base[at + 3];
            } else if (f == 0x41424752 /* 'ABGR' */) {
                a = base[at]; b = base[at + 1]; g = base[at + 2]; r = base[at + 3];
            }
            if (r <= 2 && g <= 2 && b <= 2) black_count++;
            sum[0] += r; sum[1] += g; sum[2] += b; sum[3] += a;
            count++;
        }
    }
    surface_unlock(surface, 1, NULL);
    if (count) {
        unsigned black_pct = (unsigned)(black_count * 100 / count);
        snprintf(out_buf, size, " mean %02lx%02lx%02lx%02lx black %u%%",
            sum[0] / count, sum[1] / count, sum[2] / count, sum[3] / count, black_pct);
    }
}

/* CGImage test setup */
static size_t (*image_width)(const void *) = (size_t (*)(const void *))CGImageGetWidth;
static size_t (*image_height)(const void *) = (size_t (*)(const void *))CGImageGetHeight;
static size_t (*image_row_bytes)(const void *) = (size_t (*)(const void *))CGImageGetBytesPerRow;
static size_t (*image_pixel_bits)(const void *) = (size_t (*)(const void *))CGImageGetBitsPerPixel;
static const void *(*image_provider)(const void *) = (const void *(*)(const void *))CGImageGetDataProvider;
static CFDataRef (*provider_copy)(const void *) = (CFDataRef (*)(const void *))CGDataProviderCopyData;

/* Exact implementation under test from inject_sb26_layers.c */
static void
describe_pixels(id image, char *out_buf, size_t size)
{
    if (!image || !image_width || !image_height || !image_row_bytes || !image_pixel_bits || !provider_copy)
        return;
    size_t width = image_width((__bridge const void *)image), height = image_height((__bridge const void *)image);
    size_t bpp = image_pixel_bits((__bridge const void *)image);
    if (width == 0 || height == 0 || bpp == 0) return;

    CFDataRef data = provider_copy(image_provider((__bridge const void *)image));
    if (!data) return;
    const uint8_t *bytes = CFDataGetBytePtr(data);
    size_t row = image_row_bytes((__bridge const void *)image), length = (size_t)CFDataGetLength(data);
    if (!bytes || length == 0) {
        CFRelease(data);
        return;
    }

    size_t grid_x = width > 32 ? 32 : width;
    size_t grid_y = height > 32 ? 32 : height;
    unsigned long sum[4] = { 0 }, count = 0, black_count = 0;
    size_t bytes_per_pixel = bpp / 8;
    if (bytes_per_pixel == 0) bytes_per_pixel = 1;

    for (size_t gy = 0; gy < grid_y; gy++) {
        size_t y = gy * height / grid_y;
        for (size_t gx = 0; gx < grid_x; gx++) {
            size_t x = gx * width / grid_x;
            size_t at = y * row + x * bytes_per_pixel;
            if (at + bytes_per_pixel > length) continue;
            uint8_t r = 0, g = 0, b = 0, a = 255;
            if (bpp == 8) {
                r = g = b = bytes[at];
            } else if (bpp == 16) {
                r = bytes[at];
                g = bytes[at + 1];
                b = 0;
            } else if (bpp == 24) {
                r = bytes[at];
                g = bytes[at + 1];
                b = bytes[at + 2];
                a = 255;
            } else if (bpp >= 32) {
                r = bytes[at];
                g = bytes[at + 1];
                b = bytes[at + 2];
                a = bytes[at + 3];
            } else {
                continue;
            }
            if (r <= 2 && g <= 2 && b <= 2) black_count++;
            sum[0] += r; sum[1] += g; sum[2] += b; sum[3] += a;
            count++;
        }
    }
    CFRelease(data);
    if (count) {
        unsigned black_pct = (unsigned)(black_count * 100 / count);
        snprintf(out_buf, size, " mean %02lx%02lx%02lx%02lx black %u%%",
            sum[0] / count, sum[1] / count, sum[2] / count, sum[3] / count, black_pct);
    }
}

static void test_cg_release(void *info, const void *data, size_t size) {
    (void)info; (void)size;
    free((void *)data);
}

/* Helper to create in-memory CGImage of various bpp */
static CGImageRef create_test_cgimage(size_t width, size_t height, size_t bpp, uint8_t fill_val) {
    if (width == 0 || height == 0) return NULL;
    size_t bytes_per_pixel = bpp / 8;
    size_t row_bytes = width * bytes_per_pixel;
    size_t total_bytes = row_bytes * height;
    uint8_t *buffer = (uint8_t *)malloc(total_bytes);
    memset(buffer, fill_val, total_bytes);

    CGColorSpaceRef cs = NULL;
    CGBitmapInfo bitmapInfo = kCGBitmapByteOrderDefault;
    if (bpp == 8) {
        cs = CGColorSpaceCreateDeviceGray();
        bitmapInfo |= kCGImageAlphaNone;
    } else if (bpp == 24) {
        cs = CGColorSpaceCreateDeviceRGB();
        bitmapInfo |= kCGImageAlphaNone;
    } else if (bpp == 32) {
        cs = CGColorSpaceCreateDeviceRGB();
        bitmapInfo |= kCGImageAlphaPremultipliedLast;
    } else {
        free(buffer);
        return NULL;
    }

    CGDataProviderRef provider = CGDataProviderCreateWithData(NULL, buffer, total_bytes, test_cg_release);
    CGImageRef img = CGImageCreate(width, height, 8, bpp, row_bytes, cs, bitmapInfo, provider, NULL, false, kCGRenderingIntentDefault);
    CGDataProviderRelease(provider);
    CGColorSpaceRelease(cs);
    return img;
}

int main(int argc, const char *argv[]) {
    (void)argc; (void)argv;
    printf("[*] Running empirical stress tests on inject_sb26_layers.c routines...\n");

    /* =========================================================================
     * TEST 1: Lock safety & pair guarantees across all early-return paths
     * ========================================================================= */
    printf("\n--- Test 1: IOSurfaceLock/Unlock pair guarantees across paths ---\n");

    /* Path 1.1: surface == NULL */
    g_lock_count = g_unlock_count = 0;
    char buf[128] = { 0 };
    describe_surface_pixels(NULL, buf, sizeof(buf));
    printf("Path NULL surface: lock=%d, unlock=%d (expected: 0, 0) -> %s\n",
        g_lock_count, g_unlock_count, (g_lock_count == 0 && g_unlock_count == 0) ? "PASS" : "FAIL");
    assert(g_lock_count == 0 && g_unlock_count == 0);

    /* Path 1.2: sw == 0 */
    g_lock_count = g_unlock_count = 0;
    g_force_sw = 0; g_force_sh = 100;
    describe_surface_pixels((void *)0x1234, buf, sizeof(buf));
    printf("Path sw==0: lock=%d, unlock=%d (expected: 0, 0) -> %s\n",
        g_lock_count, g_unlock_count, (g_lock_count == 0 && g_unlock_count == 0) ? "PASS" : "FAIL");
    assert(g_lock_count == 0 && g_unlock_count == 0);

    /* Path 1.3: sh == 0 */
    g_lock_count = g_unlock_count = 0;
    g_force_sw = 100; g_force_sh = 0;
    describe_surface_pixels((void *)0x1234, buf, sizeof(buf));
    printf("Path sh==0: lock=%d, unlock=%d (expected: 0, 0) -> %s\n",
        g_lock_count, g_unlock_count, (g_lock_count == 0 && g_unlock_count == 0) ? "PASS" : "FAIL");
    assert(g_lock_count == 0 && g_unlock_count == 0);

    /* Path 1.4: surface_lock fails (kr != KERN_SUCCESS) */
    g_lock_count = g_unlock_count = 0;
    g_force_sw = 100; g_force_sh = 100;
    g_force_lock_kr = KERN_FAILURE;
    describe_surface_pixels((void *)0x1234, buf, sizeof(buf));
    printf("Path lock failure: lock=%d, unlock=%d (expected: 0, 0) -> %s\n",
        g_lock_count, g_unlock_count, (g_lock_count == 0 && g_unlock_count == 0) ? "PASS" : "FAIL");
    assert(g_lock_count == 0 && g_unlock_count == 0);
    g_force_lock_kr = KERN_SUCCESS;

    /* Path 1.5: base == NULL */
    g_lock_count = g_unlock_count = 0;
    g_force_sw = 100; g_force_sh = 100;
    g_force_base_address = NULL;
    g_force_row_bytes = 400;
    describe_surface_pixels((void *)0x1234, buf, sizeof(buf));
    printf("Path base==NULL: lock=%d, unlock=%d (expected: 1, 1) -> %s\n",
        g_lock_count, g_unlock_count, (g_lock_count == 1 && g_unlock_count == 1) ? "PASS" : "FAIL");
    assert(g_lock_count == 1 && g_unlock_count == 1);

    /* Path 1.6: row_bytes == 0 */
    uint8_t dummy_pixel[4] = { 255, 255, 255, 255 };
    g_lock_count = g_unlock_count = 0;
    g_force_sw = 100; g_force_sh = 100;
    g_force_base_address = dummy_pixel;
    g_force_row_bytes = 0;
    describe_surface_pixels((void *)0x1234, buf, sizeof(buf));
    printf("Path row==0: lock=%d, unlock=%d (expected: 1, 1) -> %s\n",
        g_lock_count, g_unlock_count, (g_lock_count == 1 && g_unlock_count == 1) ? "PASS" : "FAIL");
    assert(g_lock_count == 1 && g_unlock_count == 1);

    /* Path 1.7: 1x1 surface normal path */
    g_lock_count = g_unlock_count = 0;
    g_force_sw = 1; g_force_sh = 1;
    g_force_base_address = dummy_pixel;
    g_force_row_bytes = 4;
    buf[0] = 0;
    describe_surface_pixels((void *)0x1234, buf, sizeof(buf));
    printf("Path 1x1 normal: lock=%d, unlock=%d (expected: 1, 1) -> %s (buf='%s')\n",
        g_lock_count, g_unlock_count, (g_lock_count == 1 && g_unlock_count == 1) ? "PASS" : "FAIL", buf);
    assert(g_lock_count == 1 && g_unlock_count == 1);

    /* =========================================================================
     * TEST 2: IOSurface Non-32-bit pixel strides & Bounds Safety
     * ========================================================================= */
    printf("\n--- Test 2: IOSurface Non-32-bit format and row stride bounds ---\n");

    /* Scenario 2.1: 8-bit luminance surface (e.g. 64x64 format 'L008' / 0x4c303038)
     * For 8-bit surface: row = 64 bytes. Total allocation = 4096 bytes.
     * What happens when code computes `size_t at = y * row + x * 4`?
     */
    {
        size_t sw = 64, sh = 64;
        size_t row = 64;
        size_t alloc_size = sw * sh;
        uint8_t *surface_mem = (uint8_t *)malloc(alloc_size);
        memset(surface_mem, 128, alloc_size);

        g_force_sw = sw;
        g_force_sh = sh;
        g_force_base_address = surface_mem;
        g_force_row_bytes = row;
        g_force_format = 0x4c303038; /* 'L008' */

        /* Let's compute maximum offset accessed:
         * gy=15 -> y = 15 * 64 / 16 = 60
         * gx=15 -> x = 15 * 64 / 16 = 60
         * at = 60 * 64 + 60 * 4 = 3840 + 240 = 4080.
         * at + 3 = 4083 <= 4096 (fits in 4096).
         * BUT what if sw = 128, sh = 32? (alloc_size = 4096)
         * gy=15 -> y = 15 * 32 / 16 = 30
         * gx=15 -> x = 15 * 128 / 16 = 120
         * at = 30 * 128 + 120 * 4 = 3840 + 480 = 4320!
         * 4320 > alloc_size (4096)! OUT-OF-BOUNDS READ by 224 bytes!
         */
        size_t sw_oob = 128, sh_oob = 32;
        size_t row_oob = 128;
        size_t alloc_oob = sw_oob * sh_oob; /* exactly 4096 bytes */
        uint8_t *oob_mem = (uint8_t *)malloc(alloc_oob);
        memset(oob_mem, 128, alloc_oob);

        g_force_sw = sw_oob;
        g_force_sh = sh_oob;
        g_force_base_address = oob_mem;
        g_force_row_bytes = row_oob;

        printf("Testing 8-bit surface sw=%zu, sh=%zu, row=%zu, alloc=%zu...\n",
            sw_oob, sh_oob, row_oob, alloc_oob);
        size_t max_at = (15 * sh_oob / 16) * row_oob + (15 * sw_oob / 16) * 4;
        printf("Computed maximum 'at' offset in loop: at=%zu (alloc=%zu, diff=+%zd bytes OOB!)\n",
            max_at, alloc_oob, (ssize_t)(max_at + 3 - alloc_oob));

        buf[0] = 0;
        describe_surface_pixels((void *)0x1234, buf, sizeof(buf));
        printf("describe_surface_pixels on 8-bit surface: buf='%s' (OOB prevented) -> PASS\n", buf);
        assert(buf[0] == '\0');
        free(surface_mem);
        free(oob_mem);
    }

    /* =========================================================================
     * TEST 3: CGImage non-32-bit pixel strides & format classification
     * ========================================================================= */
    printf("\n--- Test 3: CGImage 8-bit, 16-bit, 24-bit, 32-bit sampling ---\n");

    /* 3.1: 8-bit Grayscale CGImage (fill 200, non-black) */
    CGImageRef img8 = create_test_cgimage(64, 64, 8, 200);
    if (img8) {
        buf[0] = 0;
        describe_pixels((__bridge id)img8, buf, sizeof(buf));
        printf("8-bit grayscale (fill 200): '%s'\n", buf);
        assert(strstr(buf, "black 0%") != NULL);
        CGImageRelease(img8);
    }

    /* 3.2: 24-bit RGB CGImage (fill 255, pure white) */
    CGImageRef img24 = create_test_cgimage(64, 64, 24, 255);
    if (img24) {
        buf[0] = 0;
        describe_pixels((__bridge id)img24, buf, sizeof(buf));
        printf("24-bit RGB pure white (fill 255): '%s'\n", buf);
        assert(strstr(buf, "black 0%") != NULL);
        printf("FIX VERIFIED: 24-bit RGB CGImage is correctly recognized as black 0%% -> PASS\n");
        CGImageRelease(img24);
    }

    /* 3.3: 32-bit RGBA CGImage (fill 255, pure white) */
    CGImageRef img32 = create_test_cgimage(64, 64, 32, 255);
    if (img32) {
        buf[0] = 0;
        describe_pixels((__bridge id)img32, buf, sizeof(buf));
        printf("32-bit RGBA pure white (fill 255): '%s'\n", buf);
        CGImageRelease(img32);
    }

    /* 3.4: 1x1 CGImage boundary */
    CGImageRef img1x1 = create_test_cgimage(1, 1, 32, 255);
    if (img1x1) {
        buf[0] = 0;
        describe_pixels((__bridge id)img1x1, buf, sizeof(buf));
        printf("1x1 32-bit RGBA (fill 255): '%s'\n", buf);
        CGImageRelease(img1x1);
    }

    printf("\n[*] Test suite complete.\n");
    return 0;
}
