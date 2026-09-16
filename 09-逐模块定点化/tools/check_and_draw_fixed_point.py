#!/usr/bin/env python3
"""重绘跟踪定点文档的模块图，复算G1参数并检查符号及第10章保护范围。"""

import argparse
import hashlib
import json
import re
from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET


DOC_NAME = '18-跟踪逻辑定点化设计方案.md'
ROOT = Path(__file__).resolve().parents[1]
NAMES = {
    'overview': '图LTFP-00_跟踪逻辑总体数据流_v03',
    'ddc': '图LTFP-02_载波NCO与DDC数据关系_v03',
    'code': '图LTFP-03_码NCO定点数据关系_v03',
    'load': '图LTFP-04_捕获移交与NCO初始装载_v03',
    'taps': '图LTFP-05_五抽头与本地副本生成_v03',
    'corr': '图LTFP-06_分批相关与复数累加_v03',
    'pdi': '图LTFP-07_PDI结果冻结_v03',
    'example': '图LTFP-08_B1C_4_7ms移交积分区间_v03',
}
PROTECTED = {
    '图LTFP-09_单分量五抽头跟踪流程_v04.png':
        'af9e7cbc4da3363a65077448323f4693bd76f90b59abe955277bae040c234b71',
    '图LTFP-10_数据导频跟踪流程_v03.png':
        '5ef0b31e638106659877fd9c90784d2eac2de70023147f601f89e8452861ce2d',
    '图LTFP-11_BOC双副本跟踪流程_v03.png':
        'c8697a5d55690be2a23cd8f5416b5b1ce69db8c1b24e31002a77de468782037a',
}


