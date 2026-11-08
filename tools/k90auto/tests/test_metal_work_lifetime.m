#import <Foundation/Foundation.h>
#include <assert.h>
#include "annibalemetal_work_private.h"
#include "annibalemetal_work.inc"

static unsigned destroyed;
@interface TrackedTexture : NSObject
@end
@implementation TrackedTexture
- (void)dealloc
{
    destroyed++;
    [super dealloc];
}
@end

int main(void)
{
    @autoreleasepool {
        TrackedTexture *texture = [[TrackedTexture alloc] init];
        AnnibaleMetalWork *work = [[AnnibaleMetalWork alloc] init];
        work->colorCount = 2;
        work->color[0] = texture;
        work->color[1] = texture;
        work->resolve[0] = texture;
        work->depth = texture;
        [work retainResources];
        [work retainResources];
        assert([texture retainCount] == 5);
        [texture release];
        assert(destroyed == 0);
        [work release];
        assert(destroyed == 1);

        work = [[AnnibaleMetalWork alloc] init];
        texture = [[TrackedTexture alloc] init];
        work->color[0] = texture;
        work->colorCount = 1;
        [work release];
        assert(destroyed == 1);
        [texture release];
        assert(destroyed == 2);
    }
    puts("Metal work lifetime tests passed");
    return 0;
}
