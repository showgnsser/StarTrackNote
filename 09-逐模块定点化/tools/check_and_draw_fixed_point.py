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
    'overview': '图LTFP-00_跟踪逻辑总体数据流_v02',
    'ddc': '图LTFP-02_载波NCO与DDC数据关系_v02',
    'code': '图LTFP-03_码NCO定点数据关系_v02',
    'load': '图LTFP-04_捕获移交与NCO初始装载_v02',
    'taps': '图LTFP-05_五抽头与本地副本生成_v02',
    'corr': '图LTFP-06_分批相关与复数累加_v02',
    'pdi': '图LTFP-07_PDI结果冻结_v02',
    'example': '图LTFP-08_B1C_4_7ms移交积分区间_v02',
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
        matplotlib.rcParams.update({'svg.hashsalt': 'tracking-fixed-v040',
                                   'mathtext.fontset': 'dejavusans'})
        import matplotlib.pyplot as plt
        from matplotlib.font_manager import FontProperties
        self.plt = plt
        self.font = FontProperties(fname='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
        self.fig, self.ax = plt.subplots(figsize=(width / 100, height / 100))
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.ax.set(xlim=(0, width), ylim=(height, 0))
        self.ax.axis('off')
        self.width, self.height, self.folder = width, height, folder
        self.boxes, self.labels, self.edges = [], [], []

    def text(self, x, y, label, size=13, align='center'):
        artist = self.ax.text(x, y, label, ha=align, va='center', fontsize=size,
                              fontproperties=self.font, linespacing=1.55, color='#202020')
        self.labels.append(artist)
        return artist

    def box(self, x, y, width, height, label, size=14, shade=False):
        from matplotlib.patches import Rectangle
        rect = Rectangle((x, y), width, height, linewidth=1.1,
                         edgecolor='#303030', facecolor='#f4f4f4' if shade else 'white')
        self.ax.add_patch(rect)
        artist = self.text(x + width / 2, y + height / 2, label, size)
        self.boxes.append((rect, artist))

    def arrow(self, *points, dashed=False):
        from matplotlib.patches import FancyArrowPatch
        self.edges.extend(zip(points[:-1], points[1:]))
        if len(points) > 2:
            xs, ys = zip(*points[:-1])
            self.ax.plot(xs, ys, color='#303030', linewidth=1.1,
                         linestyle='--' if dashed else '-')
        self.ax.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle='-|>',
                                          mutation_scale=11, linewidth=1.1,
                                          color='#303030', shrinkA=0, shrinkB=0,
                                          linestyle='--' if dashed else '-'))

    def line(self, start, end, dashed=False):
        self.edges.append((start, end))
        self.ax.plot([start[0], end[0]], [start[1], end[1]], color='#303030',
                     linewidth=1.0, linestyle='--' if dashed else '-')

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
        self.fig.savefig(path.with_suffix('.png'), facecolor='white', dpi=160)
        self.plt.close(self.fig)


def draw_overview(folder):
    d = Diagram(1100, 355, folder)
    for x, w, text in [(30, 175, 'ADC输入\ns4 I/Q'),
                        (270, 210, '载波DDC\ns5 I/Q'),
                        (550, 225, '多支路相关与积分\ns18 / s20 I/Q'),
                        (845, 225, 'PDI结果输出\n保持积分原位宽')]:
        d.box(x, 50, w, 85, text)
    for a, b in [(205, 270), (480, 550), (775, 845)]:
        d.arrow((a, 92.5), (b, 92.5))
    d.box(270, 220, 210, 85, '载波NCO与系数表\nu32相位 → sin/cos')
    d.arrow((375, 220), (375, 135))
    d.box(550, 220, 225, 85, '本地码与五抽头\n输出 ±1 码符号')
    d.arrow((662.5, 220), (662.5, 135))
    d.box(845, 220, 225, 85, '码NCO\nuQ14.36连续相位')
    d.arrow((845, 262.5), (775, 262.5))
    d.arrow((957.5, 220), (957.5, 135))
    d.text(1010, 177, '1 ms边界', 11)
    d.save('overview')


