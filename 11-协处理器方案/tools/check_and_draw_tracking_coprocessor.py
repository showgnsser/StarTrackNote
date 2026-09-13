#!/usr/bin/env python3
"""核对跟踪协处理器预算、整数运算及分块语义，绘制本章结构图。"""

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / '跟踪混频与相关协处理器处理流程与资源预算.md'
UNIT = 1 << 36
COS = [15, 12, 8, 3, -3, -8, -12, -15, -15, -12, -8, -3, 3, 8, 12, 15]
SIN = [3, 8, 12, 15, 15, 12, 8, 3, -3, -8, -12, -15, -15, -12, -8, -3]
# 信号、池、每毫秒样点数、主码长度、主码片段数。
SIGNALS = [
    ('L1CA', 0, 7680, 1023, 1), ('B1I', 0, 7680, 2046, 1),
    ('L5', 1, 30720, 10230, 1), ('B2a', 1, 30720, 10230, 1),
    ('E5a', 1, 30720, 10230, 1), ('G1', 2, 10240, 511, 1),
    ('E1', 3, 7680, 4092, 4), ('B1C', 3, 7680, 10230, 10),
]
POOL_SAMPLES = [7680, 30720, 10240, 7680]
POOL_BRANCHES = [5, 6, 5, 11]
POOL_BITS = [18, 20, 18, 18]
TARGET_COUNTS = [48, 48, 12, 36]


