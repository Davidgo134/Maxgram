#!/usr/bin/env python3
"""
Maxgram iOS26 patch tool v2 — UI-мод для apktool-дампа MAX.

Запуск из КОРНЯ репозитория (рядом с папкой 26.25.0-1.5.2):

  # НОВОЕ: floating glass таб-бар как в Telegram iOS 26 (dry-run):
  python3 maxgram_ios26_patch.py --tabbar

  # Применить:
  python3 maxgram_ios26_patch.py --tabbar --apply

  # Ребрендинг + перекраска (как в v1):
  python3 maxgram_ios26_patch.py --scan-colors
  python3 maxgram_ios26_patch.py --rebrand Maxgram --recolor 0xFF7B61FF=0xFF007AFF --apply

  # Сборка:
  python3 maxgram_ios26_patch.py --build --keystore my.jks --ks-pass PASS

Что делает стадия --tabbar (smali/one/me/main/MainScreen.smali):
  1) setBlurEnabled(FALSE) -> setBlurEnabled(TRUE) — у OneMeBottomBarView (Llqb;)
     есть встроенный realtime-blur фона, в стоке он выключен. Это и есть «стекло».
  2) FrameLayout.LayoutParams таб-бара: margins 12dp со всех сторон — бар
     становится «плавающим», а не на всю ширину.
  3) Закруглённый клип 28dp через новый хелпер smali/maxgram/GlassOutline
     (2 новых smali-файла, ресурсы/public.xml не трогаем — сборка безопасна).
"""
import argparse
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------- constants

CONST_RE = re.compile(r'(const(?:/high16)?)\s+((?:v|p)\d+),\s*(-?0x[0-9a-fA-F]+|-?\d+)')
REBRAND_RE = re.compile(r'(<string\s+name="oneme_app_name">)[^<]*(</string>)')

MAIN_SCREEN = 'smali/one/me/main/MainScreen.smali'

# Якорь 1: blur. FALSE стоит ровно перед setBlurEnabled основного таб-бара (p2).
BLUR_ANCHOR = re.compile(
    r'sget-object v1, Ljava/lang/Boolean;->FALSE:Ljava/lang/Boolean;'
    r'(\s*invoke-virtual \{p2, v1\}, Llqb;->setBlurEnabled\(Ljava/lang/Boolean;\)V)'
)
BLUR_REPL = r'sget-object v1, Ljava/lang/Boolean;->TRUE:Ljava/lang/Boolean;\1'

# Якорь 2: первый addView (таб-бар p2). Вставляем margins + rounded clip перед ним.
ADDVIEW_ANCHOR = (
    '    invoke-virtual {p1, p2, p0}, '
    'Landroid/view/ViewGroup;->addView(Landroid/view/View;Landroid/view/ViewGroup$LayoutParams;)V'
)
# На этом месте живы: p0=LayoutParams, p1=root, p2=бар, p3=-1, v0=-2, v1=0x50.
# v2 и v4 мертвы — используем их. .locals 5 (v0..v4) не превышаем.
TABBAR_INSERT = """    # --- maxgram: floating glass tab bar ---
    invoke-static {}, Lgi5;->d()Landroid/content/res/Resources;

    move-result-object v2

    invoke-virtual {v2}, Landroid/content/res/Resources;->getDisplayMetrics()Landroid/util/DisplayMetrics;

    move-result-object v2

    iget v2, v2, Landroid/util/DisplayMetrics;->density:F

    const/high16 v4, 0x41400000    # 12.0f

    mul-float v4, v2, v4

    float-to-int v4, v4

    iput v4, p0, Landroid/widget/FrameLayout$LayoutParams;->leftMargin:I

    iput v4, p0, Landroid/widget/FrameLayout$LayoutParams;->rightMargin:I

    iput v4, p0, Landroid/widget/FrameLayout$LayoutParams;->bottomMargin:I

    const/high16 v4, 0x41e00000    # 28.0f

    mul-float/2addr v2, v4

    invoke-static {p2, v2}, Lmaxgram/GlassOutline;->apply(Landroid/view/View;F)V
    # --- /maxgram ---

"""

