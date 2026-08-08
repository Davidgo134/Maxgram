#!/usr/bin/env python3
"""
Maxgram iOS26 patch tool v5 — UI-мод для apktool-дампа MAX.

Запуск из КОРНЯ репозитория (рядом с папкой 26.25.0-1.5.2):

  python3 maxgram_ios26_patch.py --fix-public --fix-styles --apply
  python3 maxgram_ios26_patch.py --tabbar --apply
  python3 maxgram_ios26_patch.py --scan-colors
  python3 maxgram_ios26_patch.py --rebrand Maxgram --recolor 0xFF7B61FF=0xFF007AFF --apply
  python3 maxgram_ios26_patch.py --build --keystore my.jks --ks-pass PASS

Стадии:
  --fix-public  достраивает определения для символов public.xml, потерянных в res/**
                (res/values/maxgram_stubs.xml + файловые стабы).
  --fix-styles  удаляет из res/values*/styles.xml <item> ссылки на android:attr,
                которых нет в framework.apk, вшитом в apktool (новые атрибуты
                API 34/35, например windowOptOutEdgeToEdgeEnforcement). Атрибуты не
                используются OneMe-рендером, удаление безопасно.
  --tabbar      MainScreen.smali: blur TRUE + margins 12dp + rounded clip 28dp.
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

BLUR_ANCHOR = re.compile(
    r'sget-object v1, Ljava/lang/Boolean;->FALSE:Ljava/lang/Boolean;'
    r'(\s*invoke-virtual \{p2, v1\}, Llqb;->setBlurEnabled\(Ljava/lang/Boolean;\)V)'
)
BLUR_REPL = r'sget-object v1, Ljava/lang/Boolean;->TRUE:Ljava/lang/Boolean;\1'

ADDVIEW_ANCHOR = (
    '    invoke-virtual {p1, p2, p0}, '
    'Landroid/view/ViewGroup;->addView(Landroid/view/View;Landroid/view/ViewGroup$LayoutParams;)V'
)
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


# ---------------------------------------------------------------- fix-styles stage

# Атрибуты/стили, которых нет в встроенном framework.apk apktool ≤ 2.10 (API 34/35+).
UNKNOWN_ATTRS = [
    'android:windowOptOutEdgeToEdgeEnforcement',
    'android:enableOnBackInvokedCallback',
    'android:supportsMultipleDisplays',
]


def stage_fix_styles(root: Path, apply: bool):
    res = root / 'res'
    total = 0
    patterns = [re.compile(
        r'[ \t]*<item[^>]*\bname="' + re.escape(attr) + r'"[^>]*>.*?</item>\s*\n?',
        re.DOTALL) for attr in UNKNOWN_ATTRS]
    for f in res.glob('values*/styles.xml'):
        text = f.read_text(encoding='utf-8', errors='ignore')
        new_text = text
        hits = 0
        for pat in patterns:
            new_text, n = pat.subn('', new_text)
            hits += n
        if hits:
            total += hits
            print(f'{"PATCH" if apply else "WOULD"} styles {f}  ({hits} атрибутов удалено)')
            if apply:
                f.write_text(new_text, encoding='utf-8')
    if not total:
        print('fix-styles: ничего удалять не пришлось')


# ---------------------------------------------------------------- fix-public stage

PUBLIC_RE = re.compile(r'<public\s+type="([^"]+)"\s+name="([^"]+)"[^>]*>')
VALUE_DEF_RE = re.compile(r'<(\w[\w-]*)\s+[^>]*\bname="([^"]+)"')
ITEM_DEF_RE = re.compile(r'<item\s+[^>]*type="([^"]+)"[^>]*name="([^"]+)"')
VALUE_TAGS = {
    'string', 'color', 'dimen', 'bool', 'boolean', 'integer', 'fraction',
    'drawable', 'style', 'array', 'plurals', 'id', 'attr', 'item',
    'string-array', 'integer-array', 'declare-styleable', 'styleable',
}
TAG_ALIAS = {
    'string-array': 'array',
    'integer-array': 'array',
    'declare-styleable': 'styleable',
    'boolean': 'bool',
}

CANON_COLORS = {
    'foreground_material_dark': '#FFFFFFFF',
    'foreground_material_light': '#FF000000',
    'background_material_dark': '#FF303030',
    'background_material_light': '#FFFFFFFF',
    'background_floating_material_dark': '#FF424242',
    'background_floating_material_light': '#FFFFFFFF',
    'bright_foreground_material_dark': '#FFFFFFFF',
    'bright_foreground_material_light': '#FF000000',
    'bright_foreground_disabled_material_dark': '#80FFFFFF',
    'bright_foreground_disabled_material_light': '#80000000',
    'bright_foreground_inverse_material_dark': '#FF000000',
    'bright_foreground_inverse_material_light': '#FFFFFFFF',
    'button_material_dark': '#FF5A595B',
    'button_material_light': '#FFD6D7D7',
    'ripple_material_dark': '#33FFFFFF',
    'ripple_material_light': '#1F000000',
    'highlighted_text_material_dark': '#66444444',
    'highlighted_text_material_light': '#66444444',
    'accent_material_dark': '#FF80CBC4',
    'accent_material_light': '#FF009688',
    'material_grey_50': '#FFFAFAFA',
    'material_grey_600': '#FF757575',
    'material_grey_800': '#FF424242',
    'material_grey_850': '#FF303030',
    'material_grey_900': '#FF212121',
    'material_deep_teal_200': '#FF80CBC4',
    'material_deep_teal_500': '#FF009688',
    'abc_search_url_text_normal': '#FF9E9E9E',
    'abc_search_url_text_pressed': '#FF000000',
    'abc_search_url_text_selected': '#FF000000',
    'call_notification_answer_color': '#FF4CAF50',
    'call_notification_decline_color': '#FFF44336',
    'design_dark_default_color_background': '#FF121212',
    'androidx_core_ripple_material_light': '#1F000000',
    'androidx_core_secondary_text_default_material_light': '#8A000000',
}
DEFAULT_COLOR = '#FF888888'

ANDROID_NS = 'xmlns:android="http://schemas.android.com/apk/res/android"'
FILE_STUBS = {
    'anim': f'<set {ANDROID_NS}/>',
    'animator': f'<set {ANDROID_NS}/>',
    'interpolator': f'<linearInterpolator {ANDROID_NS}/>',
    'layout': f'<FrameLayout {ANDROID_NS} android:layout_width="match_parent" '
              f'android:layout_height="match_parent"/>',
    'menu': f'<menu {ANDROID_NS}/>',
    'drawable': f'<shape {ANDROID_NS} android:shape="rectangle">'
                f'<solid android:color="#00000000"/></shape>',
    'mipmap': f'<shape {ANDROID_NS} android:shape="rectangle">'
              f'<solid android:color="#00000000"/></shape>',
    'xml': '<maxgram-stub/>',
}


def collect_defined(res: Path) -> set:
    defined = set()
    for f in res.rglob('*'):
        if f.is_dir():
            continue
        parent = f.parent.name
        if parent.startswith('values'):
            if f.suffix != '.xml' or f.name in ('public.xml', 'maxgram_stubs.xml'):
                continue
            text = f.read_text(encoding='utf-8', errors='ignore')
            for tag, name in VALUE_DEF_RE.findall(text):
                if tag in VALUE_TAGS:
                    defined.add((TAG_ALIAS.get(tag, tag), name))
            for t, name in ITEM_DEF_RE.findall(text):
                defined.add((t, name))
        else:
            defined.add((parent.split('-')[0], f.stem))
    return defined


def stage_fix_public(root: Path, apply: bool):
    pub = root / 'res/values/public.xml'
    res = root / 'res'
    if not pub.is_file():
        sys.exit(f'не найден {pub}')
    defined = collect_defined(res)

    undefined = {}
    for ln in pub.read_text(encoding='utf-8', errors='ignore').splitlines():
        m = PUBLIC_RE.search(ln)
        if m and (m.group(1), m.group(2)) not in defined:
            undefined.setdefault(m.group(1), []).append(m.group(2))

    total = sum(len(v) for v in undefined.values())
    if not total:
        print('fix-public: все символы public.xml определены, ничего не делаем')
        return
    print(f'fix-public: {total} символов без определений:')
    for t, names in sorted(undefined.items()):
        print(f'   {t}: {len(names)}')

    values_entries = []
    file_writes = {}
    skipped = []
    for t, names in sorted(undefined.items()):
        for n in names:
            if t == 'color':
                values_entries.append(f'    <color name="{n}">{CANON_COLORS.get(n, DEFAULT_COLOR)}</color>')
            elif t == 'dimen':
                values_entries.append(f'    <dimen name="{n}">0dp</dimen>')
            elif t == 'string':
                values_entries.append(f'    <string name="{n}"></string>')
            elif t == 'bool':
                values_entries.append(f'    <bool name="{n}">false</bool>')
            elif t == 'integer':
                values_entries.append(f'    <integer name="{n}">0</integer>')
            elif t == 'fraction':
                values_entries.append(f'    <fraction name="{n}">0%</fraction>')
            elif t == 'id':
                values_entries.append(f'    <item type="id" name="{n}"/>')
            elif t == 'style':
                values_entries.append(f'    <style name="{n}"/>')
            elif t in ('array', 'string-array', 'integer-array'):
                values_entries.append(f'    <array name="{n}"/>')
            elif t == 'plurals':
                values_entries.append(
                    f'    <plurals name="{n}"><item quantity="other"></item></plurals>')
            elif t == 'drawable':
                values_entries.append(f'    <item type="drawable" name="{n}">#00000000</item>')
            elif t in ('styleable', 'declare-styleable'):
                values_entries.append(f'    <declare-styleable name="{n}"></declare-styleable>')
            elif t == 'attr':
                values_entries.append(f'    <attr name="{n}" format="string"/>')
            elif t in FILE_STUBS:
                file_writes[f'res/{t}/{n}.xml'] = (
                    '<?xml version="1.0" encoding="utf-8"?>\n' + FILE_STUBS[t] + '\n')
            elif t == 'raw':
                file_writes[f'res/raw/{n}'] = ''
            else:
                skipped.append(f'{t}/{n}')

    stub_xml = ('<?xml version="1.0" encoding="utf-8"?>\n'
                '<!-- Maxgram: стабы для символов public.xml, потерянных при декомпиляции -->\n'
                '<resources>\n' + '\n'.join(values_entries) + '\n</resources>\n')

    print(f'{"WRITE" if apply else "WOULD"} res/values/maxgram_stubs.xml '
          f'({len(values_entries)} определений)')
    for rel in sorted(file_writes):
        print(f'{"WRITE" if apply else "WOULD"} {rel}')
    if skipped:
        print(f'!! пропущено (нет шаблона): {len(skipped)}')
        for s in skipped[:20]:
            print('   -', s)

    if apply:
        (res / 'values/maxgram_stubs.xml').write_text(stub_xml, encoding='utf-8')
        for rel, content in file_writes.items():
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content, encoding='utf-8')


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
        cmd + ['b', str(root), '-o', str(unsigned)],
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
    ap = argparse.ArgumentParser(description='Maxgram iOS26 patch tool v5')
    ap.add_argument('--root', default='26.25.0-1.5.2')
    ap.add_argument('--fix-public', action='store_true')
    ap.add_argument('--fix-styles', action='store_true')
    ap.add_argument('--tabbar', action='store_true')
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

    if args.fix_public:
        stage_fix_public(root, args.apply)

    if args.fix_styles:
        stage_fix_styles(root, args.apply)

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

    if not args.apply and (args.fix_public or args.fix_styles or args.tabbar or mapping or args.rebrand):
        print('\nЭто dry-run. Добавь --apply, чтобы записать изменения.')

    if args.build:
        Path(args.apk_out).parent.mkdir(parents=True, exist_ok=True)
        build(root, Path(args.apk_out), args.keystore, args.ks_pass)


if __name__ == '__main__':
    main()
