/*
 * test_annibale_audit_stress.m
 * Empirical stress test harness for annibalemetal_diag.inc Render Pass audit logic.
 *
 * Tests:
 * 1. Thread safety & data race detection with ThreadSanitizer
 * 2. Attachment edge cases:
 *    - Nil color textures in single and multi-attachment passes
 *    - Depth-only passes (colorCount == 0, depth != nil)
 *    - Multi-sampled passes (sampleCount == 4, resolve != nil)
 *    - Stencil clears & depth clears
 *    - Missing selectors / NULL mesaTexture
 *    - Pure black warning accuracy
 */
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <objc/message.h>
#include <notify.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <unistd.h>

/* Mock rw_print */
static char g_last_print[4096] = { 0 };
static int g_print_count = 0;
static int g_warn_count = 0;
static pthread_mutex_t g_print_mutex = PTHREAD_MUTEX_INITIALIZER;

static void rw_print(const char *format, ...) {
    va_list args;
    va_start(args, format);
    pthread_mutex_lock(&g_print_mutex);
    vsnprintf(g_last_print, sizeof(g_last_print), format, args);
    g_print_count++;
    if (strstr(g_last_print, "audit-warn")) {
        g_warn_count++;
    }
    // printf("%s", g_last_print);
    pthread_mutex_unlock(&g_print_mutex);
    va_end(args);
}

/* Mock mesa struct */
struct rwa_texture { int id; };
static uint8_t g_mock_thumb_rgba[16 * 16 * 4];
static int g_mock_thumb_ret = 0;

static int mock_texture_thumbnail(struct rwa_texture *t, unsigned w, unsigned h, uint8_t *rgba) {
    (void)t; (void)w; (void)h;
    if (g_mock_thumb_ret != 0) return g_mock_thumb_ret;
    memcpy(rgba, g_mock_thumb_rgba, 16 * 16 * 4);
    return 0;
}

static struct {
    int (*texture_thumbnail)(struct rwa_texture *texture, unsigned w, unsigned h, uint8_t *rgba);
} mesa = { mock_texture_thumbnail };

/* Mock classes */
@interface MockPipeline : NSObject
- (void *)render;
@end
@implementation MockPipeline
- (void *)render { return (void *)0xdeadbeef; }
@end

@interface MockTexture : NSObject {
    NSUInteger _w, _h, _fmt, _samples;
    BOOL _is_surface;
    BOOL _has_mesa;
    struct rwa_texture _mt;
}
@property (nonatomic, assign) NSUInteger width;
@property (nonatomic, assign) NSUInteger height;
@property (nonatomic, assign) NSUInteger pixelFormat;
@property (nonatomic, assign) NSUInteger sampleCount;
@property (nonatomic, assign) BOOL isSurface;
@property (nonatomic, assign) BOOL hasMesa;
- (struct __IOSurface *)iosurface;
- (struct rwa_texture *)mesaTexture;
@end

@implementation MockTexture
@synthesize width = _w, height = _h, pixelFormat = _fmt, sampleCount = _samples;
@synthesize isSurface = _is_surface, hasMesa = _has_mesa;

- (instancetype)initWithWidth:(NSUInteger)w height:(NSUInteger)h format:(NSUInteger)fmt samples:(NSUInteger)samples isSurface:(BOOL)isSurface hasMesa:(BOOL)hasMesa {
    if ((self = [super init])) {
        _w = w; _h = h; _fmt = fmt; _samples = samples;
        _is_surface = isSurface;
        _has_mesa = hasMesa;
        _mt.id = 1;
    }
    return self;
}
- (struct __IOSurface *)iosurface {
    return _is_surface ? (struct __IOSurface *)0x1234 : NULL;
}
- (BOOL)respondsToSelector:(SEL)aSelector {
    if (aSelector == sel_registerName("mesaTexture")) {
        return _has_mesa;
    }
    return [super respondsToSelector:aSelector];
}
- (struct rwa_texture *)mesaTexture {
    return _has_mesa ? &_mt : NULL;
}
@end

/* Mock AnnibaleMetalWork as defined in annibalemetal_work_private.h */
@interface AnnibaleMetalWork : NSObject {
@public
    id pipeline;
    id render;
    id color[8];
    unsigned colorCount;
    id resolve[8];
    float clearColor[4];
    BOOL clears;
    unsigned discards;
    id depth;
    id depthStencilState;
    float clearDepth;
    unsigned clearStencil;
    BOOL clearsDepth, clearsStencil;
    unsigned primitive, vertexStart, vertexCount;
}
@end
@implementation AnnibaleMetalWork
@end

