#include <stdio.h>

#include "air_clear_plan.h"

/* A recording pipe checks the production clear entry point without a GPU or shaders. */
#include <assert.h>
#include <stdbool.h>
#include <stdarg.h>
#include <string.h>
#include "air_metal.h"
#define RWA_LOCKED
#define PIPE_MAX_COLOR_BUFS 8
#define PIPE_CLEAR_COLOR0 4u
#define PIPE_CLEAR_DEPTH 1u
#define PIPE_CLEAR_STENCIL 2u
#define PIPE_BIND_RENDER_TARGET 1u
#define PIPE_BIND_DEPTH_STENCIL 2u
#define MIN2(a,b) ((a) < (b) ? (a) : (b))
union pipe_color_union { float f[4]; };
struct pipe_resource { unsigned nr_samples, bind, format, refs; float pixel[4]; double depth; unsigned stencil; };
struct pipe_surface { struct pipe_resource *texture; unsigned format, level, layer; };
struct pipe_framebuffer_state {
 unsigned nr_cbufs, width, height, samples;
 struct pipe_surface cbufs[8], zsbuf;
};
struct pipe_context {
 void (*clear)(struct pipe_context *, unsigned, unsigned, unsigned, const void *,
               const union pipe_color_union *, double, unsigned);
 struct pipe_framebuffer_state fb;
 unsigned calls;
};
struct rwa_device { struct pipe_context *pipe; };
struct rwa_texture {
 struct rwa_device *device;
 struct pipe_resource *res;
 struct rwa_texture_shape shape;
 unsigned first_level, written;
};
static void say(char *why, size_t n, const char *fmt, ...) {
 va_list ap; va_start(ap, fmt); vsnprintf(why, n, fmt, ap); va_end(ap);
}
static bool format_has_depth(unsigned f) { return f == 260; }
static bool format_has_stencil(unsigned f) { return f == 260; }
static bool attachment_shape_fits(const struct rwa_texture *t, unsigned samples,
 const char *name, char *why, size_t size) {
 (void)name; (void)why; (void)size; return t->shape.type == (samples > 1 ? 4 : 2);
}
static void pipe_surface_init(struct pipe_context *p, struct pipe_surface *s,
 struct pipe_resource *r, unsigned level, unsigned layer) {
 (void)p; s->level = level; s->layer = layer; s->texture = r; r->refs++;
}
static unsigned texture_format(struct rwa_texture *t) { return t->res->format; }
static void texture_written(struct rwa_texture *t) { t->written++; }
static void pipe_resource_reference(struct pipe_resource **p, struct pipe_resource *r) {
 if (r) r->refs++;
 if (*p) { assert((*p)->refs); (*p)->refs--; }
 *p = r;
}
static void state_framebuffer(struct rwa_device *d, struct pipe_framebuffer_state *fb) {
 for (unsigned i = 0; i < 8; i++) {
  pipe_resource_reference(&d->pipe->fb.cbufs[i].texture, fb->cbufs[i].texture);
 }
 pipe_resource_reference(&d->pipe->fb.zsbuf.texture, fb->zsbuf.texture);
 d->pipe->fb = *fb;
}
static void record_clear(struct pipe_context *p, unsigned mask, unsigned channels,
 unsigned stencil_mask, const void *scissor, const union pipe_color_union *c,
 double depth, unsigned stencil) {
 assert(scissor == NULL);
 if (mask & PIPE_CLEAR_DEPTH) p->fb.zsbuf.texture->depth = depth;
 if (mask & PIPE_CLEAR_STENCIL) {
  unsigned *old = &p->fb.zsbuf.texture->stencil;
  *old = (*old & ~stencil_mask) | (stencil & stencil_mask);
 }
 p->calls++;
 for (unsigned i = 0; i < 8; i++) if (mask & (PIPE_CLEAR_COLOR0 << i)) {
  assert(p->fb.cbufs[i].texture);
  for (unsigned k = 0; k < 4; k++) if (channels & (1u << (i * 4 + k)))
   p->fb.cbufs[i].texture->pixel[k] = c->f[k];
 }
}
#include "air_metal_clear.inc"