GLASS_OUTLINE = '''.class public final Lmaxgram/GlassOutline;
.super Ljava/lang/Object;
.source "GlassOutline.java"


# direct methods
.method private constructor <init>()V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method

.method public static apply(Landroid/view/View;F)V
    .locals 1

    new-instance v0, Lmaxgram/GlassOutline$1;

    invoke-direct {v0, p1}, Lmaxgram/GlassOutline$1;-><init>(F)V

    invoke-virtual {p0, v0}, Landroid/view/View;->setOutlineProvider(Landroid/view/ViewOutlineProvider;)V

    const/4 v0, 0x1

    invoke-virtual {p0, v0}, Landroid/view/View;->setClipToOutline(Z)V

    return-void
.end method
'''

GLASS_OUTLINE_1 = '''.class final Lmaxgram/GlassOutline$1;
.super Landroid/view/ViewOutlineProvider;
.source "GlassOutline.java"


# instance fields
.field final val$radius:F


# direct methods
.method constructor <init>(F)V
    .locals 0

    invoke-direct {p0}, Landroid/view/ViewOutlineProvider;-><init>()V

    iput p1, p0, Lmaxgram/GlassOutline$1;->val$radius:F

    return-void
.end method


# virtual methods
.method public getOutline(Landroid/view/View;Landroid/graphics/Outline;)V
    .locals 6

    invoke-virtual {p1}, Landroid/view/View;->getWidth()I

    move-result v3

    invoke-virtual {p1}, Landroid/view/View;->getHeight()I

    move-result v4

    iget v5, p0, Lmaxgram/GlassOutline$1;->val$radius:F

    const/4 v1, 0x0

    const/4 v2, 0x0

    move-object v0, p2

    invoke-virtual/range {v0 .. v5}, Landroid/graphics/Outline;->setRoundRect(IIIIF)V

    return-void
.end method
'''

# ---------------------------------------------------------------- helpers

def parse_int(tok: str) -> int:
    return int(tok, 0)


def to_signed32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


def reg_value(instr: str, v: int) -> int:
    if instr == 'const/high16':
        return (v & 0xFFFF) << 16
    return v & 0xFFFFFFFF


def smali_files(root: Path):
    yield from root.glob('smali*/**/*.smali')


# ---------------------------------------------------------------- tabbar stage

def stage_tabbar(root: Path, apply: bool):
    ms = root / MAIN_SCREEN
    if not ms.is_file():
        sys.exit(f'не найден {ms}')
    text = ms.read_text(encoding='utf-8')

    new_text, n_blur = BLUR_ANCHOR.subn(BLUR_REPL, text, count=1)
    if n_blur != 1:
        print(f'!! якорь blur не найден (совпадений: {n_blur}) — проверь MainScreen.smali')
    else:
        print(f'{"PATCH" if apply else "WOULD"} blur: setBlurEnabled FALSE->TRUE')

    n_add = new_text.count(ADDVIEW_ANCHOR)
    if n_add != 1:
        print(f'!! якорь addView: совпадений {n_add} (ожидался 1) — пропускаю margins/clip')
    else:
        new_text = new_text.replace(ADDVIEW_ANCHOR, TABBAR_INSERT + ADDVIEW_ANCHOR, 1)
        print(f'{"PATCH" if apply else "WOULD"} margins 12dp + rounded clip 28dp перед addView таб-бара')

    if apply and new_text != text:
        ms.write_text(new_text, encoding='utf-8')

    for rel, content in (('smali/maxgram/GlassOutline.smali', GLASS_OUTLINE),
                         ('smali/maxgram/GlassOutline$1.smali', GLASS_OUTLINE_1)):
        f = root / rel
        print(f'{"WRITE" if apply else "WOULD"} новый файл {f}')
        if apply:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content, encoding='utf-8')


# ---------------------------------------------------------------- v1 stages

def scan_colors(root: Path, top: int = 40):
    cnt, example = Counter(), {}
    for f in smali_files(root):
        text = f.read_text(encoding='utf-8', errors='ignore')
        for m in CONST_RE.finditer(text):
            instr, _, tok = m.groups()
            try:
                c = reg_value(instr, parse_int(tok))
            except ValueError:
                continue
            if (c >> 24) & 0xFF != 0xFF:
                continue
            cnt[c] += 1
            example.setdefault(c, str(f))
    print(f'{"Цвет":<12} {"Частота":>8}  Пример файла')
    print('-' * 80)
    for c, n in cnt.most_common(top):
        print(f'#{c:08X}   {n:>8}  {example[c]}')