def budget():
    """使用整数核算四资源池及六通道示例；带宽按每毫秒任务量换算。"""
    pools = []
    for i, (n, branches, bits) in enumerate(zip(POOL_SAMPLES, POOL_BRANCHES, POOL_BITS)):
        payload = 4 * ((branches * 2 * bits + 31) // 32)
        pools.append(dict(pool=i, samples=n, complex_contributions=n * branches,
                          ddc_cycles=8 * n, corr_cycles=5 * n,
                          ddc_us=8 * n / 800, corr_us=5 * n / 800,
                          ddc_channel_limit=800000 // (8 * n),
                          corr_channel_limit=800000 // (5 * n),
                          example_80_percent=640000 // (8 * n),
                          payload_bytes=payload, record_bytes=payload + 16))
    counts = [3, 1, 1, 1]
    total_samples = sum(n * c for n, c in zip(POOL_SAMPLES, counts))
    assert total_samples == 71680 and sum(counts) == 6
    result_bytes = sum(p['record_bytes'] * c for p, c in zip(pools, counts))
    assert result_bytes == 276
    storage = dict(raw_three_buffers=3 * sum(POOL_SAMPLES), baseband_ab=1024,
                   source_codes=3 * 128 + 2560 + 64 + 2560,
                   working_codes=2560, channel_states=6 * 128,
                   result_buffers=2 * result_bytes, ddc_coefficients=20,
                   descriptor_slots=2 * 8 * 32)
    assert sum(storage.values()) == 179964
    cases = []
    for count in ([8, 0, 0, 2], counts, [4, 1, 2, 2], [0, 4, 0, 0]):
        n = sum(a * b for a, b in zip(POOL_SAMPLES, count))
        cases.append(dict(channels=count, samples=n, ddc_utilization=8 * n / 800000,
                          corr_utilization=5 * n / 800000))
    return dict(clock_hz=800000000, ddc_interval=8, corr_interval=5, block_samples=256,
                pools=pools, combinations=cases, six_channel_storage=storage,
                total_storage_bytes=sum(storage.values()),
                total_storage_kib=sum(storage.values()) / 1024,
                six_channel_baseband_read_MB_s=total_samples * 2 / 1000,
                six_channel_baseband_write_MB_s=total_samples * 2 / 1000)


def target_budget():
    """按用户确认的四池144通道计算；并行数是算术需求及示例，不是RTL实测。"""
    pools = []
    for i, (count, samples, branches, bits) in enumerate(
            zip(TARGET_COUNTS, POOL_SAMPLES, POOL_BRANCHES, POOL_BITS)):
        total = count * samples
        record_bytes = 4 * ((branches * bits * 2 + 31) // 32) + 16
        pools.append(dict(pool=i, channels=count, samples_per_ms=total,
                          samples_M_s=total / 1000, mixing_cycles=total * 8,
                          correlation_cycles=total * 5,
                          contributions_per_ms=total * branches,
                          accumulator_bits=count * branches * bits * 2,
                          pdi_record_bytes_per_ms=count * record_bytes))
    total = sum(p['samples_per_ms'] for p in pools)
    assert sum(TARGET_COUNTS) == 144 and total == 2242560
    mix_cycles, corr_cycles = total * 8, total * 5
    def required(cycles, cycle_budget):
        return (cycles + cycle_budget - 1) // cycle_budget
    parallel_min = dict(mixing=required(mix_cycles, 800000),
                        correlation_groups=required(corr_cycles, 800000))
    parallel_example = dict(mixing=required(mix_cycles, 640000),
                            correlation_groups=required(corr_cycles, 640000))
    assert parallel_min == dict(mixing=23, correlation_groups=15)
    assert parallel_example == dict(mixing=29, correlation_groups=18)
    source_code_max = 48 * 256 + 48 * 2560 + 64 + 36 * 2560
    source_code_min = 48 * 128 + 48 * 2560 + 64 + 36 * 1024
    output_per_ms = sum(p['pdi_record_bytes_per_ms'] for p in pools)
    accumulator_bits = sum(p['accumulator_bits'] for p in pools)
    assert output_per_ms == 7152 and accumulator_bits == 36576
    storage = dict(raw_eight_streams=399360, baseband_64_blocks=64 * 512,
                   source_codes_worst=source_code_max, working_codes=18 * 2560,
                   channel_states=144 * 128, double_results=2 * output_per_ms,
                   mixing_coefficients=29 * 20, task_queues=2 * 144 * 32,
                   baseband_descriptors=64 * 16)
    assert sum(storage.values()) == 749156
    return dict(channels=144, counts_by_pool=TARGET_COUNTS, pools=pools,
                samples_per_ms=total, samples_G_s=total / 1e6,
                mixing_cycles=mix_cycles, correlation_cycles=corr_cycles,
                minimum_parallel=parallel_min, example_at_80_percent=parallel_example,
                example_mixing_utilization=mix_cycles / (29 * 800000),
                example_correlation_utilization=corr_cycles / (18 * 800000),
                raw_read_GB_s=total / 1e6, baseband_write_GB_s=2 * total / 1e6,
                baseband_read_GB_s=2 * total / 1e6,
                payload_traffic_GB_s=5 * total / 1e6,
                pdi_rate_per_s=144000, pdi_output_MB_s=output_per_ms / 1000,
                complex_results_per_pdi_set=sum(n*b for n,b in zip(TARGET_COUNTS, POOL_BRANCHES)),
                total_accumulator_bits=accumulator_bits,
                source_code_bytes_min=source_code_min, source_code_bytes_max=source_code_max,
                storage_example=storage, total_storage_bytes=sum(storage.values()),
                total_storage_kib=sum(storage.values()) / 1024,
                nominal_256_point_blocks_per_ms=total // 256,
                rtl_timing_verified=False)


def ddc(i, q, phase):
    """s4输入、固定整数表、s9乘加、向负无穷右移。"""
    index = (phase >> 28) & 15
    return ((i * COS[index] + q * SIN[index]) // 16,
            (q * COS[index] - i * SIN[index]) // 16)


def check_ddc():
    values = []
    for index in range(16):
        for i in range(-8, 8):
            for q in range(-8, 8):
                values.extend(ddc(i, q, index << 28))
    assert min(values) == -10 and max(values) == 10
    assert ddc(5, -3, 0) == (4, -4)
    return dict(vectors=4096, minimum=min(values), maximum=max(values))


def code_sign(address, component):
    """只用于边界测试的固定二值码表，不生成射频信号或GNSS真实主码。"""
    word = ((address + 1) * 2654435761 + component * 2246822519) & 0xffffffff
    return 1 - 2 * ((word ^ (word >> 7) ^ (word >> 17)) & 1)


def reference(signal, chunks):
    """按给定块长逐点处理，跨搬运块保留载波/码相位与部分和。"""
    name, pool, n_ms, length, segments = signal
    width = length * UNIT
    seg_width = width // segments
    step = (2 * seg_width + n_ms) // (2 * n_ms)
    phase = UNIT // 4
    if name == 'B1C':
        phase = 2464154 * 1023 * (1 << 17)
    carrier, carrier_step = 123456789, 34953
    segment = phase // seg_width
    period = 0
    boundary = (segment + 1) * seg_width
    branches = POOL_BRANCHES[pool]
    accum = [[0, 0] for _ in range(branches)]
    results = []
    total = 2 * n_ms + 17
    if name == 'E1':
        total = 5 * n_ms + 17
    elif name == 'B1C':
        total = 7 * n_ms + 17
    offsets = [0, -341 * (1 << 26), 341 * (1 << 26),
               -683 * (1 << 26), 683 * (1 << 26)]
    position, chunk_index, first = 0, 0, 0
    while position < total:
        size = min(chunks[chunk_index % len(chunks)], total - position)
        # 每块先完成DDC，模拟两级通过SRAM交接；载波在此领先码NCO。
        mixed = []
        for index in range(position, position + size):
            i, q = (index * 5 + 3) % 16 - 8, (index * 7 + 9) % 16 - 8
            mixed.append(ddc(i, q, carrier))
            carrier = (carrier + carrier_step) & 0xffffffff
        for local, (i, q) in enumerate(mixed):
            absolute = position + local
            signs = []
            raw_signs = []
            for offset in offsets:
                tap_phase = (phase + offset) % width
                raw = code_sign(tap_phase >> 36, 0)
                raw_signs.append(raw)
                full = raw
                if pool == 3 and (tap_phase & ((1 << 36) - 1)) >= (1 << 35):
                    full = -full
                signs.append(full)
            if pool in (1, 3):
                data = code_sign(phase >> 36, 1)
                if pool == 3 and (phase & (UNIT - 1)) >= UNIT // 2:
                    data = -data
                signs = [data] + signs
            if pool == 3:
                signs += raw_signs
            assert len(signs) == branches
            for value, sign in zip(accum, signs):
                value[0] += sign * i
                value[1] += sign * q
            phase += step
            if phase >= boundary:
                results.append((period, segment, first, absolute, tuple(map(tuple, accum))))
                first = absolute + 1
                accum = [[0, 0] for _ in range(branches)]
                if phase >= width:
                    phase -= width
                    period += 1
                    segment = 0
                    boundary = seg_width
                else:
                    segment += 1
                    boundary += seg_width
        position += size
        chunk_index += 1
    return results, (carrier, phase, period, segment, boundary, tuple(map(tuple, accum)))


def check_chunking():
    checks = []
    for signal in SIGNALS:
        continuous = reference(signal, [100000])
        blocked = reference(signal, [1, 255, 256, 257, 37])
        assert continuous == blocked, signal[0]
        records = continuous[0]
        for previous, current in zip(records, records[1:]):
            assert current[2] == previous[3] + 1
        if signal[0] == 'B1C':
            assert records[0][3] + 1 == 2304
        if signal[0] in ('E1', 'B1C'):
            assert any(row[0] >= 1 and row[1] == 0 for row in records)
        checks.append(dict(signal=signal[0], published=len(records),
                           sha256=hashlib.sha256(repr(continuous).encode()).hexdigest()))
    p = 2464154 * 1023 * (1 << 17)
    step = 9153649050
    assert p + 2303 * step < 5115 * UNIT <= p + 2304 * step
    # 独立覆盖E1/B1C完整主码末端的状态更新。
    for length, segments in ((4092, 4), (10230, 10)):
        old = length * UNIT - 1
        following = old + step - length * UNIT
        assert following == step - 1 and following < UNIT
        assert length * UNIT // segments == 1023 * UNIT
    return checks


def schedule(lengths, hd=0, hc=0):
    records = []
    for j, length in enumerate(lengths):
        prior_d = records[-1][1] if records else 0
        prior_c = records[-1][3] if records else 0
        bank_free = records[-2][3] if len(records) >= 2 else 0
        start_d = max(prior_d, bank_free)
        end_d = start_d + length * 8 + hd
        start_c = max(prior_c, end_d)
        end_c = start_c + length * 5 + hc
        records.append((start_d, end_d, start_c, end_c))
        assert start_d >= bank_free and start_c >= end_d
    return records


def check_schedule():
    for blocks, expected in [(30, 62720), (120, 247040), (40, 83200), (9, 19712)]:
        assert schedule([256] * blocks)[-1][-1] == expected
    records = schedule([256, 256, 1, 255, 17, 256], hd=13, hc=3000)
    assert any(records[j][0] > records[j - 1][1] for j in range(2, len(records)))
    return dict(zero_overhead_first_result_us=[78.4, 308.8, 104.0, 24.64],
                stalled_case_bank_ownership='PASS')


class Drawing:
    """使用矩形、直线和端点箭头绘制简单模块图，并检查文字没有越框。"""

    def __init__(self, width, height):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.font_manager import FontProperties
        self.plt = plt
        self.font = FontProperties(fname='/usr/share/fonts/truetype/SUN/simsun.ttc')
        self.figure, self.axis = plt.subplots(figsize=(width / 100, height / 100))
        self.figure.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.axis.set(xlim=(0, width), ylim=(height, 0))
        self.axis.axis('off')
        self.width, self.height, self.bound_text = width, height, []

    def text(self, x, y, text, size=16, align='center'):
        return self.axis.text(x, y, text, ha=align, va='center', fontsize=size,
                              fontproperties=self.font, linespacing=1.45, color='black')

    def box(self, x, y, w, h, text, size=16, fill='white'):
        from matplotlib.patches import Rectangle
        rect = Rectangle((x, y), w, h, facecolor=fill, edgecolor='black', linewidth=1)
        self.axis.add_patch(rect)
        label = self.text(x + w / 2, y + h / 2, text, size)
        self.bound_text.append((rect, label))

    def arrow(self, points, dashed=False):
        from matplotlib.patches import FancyArrowPatch
        xs, ys = zip(*points)
        if len(points) > 2:
            self.axis.plot(xs[:-1], ys[:-1], color='black', lw=1,
                           linestyle='--' if dashed else '-')
        self.axis.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle='-|>',
                                            mutation_scale=12, linewidth=1,
                                            linestyle='--' if dashed else '-', color='black',
                                            shrinkA=0, shrinkB=0))

    def save(self, name):
        folder = ROOT / '图解'
        folder.mkdir(exist_ok=True)
        self.figure.canvas.draw()
        renderer = self.figure.canvas.get_renderer()
        for rect, label in self.bound_text:
            outer, inner = rect.get_window_extent(renderer), label.get_window_extent(renderer)
            assert inner.x0 >= outer.x0 + 3 and inner.x1 <= outer.x1 - 3, label.get_text()
            assert inner.y0 >= outer.y0 + 3 and inner.y1 <= outer.y1 - 3, label.get_text()
        svg = folder / (name + '.svg')
        self.figure.savefig(svg, facecolor='white', metadata={'Date': None})
        svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
        self.figure.savefig(folder / (name + '.png'), facecolor='white', dpi=160)
        self.plt.close(self.figure)


def draw_all():
    d = Drawing(1200, 520)
    d.box(40, 180, 200, 75, '原始I/Q SRAM\n按输入流共享')
    d.box(320, 180, 200, 75, '混频协处理器\n多路NCO、DDC')
    d.box(600, 180, 230, 75, '共享基带SRAM\n多块缓存，256点/块', fill='#f2f2f2')
    d.box(910, 180, 250, 75, '相关协处理器\n多组码NCO、相关、I&D')
    for x1, x2 in [(240, 320), (520, 600), (830, 910)]:
        d.arrow([(x1, 217), (x2, 217)])
    d.box(320, 40, 200, 65, '通道载波状态')
    d.arrow([(420, 105), (420, 180)], dashed=True)
    d.box(910, 40, 250, 65, '主码与码/积分状态')
    d.arrow([(1035, 105), (1035, 180)], dashed=True)
    d.box(910, 355, 250, 75, 'PDI结果SRAM\n5 / 6 / 11组复相关')
    d.arrow([(1035, 255), (1035, 355)])
    d.box(600, 355, 230, 75, '软件跟踪环\n读取结果、配置任务')
    d.arrow([(910, 392), (830, 392)])
    d.text(340, 390, '实线：样点或结果\n虚线：当前通道状态', 15)
    d.text(600, 480, '144通道共享两个协处理器；内部计算单元并行，通道状态独立', 16)
    d.save('TC-01_总体架构')

    d = Drawing(1200, 475)
    d.box(40, 210, 160, 70, '原始SRAM\ns4 I/Q')
    d.box(270, 210, 160, 70, '输入字拆分\n每点I、Q')
    d.box(500, 210, 200, 70, '复数共轭混频\n4次实乘、2次加减')
    d.box(770, 210, 170, 70, '算术右移4 bit\ns5 I/Q')
    d.box(1010, 210, 150, 70, '打包写入\n基带A或B')
    for x1, x2 in [(200, 270), (430, 500), (700, 770), (940, 1010)]:
        d.arrow([(x1, 245), (x2, 245)])
    d.box(270, 50, 160, 70, '载波NCO\nu32相位、步进')
    d.box(500, 50, 200, 70, '16相位系数表\nsin / cos')
    d.arrow([(430, 85), (500, 85)])
    d.arrow([(600, 120), (600, 210)])
    d.box(270, 365, 670, 65, '示例：输入 (5, -3)，系数 (15, 3)，输出 (4, -4)', size=17)
    d.save('TC-02_混频协处理器')

    d = Drawing(1160, 400)
    left, scale = 170, 920 / 6144
    d.text(100, 120, '混频', 17)
    d.text(100, 245, '相关', 17)
    for tick in [0, 2048, 3328, 4096, 5376, 6144]:
        x = left + tick * scale
        d.axis.plot([x, x], [80, 298], color='#cccccc', linewidth=0.7, linestyle=':')
        d.text(x, 48, str(tick), 13)
    for j in range(3):
        x = left + j * 2048 * scale
        d.box(x, 90, 2048 * scale, 60, '第%d块 → %s' % (j, 'A' if j % 2 == 0 else 'B'), fill='#f0f0f0')
    for j in range(2):
        x = left + (j + 1) * 2048 * scale
        d.box(x, 215, 1280 * scale, 60, '%s → 第%d块' % ('A' if j % 2 == 0 else 'B', j))
    d.text(620, 335, '时间单位：系统拍；满256点块；此图不含任务和流水开销', 16)
    d.save('TC-03_AB流水')

    d = Drawing(1220, 510)
    d.box(45, 270, 180, 80, '基带A / B\n每点读一次I/Q')
    d.box(295, 270, 180, 80, '样点保持\n供五个批次复用')
    d.box(550, 235, 280, 150, '3条复数相关通路\n按本地码选 +I/Q 或 -I/Q\n各自累加', 17)
    d.box(905, 270, 260, 80, '独立积分状态\n按资源池保留5/6/11组')
    for x1, x2 in [(225, 295), (475, 550), (830, 905)]:
        d.arrow([(x1, 310), (x2, 310)])
    d.box(45, 55, 180, 80, '码NCO\n当前Prompt相位')
    d.box(295, 55, 180, 80, '五抽头地址\nVE、E、P、L、VL')
    d.box(550, 55, 280, 80, '主码RAM与符号生成\nBOC / PRN-only共享读码')
    d.arrow([(225, 95), (295, 95)])
    d.arrow([(475, 95), (550, 95)])
    d.arrow([(690, 135), (690, 235)])
    d.text(825, 185, '当前抽头码符号', 15)
    d.text(610, 455, '五批次：VE → E → P → L → VL；P批次最多同时启用3条复通路', 17)
    d.save('TC-04_相关协处理器')

    d = Drawing(1160, 430)
    d.text(70, 55, 'Prompt约4808.101 chip\n主码内4.70 ms', 17, align='left')
    d.text(1090, 55, '边界5115 chip\n主码内5 ms', 17, align='right')
    left, size = 75, 112
    for j in range(9):
        d.box(left + j * size, 135, size, 64, '第%d块\n256点' % (j + 1), 15,
              fill='#e9e9e9' if j == 8 else 'white')
    d.axis.plot([left, left], [105, 214], color='black', lw=1)
    d.axis.plot([left + 9 * size, left + 9 * size], [105, 214], color='black', lw=1)
    d.text(left + size * 4, 258, '前8块：积分状态连续保存，不清零', 17)
    d.arrow([(left + size * 8.5, 199), (left + size * 8.5, 310)])
    d.box(745, 310, 355, 65, '第2304点后输出11组相关结果', 16)
    d.text(360, 345, '9块合计2304点，形成一条首段PDI', 16)
    d.save('TC-05_跨块积分')


def check_document():
    text = DOC.read_text()
    assert sum(line.strip() == '$$' for line in text.splitlines()) % 2 == 0
    assert text.count('```') % 2 == 0
    for needed in ['179964', '175.7461', '71.68%', '44.80%', '573440', '358400', '83.2']:
        assert needed in text, needed
    for needed in ['2242560', '17940480', '11212800', '749156', '731.5977',
                   '4.48512', '36576', '227392', '8760']:
        assert needed in text, needed
    images = re.findall(r'!\[[^\]]*\]\(([^)]+)\)', text)
    assert len(images) == 5
    for image in images:
        path = ROOT / image
        assert path.exists(), str(path)
        ET.parse(path)
        assert path.with_suffix('.png').exists()
    return dict(images=len(images), math_delimiters='PASS', document_budget_tokens='PASS')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    results = dict(budget=budget(), target_144=target_budget(),
                   ddc=check_ddc(), chunking=check_chunking(),
                   ab_schedule=check_schedule(), rtl_timing_verified=False)
    if not args.check_only:
        draw_all()
    results['document'] = check_document()
    if not args.check_only:
        (ROOT / '预算核算.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