static void test_pass_without_draw(void) {
 struct pipe_context pipe = { .clear = record_clear };
 struct rwa_device device = { .pipe = &pipe };
 struct pipe_resource resources[2] = {
  { .nr_samples = 1, .refs = 1, .bind = PIPE_BIND_RENDER_TARGET, .pixel = {9,9,9,9} },
  { .nr_samples = 1, .refs = 1, .bind = PIPE_BIND_RENDER_TARGET, .pixel = {9,9,9,9} }
 };
 struct rwa_texture textures[2]; struct rwa_texture *colors[2];
 for (unsigned i = 0; i < 2; i++) {
  textures[i] = (struct rwa_texture){ .device = &device, .res = &resources[i],
   .shape = { .type = 2, .width = 4, .height = 4 } }; colors[i] = &textures[i];
 }
 float rgba[8] = {0,0,0,1, 1,0.5f,0.25f,0.75f};
 struct rwa_draw pass = {.color=colors, .color_count=2, .clear_color=rgba, .discard=3u<<8};
 char why[128];
 assert(rwa_render_clear(&device, &pass, why, sizeof(why)) == 0);
 assert(pipe.calls == 2 && !memcmp(resources[0].pixel, rgba, 4*sizeof(float)));
 assert(!memcmp(resources[1].pixel, rgba+4, 4*sizeof(float)));
 rgba[0] = 0.75f; pass.discard = 1u << 8;
 assert(rwa_render_clear(&device, &pass, why, sizeof(why)) == 0);
 assert(resources[0].pixel[0] == 0.75f && resources[1].pixel[0] == 1);
 unsigned calls = pipe.calls, written = textures[0].written; pass.clear_color = NULL;
 assert(rwa_render_clear(&device, &pass, why, sizeof(why)) == 0 && pipe.calls == calls);
 assert(textures[0].written == written);
 resources[1].nr_samples = 4; textures[1].shape.type = 4;
 pass.clear_color = rgba;
 assert(rwa_render_clear(&device, &pass, why, sizeof(why)) == -1 && pipe.calls == calls);
 resources[1].nr_samples = 1; textures[1].shape.type = 2;
 struct rwa_device foreign = { .pipe = &pipe };
 textures[1].device = &foreign;
 assert(rwa_render_clear(&device, &pass, why, sizeof(why)) == -1 && pipe.calls == calls);
 textures[1].device = &device;
 pass.color_count = 9;
 assert(rwa_render_clear(&device, &pass, why, sizeof(why)) == -1 && pipe.calls == calls);
}

static void test_depth_view_and_references(void) {
 struct pipe_context pipe = { .clear = record_clear };
 struct rwa_device device = { .pipe = &pipe };
 struct pipe_resource resource = { .nr_samples = 1, .refs = 1,
  .bind = PIPE_BIND_DEPTH_STENCIL, .format = 260, .depth = 0.75, .stencil = 42 };
 struct rwa_texture tex = { .device = &device, .res = &resource,
  .shape = { .type = 2, .width = 2, .height = 2 }, .first_level = 3 };
 float depth = 0.25f; unsigned stencil = 17;
 const unsigned scissor[4] = { 1, 1, 1, 1 };
 struct rwa_draw pass = { .depth = &tex, .clear_depth = &depth, .scissor = scissor };
 char why[128];
 assert(rwa_render_clear(&device, &pass, why, sizeof(why)) == 0);
 assert(resource.depth == 0.25 && resource.stencil == 42);
 assert(pipe.fb.zsbuf.level == 3 && pipe.fb.zsbuf.layer == 0);
 assert(pipe.fb.width == 2 && pipe.fb.height == 2 && resource.refs == 2);
 pass.clear_depth = NULL; pass.clear_stencil = &stencil;
 assert(rwa_render_clear(&device, &pass, why, sizeof(why)) == 0);
 assert(resource.depth == 0.25 && resource.stencil == 17 && resource.refs == 2);
 state_framebuffer(&device, &(struct pipe_framebuffer_state){0});
 assert(resource.refs == 1);
}