def draw_ddc(folder):
    d = Diagram(1120, 340, folder)
    for x, w, label in [(25, 155, 'ADC样点\ns4 I/Q'),
                         (235, 175, '四次实数乘法\n单项s8'),
                         (465, 175, '复数加减\n中间量s9'),
                         (695, 190, '算术右移4 bit\n' + r'$\lfloor T/16\rfloor$'),
                         (940, 155, '基带输出\ns5 I/Q')]:
        d.box(x, 195, w, 85, label)
    for a, b in [(180, 235), (410, 465), (640, 695), (885, 940)]:
        d.arrow((a, 237.5), (b, 237.5))
    d.box(25, 35, 155, 80, '载波NCO\nu32相位累加')
    d.box(235, 35, 175, 80, '16相位系数表\nsQ1.4 sin/cos')
    d.arrow((180, 75), (235, 75))
    d.arrow((322.5, 115), (322.5, 195))
    d.text(660, 76, '4次实乘、2次加减；I/Q按同一相位旋转', 14)
    d.text(560, 315, '右移向负无穷取整；输出范围 −10～+10', 13)
    d.save('ddc')


def draw_code(folder):
    d = Diagram(1050, 500, folder)
    d.box(30, 35, 245, 85, '当前Prompt码相位\n' + r'$P_{code}$' + '：uQ14.36')
    d.box(385, 35, 245, 85, '高14 bit：码片地址\n低36 bit：小数相位')
    d.box(740, 35, 280, 85, '本地码与五抽头\n供当前样点使用')
    d.arrow((275, 77.5), (385, 77.5))
    d.arrow((630, 77.5), (740, 77.5))
    d.box(30, 200, 245, 85, '加一次码步进\n' + r'$P_{next}=P_{code}+K_{code}$', 13)
    d.box(385, 200, 245, 85, '完整主码回绕\n到末端才减一个码周期')
    d.box(740, 200, 280, 85, '保存连续码相位\n供下一ADC样点使用')
    d.arrow((152.5, 120), (152.5, 200))
    d.text(255, 159, '当前样点完成后', 11)
    d.arrow((275, 242.5), (385, 242.5))
    d.arrow((630, 242.5), (740, 242.5))
    d.box(30, 365, 245, 85, '比较下一1 ms边界\n' + r'$P_{next}\geq B_{next}$')
    d.box(385, 365, 245, 85, 'PDI结束信号\n所有相关支路共用')
    d.arrow((152.5, 285), (152.5, 365))
    d.arrow((275, 407.5), (385, 407.5))
    d.text(880, 407, '片段边界只结束积分\n不把连续码相位置零', 14)
    d.save('code')


def draw_load(folder):
    d = Diagram(1140, 495, folder)
    rows = [
        (30, '载波多普勒\n' + r'$f_d$' + '：s14 Hz',
         r'$T_c=f_d\times H_c$' + '\n' + r'$\mathrm{round}(T_c/2^{16})\ \mathrm{mod}\ 2^{32}$',
         '载波步进\n' + r'$K_c$' + '：u32'),
        (175, '载波多普勒\n' + r'$f_d$' + '：s14 Hz',
         r'$\Delta K_{code}=\mathrm{round}(f_d H_a/2^{18})$' + '\n' + r'$K_{code,0}+\Delta K_{code}$',
         '初始码步进\n' + r'$K_{code,init}$' + '：uQ0.36'),
        (320, '移交码相位\nuQ15.8，单位dump',
         r'$P_{load}=(C_{dump,Q8}\times R_{code})\ll17$' + '\n整数乘法与左移',
         '初始码相位\n' + r'$P_{load}$' + '：uQ14.36'),
    ]
    for y, left, center, right in rows:
        d.box(30, y, 210, 100, left)
        d.box(330, y, 440, 100, center, 14)
        d.box(860, y, 250, 100, right)
        d.arrow((240, y + 50), (330, y + 50))
        d.arrow((770, y + 50), (860, y + 50))
    d.text(570, 466, '到启动计数时同时装载；载波相位初值为0', 14)
    d.save('load')


def draw_taps(folder):
    d = Diagram(1140, 420, folder)
    d.box(25, 40, 195, 85, 'Prompt码相位\nuQ14.36')
    d.box(295, 40, 245, 85, '加入五抽头偏移\n在完整主码内回绕')
    d.box(615, 40, 220, 85, '每抽头地址与小数\n' + r'$A_t=P_t\gg36$')
    d.box(910, 40, 205, 85, '读取主码RAM\n每码片1 bit')
    for a, b in [(220, 295), (540, 615), (835, 910)]:
        d.arrow((a, 82.5), (b, 82.5))
    d.box(295, 210, 245, 85, '抽头间距uQ1.10\n左移26 bit对齐')
    d.arrow((417.5, 210), (417.5, 125))
    d.box(615, 210, 220, 85, '本地符号生成\nPRN与半码片符号组合')
    d.arrow((725, 125), (725, 210))
    d.arrow((1012.5, 125), (1012.5, 252.5), (835, 252.5))
    d.box(615, 340, 500, 55, '按资源池输出5 / 6 / 11个 ±1 码符号', 14)
    d.arrow((725, 295), (725, 340))
    d.text(270, 354, 'VE、E为负偏移；P为0\nL、VL为正偏移', 13)
    d.save('taps')