def recolor_smali(root: Path, mapping: dict, apply: bool):
    for f in smali_files(root):
        text = f.read_text(encoding='utf-8', errors='ignore')
        hits = 0

        def repl(m):
            nonlocal hits
            instr, reg, tok = m.groups()
            try:
                c = reg_value(instr, parse_int(tok))
            except ValueError:
                return m.group(0)
            if c not in mapping:
                return m.group(0)
            hits += 1
            new = mapping[c]
            if instr == 'const/high16':
                return f'{instr} {reg}, {to_signed32(new >> 16):#x}'
            return f'{instr} {reg}, {to_signed32(new)}'

        new_text = CONST_RE.sub(repl, text)
        if hits:
            print(f'{"PATCH" if apply else "WOULD"} smali  {f}  ({hits} замен)')
            if apply:
                f.write_text(new_text, encoding='utf-8')


def recolor_xml(root: Path, mapping: dict, apply: bool):
    res = root / 'res'
    if not res.is_dir():
        return
    for f in res.rglob('*.xml'):
        text = f.read_text(encoding='utf-8', errors='ignore')
        new_text = text
        for old, new in mapping.items():
            for o, n in ((f'#{old:08X}', f'#{new:08X}'),
                         (f'#{old & 0xFFFFFF:06X}', f'#{new & 0xFFFFFF:06X}')):
                new_text = re.sub(re.escape(o), n, new_text, flags=re.I)
        if new_text != text:
            print(f'{"PATCH" if apply else "WOULD"} xml    {f}')
            if apply:
                f.write_text(new_text, encoding='utf-8')


def rebrand(root: Path, name: str, apply: bool):
    for strings in (root / 'res').glob('values*/strings.xml'):
        text = strings.read_text(encoding='utf-8', errors='ignore')
        new_text, n = REBRAND_RE.subn(rf'\g<1>{name}\g<2>', text)
        if n:
            print(f'{"PATCH" if apply else "WOULD"} string {strings}  (oneme_app_name -> {name})')
            if apply:
                strings.write_text(new_text, encoding='utf-8')


def build(root: Path, out: Path, keystore: str, ks_pass: str):
    apktool = shutil.which('apktool')
    cmd = ([apktool] if apktool else ['java', '-jar', 'apktool.jar'])
    unsigned = out.with_suffix('.unsigned.apk')
    aligned = out.with_suffix('.aligned.apk')
    steps = [
        cmd + ['b', str(root), '-o', str(unsigned), '--use-aapt2'],
        ['zipalign', '-p', '4', str(unsigned), str(aligned)],
        ['apksigner', 'sign', '--ks', keystore, '--ks-pass', f'pass:{ks_pass}',
         '--out', str(out), str(aligned)],
    ]
    for s in steps:
        print('$', ' '.join(s))
        r = subprocess.run(s)
        if r.returncode != 0:
            sys.exit(f'шаг завершился с кодом {r.returncode}')
    print(f'\nOK: {out}')


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description='Maxgram iOS26 patch tool v2')
    ap.add_argument('--root', default='26.25.0-1.5.2')
    ap.add_argument('--tabbar', action='store_true', help='floating glass таб-бар (MainScreen)')
    ap.add_argument('--rebrand', metavar='NAME')
    ap.add_argument('--scan-colors', action='store_true')
    ap.add_argument('--recolor', nargs='*', metavar='OLD=NEW')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--build', action='store_true')
    ap.add_argument('--apk-out', default='dist/maxgram.apk')
    ap.add_argument('--keystore', default='maxgram.jks')
    ap.add_argument('--ks-pass', default='')
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.exit(f'не найдена папка {root} — запускай из корня репозитория')

    if args.tabbar:
        stage_tabbar(root, args.apply)

    if args.scan_colors:
        scan_colors(root)

    mapping = {}
    for pair in args.recolor or []:
        old, new = pair.split('=')
        mapping[parse_int(old) & 0xFFFFFFFF] = parse_int(new) & 0xFFFFFFFF
    if mapping:
        recolor_smali(root, mapping, args.apply)
        recolor_xml(root, mapping, args.apply)

    if args.rebrand:
        rebrand(root, args.rebrand, args.apply)

    if not args.apply and (args.tabbar or mapping or args.rebrand):
        print('\nЭто dry-run. Добавь --apply, чтобы записать изменения.')

    if args.build:
        Path(args.apk_out).parent.mkdir(parents=True, exist_ok=True)
        build(root, Path(args.apk_out), args.keystore, args.ks_pass)


if __name__ == '__main__':
    main()