def round_away(value):
    sign = -1 if value < 0 else 1
    value = abs(value)
    return sign * ((2 * value.numerator + value.denominator) // (2 * value.denominator))


class Diagram:
    """简洁黑白矢量图，框中文字和全部文字之间自动检查布局。"""

    def __init__(self, width, height, folder):
        import matplotlib
        matplotlib.use('Agg')
        matplotlib.rcParams.update({'svg.hashsalt': 'tracking-fixed-v042',
                                   'font.family': ['Times New Roman', 'SimSun'],
                                   'mathtext.fontset': 'custom',
                                   'mathtext.rm': 'Times New Roman',
                                   'mathtext.it': 'Times New Roman:italic',
                                   'mathtext.bf': 'Times New Roman:bold'})
        import matplotlib.pyplot as plt
        from matplotlib.font_manager import FontProperties
        self.plt = plt
        self.font = FontProperties(family=['Times New Roman', 'SimSun'])
        self.fig, self.ax = plt.subplots(figsize=(width / 100, height / 100))
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.ax.set(xlim=(0, width), ylim=(height, 0))
        self.ax.axis('off')
        self.width, self.height, self.folder = width, height, folder
        self.boxes, self.labels, self.edges = [], [], []

    def text(self, x, y, label, size=13, align='center'):
        artist = self.ax.text(x, y, label, ha=align, va='center', fontsize=size,
                              fontproperties=self.font, linespacing=1.25, color='black')
        self.labels.append(artist)
        return artist

    def box(self, x, y, width, height, label, size=14, shade=False):
        from matplotlib.patches import Rectangle
        rect = Rectangle((x, y), width, height, linewidth=0.85,
                         edgecolor='black', facecolor='white')
        self.ax.add_patch(rect)
        artist = self.text(x + width / 2, y + height / 2, label, size)
        self.boxes.append((rect, artist))

    def circle(self, x, y, radius, label):
        from matplotlib.patches import Circle
        self.ax.add_patch(Circle((x, y), radius, facecolor='white',
                                edgecolor='black', linewidth=0.85))
        self.text(x, y, label, 15)

    def diamond(self, x, y, width, height, label, size=14):
        from matplotlib.patches import Polygon
        vertices = [(x, y-height/2), (x+width/2, y), (x, y+height/2), (x-width/2, y)]
        self.ax.add_patch(Polygon(vertices, facecolor='white', edgecolor='black', linewidth=.85))
        self.text(x, y, label, size)

    def arrow(self, *points, dashed=False):
        from matplotlib.patches import FancyArrowPatch
        self.edges.extend(zip(points[:-1], points[1:]))
        if len(points) > 2:
            xs, ys = zip(*points[:-1])
            self.ax.plot(xs, ys, color='black', linewidth=0.85,
                         linestyle='--' if dashed else '-')
        self.ax.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle='-|>',
                                          mutation_scale=10, linewidth=0.85,
                                          color='black', shrinkA=0, shrinkB=0,
                                          linestyle='--' if dashed else '-'))

    def line(self, start, end, dashed=False):
        self.edges.append((start, end))
        self.ax.plot([start[0], end[0]], [start[1], end[1]], color='black',
                     linewidth=0.85, linestyle='--' if dashed else '-')

    def save(self, key):
        self.fig.canvas.draw()
        renderer = self.fig.canvas.get_renderer()
        text_bounds = [label.get_window_extent(renderer) for label in self.labels]
        canvas = self.fig.bbox
        for bounds in text_bounds:
            assert canvas.contains(bounds.x0, bounds.y0) and canvas.contains(bounds.x1, bounds.y1)
        for rect, label in self.boxes:
            outer = rect.get_window_extent(renderer)
            inner = label.get_window_extent(renderer)
            assert outer.x0 + 5 <= inner.x0 and inner.x1 <= outer.x1 - 5, label.get_text()
            assert outer.y0 + 5 <= inner.y0 and inner.y1 <= outer.y1 - 5, label.get_text()
        for i, a in enumerate(text_bounds):
            for b in text_bounds[i + 1:]:
                assert not a.overlaps(b), key + ': text overlap'
        # 直线不能穿过文字；边界留少量浮点余量。
        for start, end in self.edges:
            a, b = self.ax.transData.transform(start), self.ax.transData.transform(end)
            for bounds in text_bounds:
                x0, x1, y0, y1 = bounds.x0 - 2, bounds.x1 + 2, bounds.y0 - 2, bounds.y1 + 2
                if abs(a[0] - b[0]) < 0.01:
                    assert not (x0 < a[0] < x1 and max(min(a[1], b[1]), y0) < min(max(a[1], b[1]), y1)), key
                elif abs(a[1] - b[1]) < 0.01:
                    assert not (y0 < a[1] < y1 and max(min(a[0], b[0]), x0) < min(max(a[0], b[0]), x1)), key
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / (NAMES[key] + '.svg')
        self.fig.savefig(path, facecolor='white', metadata={'Date': None})
        path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines()) + '\n')
        svg_text = path.read_text()
        assert 'SimSun' in svg_text and 'TimesNewRoman' in svg_text, key + ': fonts'
        self.fig.savefig(path.with_suffix('.png'), facecolor='white', dpi=180)
        self.plt.close(self.fig)


def draw_overview(folder):
    d = Diagram(1100, 280, folder)
    for x, w, label in [(30, 145, 'ADC 输入'), (285, 165, '载波 DDC'),
                         (560, 200, '相关与积分'), (890, 175, 'PDI 输出')]:
        d.box(x, 160, w, 52, label)
    for a, b, label in [(175, 285, 's4 I/Q'), (450, 560, 's5 I/Q'),
                         (760, 890, 's18 / s20 I/Q')]:
        d.arrow((a, 186), (b, 186))
        d.text((a+b)/2, 167, label, 12)
    d.box(285, 25, 165, 62, '载波 NCO\n正余弦表')
    d.arrow((367.5, 87), (367.5, 160))
    d.text(387.5, 124, 'sQ1.4', 12, 'left')
    d.box(560, 25, 200, 62, '本地码与五抽头')
    d.arrow((660, 87), (660, 160))
    d.text(680, 124, '±1', 12, 'left')
    d.box(890, 25, 175, 62, '码 NCO')
    d.arrow((890, 56), (760, 56))
    d.text(825, 35, 'uQ14.36', 12)
    d.arrow((977.5, 87), (977.5, 160))
    d.text(996, 124, '1 ms 边界', 11, 'left')
    d.text(812, 247, '各支路独立积分，输出保持原位宽', 12)
    d.save('overview')