/* Now bring in exact logic from annibalemetal_diag.inc lines 595-725 */
static _Atomic int rw_audit_wanted_frame = -1;
static _Atomic bool rw_audit_active = false;

static void
rw_audit_setup_notify(void)
{
	static dispatch_once_t once;
	dispatch_once(&once, ^{
		int token;
		notify_register_dispatch("com.annibale.audit.pass", &token, dispatch_get_main_queue(), ^(int t) {
			(void)t;
			atomic_store_explicit(&rw_audit_active, true, memory_order_release);
			rw_print("audit: single-frame pass audit requested via notification\n");
		});
	});
}

static bool
rw_audit_frame_active(unsigned commit)
{
	rw_audit_setup_notify();
	int wanted = atomic_load_explicit(&rw_audit_wanted_frame, memory_order_acquire);
	if (wanted < 0) {
		const char *env = getenv("ANNIBALE_AUDIT_FRAME");
		int parsed = -2;
		if (env != NULL) {
			if (strcmp(env, "all") == 0)
				parsed = 0;
			else
				parsed = atoi(env);
		}
		int expected = wanted;
		atomic_compare_exchange_strong_explicit(&rw_audit_wanted_frame, &expected, parsed,
							memory_order_acq_rel, memory_order_acquire);
		wanted = atomic_load_explicit(&rw_audit_wanted_frame, memory_order_acquire);
	}
	if (wanted >= 0) {
		if (wanted == 0 || commit == (unsigned)wanted)
			return true;
	}
	return atomic_load_explicit(&rw_audit_active, memory_order_acquire);
}

static void
rw_audit_commit_begin(NSArray *works, unsigned commit)
{
	if (!rw_audit_frame_active(commit))
		return;
	rw_print("audit-pass begin: commit %u total_works %lu\n", commit, (unsigned long)[works count]);
}

static void
rw_audit_render_work(AnnibaleMetalWork *work, unsigned commit, unsigned index)
{
	if (!rw_audit_frame_active(commit) || work == nil || work->render == nil)
		return;

	void *pipeline_render = ((void *(*)(id, SEL))objc_msgSend)(work->render, sel_registerName("render"));
	rw_print("audit-pass work %u: pipeline %p prim %u vert %u+%u\n",
	    index, pipeline_render, work->primitive, work->vertexStart, work->vertexCount);

	for (unsigned i = 0; i < work->colorCount; i++) {
		id tex = work->color[i];
		if (tex == nil)
			continue;
		BOOL is_surface = [(id<MTLTexture>)tex iosurface] != NULL;
		BOOL is_clear = work->clears;
		BOOL is_discard = (work->discards & (1u << i)) != 0;
		const char *load_str = is_clear ? "clear" : is_discard ? "dontCare" : "load";
		const char *store_str = work->resolve[i] != nil ? "resolve" : "store";

		rw_print("audit-pass color %u: %lux%lu format %lu s%lu mem=%s load=%s store=%s%s\n",
		    i,
		    (unsigned long)[(id<MTLTexture>)tex width],
		    (unsigned long)[(id<MTLTexture>)tex height],
		    (unsigned long)[(id<MTLTexture>)tex pixelFormat],
		    (unsigned long)[(id<MTLTexture>)tex sampleCount],
		    is_surface ? "surface" : "own",
		    load_str, store_str,
		    is_clear ? " [cleared]" : "");

		if (mesa.texture_thumbnail != NULL) {
			uint8_t sample_rgba[16 * 16 * 4];
			SEL mt_sel = sel_registerName("mesaTexture");
			struct rwa_texture *mt = [tex respondsToSelector:mt_sel]
			    ? ((struct rwa_texture *(*)(id, SEL))objc_msgSend)(tex, mt_sel) : NULL;
			if (mt != NULL && mesa.texture_thumbnail(mt, 16, 16, sample_rgba) == 0) {
				bool all_black = true;
				for (int p = 0; p < 16 * 16; p++) {
					if (sample_rgba[p * 4 + 0] > 2 ||
					    sample_rgba[p * 4 + 1] > 2 ||
					    sample_rgba[p * 4 + 2] > 2) {
						all_black = false;
						break;
					}
				}
				if (all_black) {
					rw_print("audit-warn: pass %u work %u color %u drew pure black (size %lux%lu, format %lu)\n",
					    commit, index, i,
					    (unsigned long)[(id<MTLTexture>)tex width],
					    (unsigned long)[(id<MTLTexture>)tex height],
					    (unsigned long)[(id<MTLTexture>)tex pixelFormat]);
				}
			}
		}
	}

	if (work->depth != nil) {
		id dtex = work->depth;
		rw_print("audit-pass depth: %lux%lu format %lu load=%s%s\n",
		    (unsigned long)[(id<MTLTexture>)dtex width],
		    (unsigned long)[(id<MTLTexture>)dtex height],
		    (unsigned long)[(id<MTLTexture>)dtex pixelFormat],
		    work->clearsDepth ? "clear" : "load",
		    work->clearsStencil ? " stencil_clear" : "");
	}
}

