"""gen_prompts.py —— 组合式生成珠宝/钻石设计提示词清单。
10 品类 × 10 宝石 × 3 金属 = 300 条。复杂度 O(N)。
"""
import itertools, json, sys
from pathlib import Path

ITEMS = [
    "an engagement ring", "a pendant necklace", "an eternity band",
    "a cocktail ring", "a pair of drop earrings", "a tennis bracelet",
    "a brooch", "a delicate tiara", "a pair of cufflinks", "a bangle",
]
GEMS = [
    "a round brilliant-cut diamond", "an emerald-cut sapphire",
    "an oval ruby", "a pear-shaped emerald", "a cushion-cut morganite",
    "a marquise-cut diamond", "a princess-cut amethyst",
    "a radiant-cut citrine", "a heart-shaped pink diamond",
    "a trillion-cut tanzanite",
]
METALS = [
    "a platinum", "an 18k yellow gold", "an 18k rose gold",
]
DETAILS = [
    "pave diamond accents", "milgrain edge detailing",
    "delicate filigree scrollwork", "channel-set side stones",
    "a twisted rope texture", "a sleek bezel setting",
    "vintage engraving",
]


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("design_prompts.json")
    items = []
    combo = itertools.product(ITEMS, GEMS, METALS)
    for i, (item, gem, metal) in enumerate(combo, 1):
        if i > n:
            break
        detail = DETAILS[(i - 1) % len(DETAILS)]
        prompt = (f"{item} featuring {gem} center stone, set in {metal} band "
                  f"with {detail}, luxury jewelry design, studio product "
                  f"photography, clean white background, high detail macro")
        items.append({"name": f"design_{i:03d}", "prompt": prompt})
    out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"生成 {len(items)} 条 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
