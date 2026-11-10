"""exit 0 if IMAGE looks like the stuck loading screen (harness/ref_loading.jpg), else 1"""
import sys
from PIL import Image, ImageChops
a = Image.open(sys.argv[1]).convert("L").resize((240, 135))
b = Image.open(sys.argv[2] if len(sys.argv) > 2 else "harness/ref_loading.jpg").convert("L").resize((240, 135))
d = sum(ImageChops.difference(a, b).histogram()[40:])
print("loading" if d < 2000 else "in level", d)
sys.exit(0 if d < 2000 else 1)