static void
rw_audit_commit_end(unsigned commit)
{
	if (!rw_audit_frame_active(commit))
		return;
	rw_print("audit-pass end: commit %u\n", commit);
	atomic_store_explicit(&rw_audit_active, false, memory_order_release);
}

/* Concurrency Worker for Thread Safety Test */
static _Atomic int g_stop_threads = 0;

static void *concurrency_commit_worker(void *arg) {
    unsigned thread_id = (unsigned)(uintptr_t)arg;
    unsigned commit = 1000 + thread_id * 100;

    MockPipeline *pipe = [[MockPipeline alloc] init];
    MockTexture *tex = [[MockTexture alloc] initWithWidth:1156 height:2510 format:80 samples:1 isSurface:YES hasMesa:YES];
    AnnibaleMetalWork *work = [[AnnibaleMetalWork alloc] init];
    work->render = pipe;
    work->colorCount = 1;
    work->color[0] = tex;
    NSArray *works = @[ work ];

    while (!g_stop_threads) {
        commit++;
        rw_audit_commit_begin(works, commit);
        rw_audit_render_work(work, commit, 0);
        rw_audit_commit_end(commit);
        usleep(100);
    }
    return NULL;
}

static void *concurrency_trigger_worker(void *arg) {
    (void)arg;
    while (!g_stop_threads) {
        atomic_store_explicit(&rw_audit_active, true, memory_order_release);
        usleep(250);
        atomic_store_explicit(&rw_audit_active, false, memory_order_release);
        usleep(250);
    }
    return NULL;
}