def draw_ddc(folder):
    d = Diagram(1060, 275, folder)
    d.box(55, 25, 150, 46, '载波 NCO')
    d.box(315, 25, 205, 46, '正余弦系数表')
    d.arrow((205, 48), (315, 48))
    d.text(260, 31, 'u32', 12)
    d.arrow((417.5, 71), (417.5, 142))
    d.text(433, 105, 'sQ1.4', 12, 'left')
    d.box(55, 142, 150, 54, 'ADC 输入')
    d.box(315, 142, 205, 54, '复数乘加')
    d.box(640, 142, 205, 54, '算术右移 4 bit')
    for a, b, label in [(205, 315, 's4 I/Q'), (520, 640, 's9 I/Q'),
                         (845, 1005, 's5 I/Q')]:
        d.arrow((a, 169), (b, 169))
        d.text((a+b)/2, 150, label, 12)
    d.text(925, 190, '基带输出', 12)
    d.text(417.5, 226, '4 次实乘，2 次加减', 12)
    d.text(742.5, 226, r'$R=\lfloor T/16\rfloor$', 13)
    d.save('ddc')


def draw_code(folder):
    d = Diagram(1060, 325, folder)
    d.box(30, 150, 195, 56, '码相位寄存器')
    d.circle(350, 178, 17, '+')
    d.arrow((225, 178), (333, 178))
    d.text(279, 159, r'$P_{code}$', 13)
    d.box(260, 25, 180, 48, '码步进')
    d.arrow((350, 73), (350, 161))
    d.text(370, 113, 'uQ0.36', 12, 'left')
    d.box(560, 150, 190, 56, '主码周期回绕')
    d.arrow((367, 178), (560, 178))
    d.text(453, 158, r'$P_{next}$', 13)
    d.box(850, 150, 180, 56, '更新连续相位')
    d.arrow((750, 178), (850, 178))
    d.arrow((940, 206), (940, 266), (127.5, 266), (127.5, 206))
    d.text(534, 291, '下一样点的码相位；uQ14.36', 12)
    d.box(560, 25, 190, 48, '1 ms 边界比较')
    d.arrow((495, 178), (495, 49), (560, 49))
    d.arrow((750, 49), (1010, 49))
    d.text(872, 29, 'PDI 结束信号', 12)
    d.text(655, 105, r'$P_{next}\geq B_{next}$', 13)
    d.save('code')


def draw_load(folder):
    d = Diagram(1140, 375, folder)
    rows = [
        (25, '载波多普勒', 's14 Hz', r'$\times H_c$', '舍入与模回绕',
         r'$\mathrm{round}(T_c/2^{16})\ \mathrm{mod}\ 2^{32}$', '载波步进', 'u32'),
        (135, '载波多普勒', 's14 Hz', r'$\times H_a$', '舍入后加标称步进',
         r'$\mathrm{round}(T_a/2^{18})+K_{code,0}$', '初始码步进', 'uQ0.36'),
        (245, '移交码相位', 'uQ15.8 dump', r'$\times R_{code}$', '左移 17 bit',
         r'$P_{load}=(C_{dump,Q8} R_{code})\ll17$', '初始码相位', 'uQ14.36'),
    ]
    for y, left, infmt, multiply, process, formula, right, outfmt in rows:
        d.box(30, y, 165, 48, left)
        d.text(112.5, y+70, infmt, 12)
        d.box(280, y, 160, 48, multiply)
        d.box(530, y, 250, 48, process)
        d.text(655, y+70, formula, 12)
        d.box(925, y, 185, 48, right)
        d.text(1017.5, y+70, outfmt, 12)
        for a, b in [(195, 280), (440, 530), (780, 925)]:
            d.arrow((a, y+24), (b, y+24))
    d.text(570, 352, '到启动计数时同时装载；载波相位初值为 0', 12)
    d.save('load')