def draw_corr(folder):
    d = Diagram(1150, 460, folder)
    d.box(30, 35, 190, 80, 'DDC基带I/Q\ns5，当前样点保持')
    d.box(285, 35, 310, 80, '按资源池选支路\nVE → E → P → L → VL')
    d.box(30, 185, 190, 80, '当前支路本地码\n+1 / −1')
    d.box(285, 185, 310, 80, '符号相关\n+1保留原值；−1取反')
    d.box(665, 185, 210, 80, '加到该支路积分\n中间量s19 / s21')
    d.box(935, 185, 185, 80, '写回积分状态\ns18 / s20')
    d.arrow((220, 75), (285, 75))
    d.arrow((440, 115), (440, 185))
    d.arrow((220, 225), (285, 225))
    d.arrow((595, 225), (665, 225))
    d.arrow((875, 225), (935, 225))
    d.box(665, 35, 210, 80, '读出该支路积分\nI、Q分别保存')
    d.arrow((770, 115), (770, 185))
    d.text(440, 340, '同批最多3条复数通路\n各支路积分历史独立', 14)
    d.box(665, 345, 455, 65, '全部批次完成 → 处理下一ADC样点', 14)
    d.arrow((1027.5, 265), (1027.5, 345))
    d.save('corr')


def draw_pdi(folder):
    d = Diagram(1120, 440, folder)
    d.box(30, 40, 230, 90, '先加入当前样点\n' + r'$S=A+u$')
    d.box(360, 40, 310, 90, 'Prompt码相位边界\n' + r'$P_{next}\geq B_{next}$' + '？')
    d.arrow((260, 85), (360, 85))
    d.box(800, 40, 290, 90, '继续当前PDI\n' + r'$A\leftarrow S$')
    d.arrow((670, 85), (800, 85))
    d.text(735, 61, '否', 13)
    d.box(360, 230, 310, 90, '保存本条PDI结果\n' + r'$R\leftarrow S$')
    d.arrow((515, 130), (515, 230))
    d.text(540, 180, '是', 13)
    d.box(800, 230, 290, 90, '清零该支路积分\n' + r'$A\leftarrow0$')
    d.arrow((670, 275), (800, 275))
    d.text(145, 267, '每个有效I/Q支路\n均执行相同操作', 14)
    d.text(560, 393, '先保存包含当前样点的结果，再清零；下一样点进入下一条PDI', 14)
    d.save('pdi')


def draw_example(folder):
    d = Diagram(1120, 320, folder)
    at = lambda ms: 60 + (ms - 4) * 980 / 3
    x = [at(ms) for ms in [4, 4.7, 5, 6, 7]]
    d.text(at(4.7), 40, '移交：约4.7 ms\nPrompt约4808.1 chip', 13)
    d.arrow((at(4.7), 76), (at(4.7), 112))
    d.line((60, 120), (1040, 120))
    for pos in x:
        d.line((pos, 114), (pos, 127))
    for pos, label in [(at(4), '4 ms\n4092 chip'), (at(5), '5 ms\n5115 chip'),
                        (at(6), '6 ms\n6138 chip'), (at(7), '7 ms\n7161 chip')]:
        d.text(pos, 157, label, 12)
    for left, right, label in [(at(4.7), at(5), 'R0\n约0.3 ms'),
                               (at(5), at(6), 'R1\n约5～6 ms'),
                               (at(6), at(7), 'R2\n约6～7 ms')]:
        d.box(left, 202, right - left, 68, label, 12)
    d.text(560, 302, '每段数据积成一个结果；图中数字为便于阅读的近似值', 12)
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
    for name, digest in PROTECTED.items():
        assert name in images
        assert hashlib.sha256((reference_vault / '90-附件' / name).read_bytes()).hexdigest() == digest
    original = (reference_vault / '09-逐模块定点化' / DOC_NAME).read_text()
    chapter = lambda content: content.split('## 10 三类跟踪硬件流程汇总')[1].split('## 修改记录')[0]
    assert chapter(text) == chapter(original), '第10章被修改'
    return dict(g1_channels=rows, rounding_examples='PASS', symbols='PASS',
                new_diagrams=len(NAMES), chapter_10_unchanged=True,
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