static int
check(int condition, const char *name)
{
	if (!condition) {
		fprintf(stderr, "FAIL: %s\n", name);
		return 1;
	}
	return 0;
}

int
main(void)
{
	test_pass_without_draw();
	test_depth_view_and_references();
	const float colors[8][4] = {
		{ 0.1f, 0.2f, 0.3f, 0.4f },
		{ 0.8f, 0.7f, 0.6f, 0.5f },
	};
	struct rwa_color_clear calls[RWA_MAX_COLOR_ATTACHMENTS];
	int failed = 0;
	unsigned count = rwa_color_clear_plan(2, 3u << 8, &colors[0][0], calls);
	failed |= check(count == 2, "two clear attachments produce two calls");
	failed |= check(calls[0].attachment == 0 && calls[0].write_mask == 0xfu,
			"first attachment mask");
	failed |= check(calls[1].attachment == 1 && calls[1].write_mask == 0xf0u,
			"second attachment mask");
	failed |= check(calls[0].rgba[0] == 0.1f && calls[0].rgba[3] == 0.4f,
			"first attachment color");
	failed |= check(calls[1].rgba[0] == 0.8f && calls[1].rgba[3] == 0.5f,
			"second attachment color");

	count = rwa_color_clear_plan(2, 2u << 8, &colors[0][0], calls);
	failed |= check(count == 1 && calls[0].attachment == 1 && calls[0].rgba[0] == 0.8f,
			"partial clear preserves attachment index and color");

	count = rwa_color_clear_plan(2, 0, &colors[0][0], calls);
	failed |= check(count == 1 && calls[0].attachment == 0 && calls[0].rgba[0] == 0.1f,
			"legacy single-color clear targets attachment zero");

	count = rwa_color_clear_plan(2, 3u << 8, NULL, calls);
	failed |= check(count == 0, "load pass creates no color clear calls");
	const float opaque_black[8][4] = {
		{ 0, 0, 0, 1 }, { 0, 0, 0, 1 }, { 0, 0, 0, 1 }, { 0, 0, 0, 1 },
		{ 0, 0, 0, 1 }, { 0, 0, 0, 1 }, { 0, 0, 0, 1 }, { 0, 0, 0, 1 },
	};
	count = rwa_color_clear_plan(8, 0xff00u, &opaque_black[0][0], calls);
	failed |= check(count == 8, "all eight clear attachments are retained");
	for (unsigned i = 0; i < count; i++) {
		failed |= check(calls[i].attachment == i && calls[i].write_mask == (0xfu << (4 * i)),
				"each attachment has its own write mask");
		failed |= check(calls[i].rgba[3] == 1.0f, "opaque black alpha remains opaque");
	}
	count = rwa_color_clear_plan(8, 0x8000u, &opaque_black[0][0], calls);
	failed |= check(count == 1 && calls[0].attachment == 7 && calls[0].write_mask == 0xf0000000u,
			"sparse last attachment clear");
	count = rwa_color_clear_plan(2, 0x8000u, &colors[0][0], calls);
	failed |= check(count == 0, "clear mask outside the active attachments is ignored");
	count = rwa_color_clear_plan(0, 0xff00u, &colors[0][0], calls);
	failed |= check(count == 0, "no color attachments produce no clears");
	count = rwa_color_clear_plan(1, 1u, NULL, calls);
	failed |= check(count == 0, "DontCare without Clear produces no clear operation");
	if (!failed) {
		puts("air clear plan tests passed");
	}
	return failed ? 1 : 0;
}