def draw_taps(folder):
    d = Diagram(1140, 320, folder)
    d.box(25, 30, 180, 50, 'Prompt 码相位')
    d.box(300, 30, 215, 50, '抽头偏移与回绕')
    d.box(600, 30, 215, 50, '地址与小数分离')
    d.box(910, 30, 200, 50, '主码 RAM')
    for a, b in [(205, 300), (515, 600), (815, 910)]:
        d.arrow((a, 55), (b, 55))
    d.text(115, 108, 'uQ14.36', 12)
    d.box(300, 190, 215, 50, '抽头间距对齐')
    d.arrow((407.5, 190), (407.5, 80))
    d.text(432, 133, '左移 26 bit', 12, 'left')
    d.text(407.5, 265, 'uQ1.10 → uQ1.36', 12)
    d.box(600, 190, 215, 50, '本地符号组合')
    d.arrow((707.5, 80), (707.5, 190))
    d.text(730, 134, r'$F_t[35]$', 13, 'left')
    d.arrow((1010, 80), (1010, 215), (815, 215))
    d.text(930, 194, 'PRN', 12)
    d.arrow((707.5, 240), (707.5, 290), (1080, 290))
    d.text(930, 268, '5 / 6 / 11 个码符号', 12)
    d.text(112, 216, 'VE / E / P / L / VL', 12)
    d.save('taps')


def draw_corr(folder):
    d = Diagram(1120, 330, folder)
    d.box(30, 130, 175, 52, '基带 I/Q')
    d.circle(350, 156, 17, '×')
    d.box(270, 25, 160, 48, '本地码符号')
    d.arrow((350, 73), (350, 139))
    d.text(370, 105, '±1', 12, 'left')
    d.arrow((205, 156), (333, 156))
    d.text(265, 137, 's5', 12)
    d.circle(605, 156, 17, '+')
    d.arrow((367, 156), (588, 156))
    d.text(473, 137, 's5 I/Q', 12)
    d.text(473, 183, '保持原值或取反', 12)
    d.box(810, 130, 230, 52, '分支积分寄存器')
    d.arrow((622, 156), (810, 156))
    d.text(716, 137, 's19 / s21', 12)
    d.text(945, 217, 's18 / s20', 12, 'left')
    d.arrow((925, 182), (925, 255), (605, 255), (605, 173))
    d.text(757, 236, r'$A$', 13)
    d.text(560, 302, '同批最多 3 条复数通路；各分量、副本和抽头独立保存积分', 12)
    d.save('corr')


def draw_pdi(folder):
    d = Diagram(1080, 345, folder)
    d.box(30, 70, 210, 52, '加入当前样点')
    d.text(135, 150, r'$S=A+u$', 13)
    d.diamond(520, 96, 260, 110, r'$P_{next}\geq B_{next}$', 14)
    d.arrow((240, 96), (390, 96))
    d.box(850, 70, 200, 52, '继续积分')
    d.arrow((650, 96), (850, 96))
    d.text(750, 77, '否', 12)
    d.text(950, 150, r'$A\leftarrow S$', 13)
    d.box(415, 236, 210, 52, '保存 PDI 结果')
    d.arrow((520, 151), (520, 236))
    d.text(544, 193, '是', 12)
    d.text(520, 315, r'$R\leftarrow S$', 13)
    d.box(850, 236, 200, 52, '积分清零')
    d.arrow((625, 262), (850, 262))
    d.text(950, 315, r'$A\leftarrow0$', 13)
    d.text(135, 262, '所有有效支路\n共用同一边界', 13)
    d.save('pdi')


def draw_example(folder):
    d = Diagram(1120, 275, folder)
    at = lambda ms: 60 + (ms - 4) * 980 / 3
    x = [at(ms) for ms in [4, 4.7, 5, 6, 7]]
    d.text(at(4.7), 35, '移交约 4.7 ms\nPrompt 约 4808.1 chip', 13)
    d.arrow((at(4.7), 66), (at(4.7), 94))
    d.line((60, 100), (1040, 100))
    for pos in x:
        d.line((pos, 94), (pos, 106))
    for pos, label in [(at(4), '4 ms\n4092 chip'), (at(5), '5 ms\n5115 chip'),
                        (at(6), '6 ms\n6138 chip'), (at(7), '7 ms\n7161 chip')]:
        d.text(pos, 133, label, 12)
    for left, right, label in [(at(4.7), at(5), 'R0\n约0.3 ms'),
                               (at(5), at(6), 'R1\n约5～6 ms'),
                               (at(6), at(7), 'R2\n约6～7 ms')]:
        d.box(left, 175, right - left, 60, label, 12)
    d.text(560, 259, '每段分别积成一个结果', 12)
    d.save('example')