int main(int argc, const char *argv[]) {
    (void)argc; (void)argv;
    printf("[*] Running empirical verification on annibalemetal_diag.inc Render Pass audit logic...\n");

    /* =========================================================================
     * SECTION 1: Attachment Edge Cases
     * ========================================================================= */
    printf("\n--- Section 1: Attachment Edge Cases ---\n");
    atomic_store_explicit(&rw_audit_wanted_frame, 0, memory_order_release); /* Enable audit for all frames */

    MockPipeline *pipe = [[MockPipeline alloc] init];

    /* 1.1: Nil textures in color attachments */
    printf("Test 1.1: Multi-attachment pass with nil textures (sparse attachments)...\n");
    AnnibaleMetalWork *workSparse = [[AnnibaleMetalWork alloc] init];
    workSparse->render = pipe;
    workSparse->colorCount = 4;
    MockTexture *texValid1 = [[MockTexture alloc] initWithWidth:800 height:600 format:80 samples:1 isSurface:NO hasMesa:YES];
    MockTexture *texValid3 = [[MockTexture alloc] initWithWidth:400 height:300 format:80 samples:1 isSurface:YES hasMesa:NO];
    workSparse->color[0] = nil; /* nil at 0 */
    workSparse->color[1] = texValid1;
    workSparse->color[2] = nil; /* nil at 2 */
    workSparse->color[3] = texValid3;

    g_print_count = 0;
    rw_audit_commit_begin(@[ workSparse ], 1);
    rw_audit_render_work(workSparse, 1, 0);
    rw_audit_commit_end(1);
    printf("Sparse nil textures: handled without crash. Log statements: %d\n", g_print_count);
    assert(g_print_count > 0);

    /* 1.2: Depth-only attachment pass (colorCount == 0, depth != nil) */
    printf("Test 1.2: Depth-only pass (colorCount == 0, depth != nil)...\n");
    AnnibaleMetalWork *workDepthOnly = [[AnnibaleMetalWork alloc] init];
    workDepthOnly->render = pipe;
    workDepthOnly->colorCount = 0;
    MockTexture *dtex = [[MockTexture alloc] initWithWidth:1156 height:2510 format:252 samples:1 isSurface:NO hasMesa:NO];
    workDepthOnly->depth = dtex;
    workDepthOnly->clearsDepth = YES;
    workDepthOnly->clearsStencil = YES;

    g_print_count = 0;
    rw_audit_render_work(workDepthOnly, 2, 0);
    printf("Depth-only pass: handled without crash. Last log: %s\n", g_last_print);
    assert(strstr(g_last_print, "audit-pass depth") != NULL);
    assert(strstr(g_last_print, "stencil_clear") != NULL);

    /* 1.3: Multi-sampled pass (sampleCount == 4, resolve != nil) */
    printf("Test 1.3: Multi-sampled pass (samples=4, resolve target present)...\n");
    AnnibaleMetalWork *workMSAA = [[AnnibaleMetalWork alloc] init];
    workMSAA->render = pipe;
    workMSAA->colorCount = 1;
    MockTexture *texMSAA = [[MockTexture alloc] initWithWidth:1156 height:2510 format:80 samples:4 isSurface:NO hasMesa:YES];
    MockTexture *texResolve = [[MockTexture alloc] initWithWidth:1156 height:2510 format:80 samples:1 isSurface:YES hasMesa:YES];
    workMSAA->color[0] = texMSAA;
    workMSAA->resolve[0] = texResolve;

    /* When thumbnail returns -1 for MSAA as required by air_metal_copy.h */
    g_mock_thumb_ret = -1;
    g_warn_count = 0;
    rw_audit_render_work(workMSAA, 3, 0);
    printf("MSAA pass: handled without crash. Thumbnail returned -1, audit-warn count: %d\n", g_warn_count);
    assert(g_warn_count == 0);

    /* 1.4: Pure black detection accuracy */
    printf("Test 1.4: Pure black store action detection...\n");
    g_mock_thumb_ret = 0;
    /* Subtest 1.4A: Fill pure black (values <= 2) */
    memset(g_mock_thumb_rgba, 0, sizeof(g_mock_thumb_rgba));
    g_warn_count = 0;
    rw_audit_render_work(workSparse, 4, 0);
    printf("Pure black filled: audit-warn count = %d (expected > 0) -> %s\n",
        g_warn_count, g_warn_count > 0 ? "PASS" : "FAIL");
    assert(g_warn_count > 0);

    /* Subtest 1.4B: Fill non-black (value = 10) */
    memset(g_mock_thumb_rgba, 10, sizeof(g_mock_thumb_rgba));
    g_warn_count = 0;
    rw_audit_render_work(workSparse, 5, 0);
    printf("Non-black filled: audit-warn count = %d (expected 0) -> %s\n",
        g_warn_count, g_warn_count == 0 ? "PASS" : "FAIL");
    assert(g_warn_count == 0);

    /* =========================================================================
     * SECTION 2: Thread Safety & Concurrency Stress Test
     * ========================================================================= */
    printf("\n--- Section 2: Thread Safety & Concurrency Stress Test ---\n");
    atomic_store_explicit(&rw_audit_wanted_frame, -1, memory_order_release); /* Toggle via rw_audit_active from thread */

    pthread_t threads[4];
    pthread_t trigger_thread;

    printf("Starting 4 commit threads and 1 trigger thread for 50ms...\n");
    for (uintptr_t i = 0; i < 4; i++) {
        pthread_create(&threads[i], NULL, concurrency_commit_worker, (void *)i);
    }
    pthread_create(&trigger_thread, NULL, concurrency_trigger_worker, NULL);

    usleep(50000); /* 50ms */
    g_stop_threads = 1;

    for (int i = 0; i < 4; i++) {
        pthread_join(threads[i], NULL);
    }
    pthread_join(trigger_thread, NULL);

    printf("Thread concurrency test finished without crash/hang. Total prints: %d\n", g_print_count);

    printf("\n[*] All empirical tests in test_annibale_audit_stress complete.\n");
    return 0;
}
