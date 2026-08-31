"""Matter Saver brand icon: a Thread mesh with one node off the net.

Same visual language as the Device Saver icon (squircle, vertical gradient,
node-link graph) so the two read as a family, but blue and built around a
hub-and-spoke mesh instead of a question mark.
"""
import math
from PIL import Image, ImageDraw

SS = 8
OUT = 256
S = OUT * SS

BLUE_TOP = (68, 176, 245)
BLUE_BOT = (18, 96, 190)
WHITE = (255, 255, 255, 255)
AMBER = (255, 193, 74, 255)

CX, CY = 0.500, 0.492
HUB_R = 0.088
RING_R = 0.272           # distance of the outer nodes from the hub
NODE_R = 0.052
EDGE_W = 0.030

# Outer nodes, clockwise from the top. The last one is the dropped device:
# it keeps its place in the ring but loses its spoke.
ANGLES = [90, 30, -30, -90, -150, 150]
DROPPED = -30


def vertical_gradient(size, top, bottom):
    g = Image.new("RGB", (1, size))
    px = g.load()
    for y in range(size):
        t = y / (size - 1)
        px[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return g.resize((size, size), Image.NEAREST)


def squircle_mask(size, radius_frac=0.235):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size, size],
                                        radius=radius_frac * size, fill=255)
    return m


def polar(a):
    return (CX + RING_R * math.cos(math.radians(a)),
            CY - RING_R * math.sin(math.radians(a)))


def disc(d, cx, cy, r, fill):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def main():
    mask = squircle_mask(S)
    body = vertical_gradient(S, BLUE_TOP, BLUE_BOT).convert("RGBA")
    body.putalpha(mask)

    hi = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(hi).ellipse([-0.15 * S, -0.55 * S, 1.15 * S, 0.40 * S],
                               fill=(255, 255, 255, 30))
    hi.putalpha(Image.composite(hi.getchannel("A"), Image.new("L", (S, S), 0), mask))
    body = Image.alpha_composite(body, hi)

    d = ImageDraw.Draw(body)
    hub = (CX * S, CY * S)

    # spokes, skipping the dropped node
    for a in ANGLES:
        if a == DROPPED:
            continue
        x, y = polar(a)
        d.line([hub, (x * S, y * S)], fill=WHITE, width=int(EDGE_W * S))

    # one chord, so it reads as a mesh rather than a plain star
    x1, y1 = polar(ANGLES[0])
    x2, y2 = polar(ANGLES[1])
    d.line([(x1 * S, y1 * S), (x2 * S, y2 * S)], fill=WHITE, width=int(EDGE_W * S))

    for a in ANGLES:
        x, y = polar(a)
        disc(d, x * S, y * S, NODE_R * S, AMBER if a == DROPPED else WHITE)

    disc(d, hub[0], hub[1], HUB_R * S, WHITE)

    icon = body.resize((OUT, OUT), Image.LANCZOS)
    icon.save("matter_icon.png", optimize=True)
    body.resize((OUT * 2, OUT * 2), Image.LANCZOS).save("matter_icon@2x.png", optimize=True)
    icon.resize((24, 24), Image.LANCZOS).resize((192, 192), Image.NEAREST).save("matter_preview_24.png")
    print("wrote matter_icon.png, matter_icon@2x.png, matter_preview_24.png")


main()