def verify(doc, folder, reference_vault):
    text = doc.read_text()
    matches = re.findall(r'^\| ([+-]?\d+) \| (\d+\.\d{4}) \| (3429262950) \| (\d+) \| (\d+\.\d{6}) \|$', text, re.M)
    assert len(matches) == 14 and [int(x[0]) for x in matches] == list(range(-7, 7))
    rows = []
    for channel, frequency, code, ha, actual in matches:
        k = int(channel)
        rf = 1602000000 + 562500 * k
        expected_code = round_away(Fraction(2**36 * 511000, 10240000))
        expected_ha = round_away(Fraction(2**54 * 511000, rf * 10240000))
        assert Fraction(frequency) * 1000000 == rf
        assert int(code) == expected_code and int(ha) == expected_ha
        assert abs(Fraction(actual) - Fraction(expected_ha, 2**18)) <= Fraction(1, 2000000)
        rows.append(dict(channel=k, rf_hz=rf, nominal_step=expected_code, aiding_raw=expected_ha))
    for s in ['roundQ16', 'roundQ18', 'roundEven', '>>', '<<', '装载前必须检查',
              '才允许装载', '无效移交描述符', '必须重新核定位宽']:
        assert s not in text, s
    assert text.index('## 计算符号约定') < text.index('## 1 设计范围')
    assert sum(line.strip() == '$$' for line in text.splitlines()) % 2 == 0
    for value in [Fraction(7, 2), Fraction(-7, 2), Fraction(5, 2), Fraction(-5, 2)]:
        assert round_away(value) == (4 if value == Fraction(7, 2) else
                                     -4 if value == Fraction(-7, 2) else
                                     3 if value > 0 else -3)
    assert [round(Fraction(n, 2)) for n in [5, 7, -5, -7]] == [2, 4, -2, -4]
    assert round(Fraction(1, 3) * 2**10) == 341
    assert round(Fraction(2, 3) * 2**10) == 683
    assert round_away(Fraction(164926746000, 2**16)) == 2516582
    assert round_away(Fraction(6854098500, 2**18)) == 26146
    assert Fraction(-60, 16).__floor__() == -4
    images = re.findall(r'!\[\[90-附件/([^\]]+)\]\]', text)
    assert len(images) == 11
    for name in NAMES.values():
        assert name + '.svg' in images
        ET.parse(folder / (name + '.svg'))
        assert (folder / (name + '.png')).exists()
        glyphs = (folder / (name + '.svg')).read_text()
        assert 'SimSun' in glyphs and 'TimesNewRoman' in glyphs
        assert 'NotoSans' not in glyphs and 'DejaVuSans' not in glyphs
    for name, digest in PROTECTED.items():
        assert name in images
        assert hashlib.sha256((reference_vault / '90-附件' / name).read_bytes()).hexdigest() == digest
    original = (reference_vault / '09-逐模块定点化' / DOC_NAME).read_text()
    chapter = lambda content: content.split('## 10 三类跟踪硬件流程汇总')[1].split('## 修改记录')[0]
    assert chapter(text) == chapter(original), '第10章被修改'
    return dict(g1_channels=rows, rounding_examples='PASS', symbols='PASS',
                new_diagrams=len(NAMES), chapter_10_unchanged=True,
                diagram_fonts=dict(chinese='SimSun', latin='Times New Roman',
                                   svg_glyphs_embedded=True),
                diagram_names=list(NAMES.values()),
                chapter_10_sha256=hashlib.sha256(chapter(text).encode()).hexdigest(),
                protected_image_sha256=PROTECTED)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--asset-dir', type=Path, default=ROOT.parent / '90-附件')
    parser.add_argument('--reference-vault', type=Path, default=ROOT.parent)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    if not args.check_only:
        for drawing in [draw_overview, draw_ddc, draw_code, draw_load,
                        draw_taps, draw_corr, draw_pdi, draw_example]:
            drawing(args.asset_dir)
    result = verify(ROOT / DOC_NAME, args.asset_dir, args.reference_vault)
    if not args.check_only:
        (ROOT / '定点文档核算.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
