#!/usr/bin/env python3
"""Run the production texture initialization/destruction methods with tracked owners."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
DRIVER = ROOT / "hackios-xnu-kernel/tools/userland-driver"
texture = (DRIVER / "redwoodmetal_texture.inc").read_text()
methods = texture[texture.index("- (instancetype)initWithRedwoodDevice:"):
                  texture.index("- (void)redwoodSetBuffer:")]
yuv = (DRIVER / "redwoodmetal_yuv.inc").read_text().split("static id\n", 1)[0]
source = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
static unsigned device_dead, resources_dead;
struct rwa_texture { unsigned unused; };
struct rwa_texture_shape { unsigned unused; };
static void destroy_texture(struct rwa_texture *texture) {
    assert(!device_dead);
    resources_dead++;
    free(texture);
}
static struct { void (*texture_destroy)(struct rwa_texture *); } mesa = {destroy_texture};
@interface RedwoodMetalDevice : NSObject
@end
@implementation RedwoodMetalDevice
- (void)dealloc { device_dead++; [super dealloc]; }
@end
@interface RedwoodMetalTexture : NSObject {
    RedwoodMetalDevice *_owner;
    struct rwa_texture *_texture;
    struct rwa_texture_shape _shape;
    CFTypeRef _iosurface;
    NSUInteger _iosurfacePlane;
    id _parentTexture, _buffer;
}
@end
@implementation RedwoodMetalTexture
''' + methods + '\n@end\n' + yuv + r'''
static id make(Class cls, RedwoodMetalDevice *device) {
    struct rwa_texture_shape shape = {0};
    return [[cls alloc] initWithRedwoodDevice:device texture:calloc(1, sizeof(struct rwa_texture))
        shape:&shape iosurface:NULL plane:0];
}
int main(void) {
    @autoreleasepool {
        RedwoodMetalDevice *device = [RedwoodMetalDevice new];
        id y = make([RedwoodMetalTexture class], device);
        id uv = make([RedwoodMetalTexture class], device);
        id combined = make([RedwoodMetalYUVTexture class], device);
        NSArray *planes = [[NSArray alloc] initWithObjects:y, uv, nil];
        [combined redwoodSetPlanes:planes];
        [planes release]; [y release]; [uv release];
        [device release];
        assert(!device_dead && !resources_dead);
        [combined release];
        assert(device_dead == 1 && resources_dead == 3);
    }
    puts("Metal textures retained the device through all three AIR destructions");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="metal-texture-lifetime-") as directory:
    work = Path(directory)
    (work / "test.m").write_text(source)
    subprocess.run(["xcrun", "clang", "-fno-objc-arc", "-fsanitize=address,undefined",
                    "-framework", "Foundation", str(work / "test.m"), "-o", str(work / "test")],
                   check=True)
    subprocess.run([str(work / "test")], check=True)
