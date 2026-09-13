#!/usr/bin/env python3
"""核算144通道实时混频／并行相关资源，不配置原始I/Q历史缓存。"""

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / '跟踪混频与相关协处理器处理流程与资源预算.md'
CLOCK_HZ = 800000000
MIX_CYCLES = 8
CORR_CYCLES = 1
COUNTS = [48, 48, 12, 36]
SAMPLES_PER_MS = [7680, 30720, 10240, 7680]
BRANCHES = [5, 6, 5, 11]
BITS = [18, 20, 18, 18]
COS = [15, 12, 8, 3, -3, -8, -12, -15, -15, -12, -8, -3, 3, 8, 12, 15]
SIN = [3, 8, 12, 15, 15, 12, 8, 3, -3, -8, -12, -15, -15, -12, -8, -3]


def ceil_div(value, divisor):
    return (value + divisor - 1) // divisor


def budget():
    """按每毫秒样点工作量计算；支路并行，不将支路数乘入相关拍数。"""
    pools = []
    for pool, (count, samples, branches, bits) in enumerate(
            zip(COUNTS, SAMPLES_PER_MS, BRANCHES, BITS)):
        total = count * samples
        payload = 4 * ceil_div(branches * 2 * bits, 32)
        pools.append(dict(pool=pool, channels=count, samples_per_ms=total,
                          parallel_branches=branches,
                          mixing_cycles=total * MIX_CYCLES,
                          correlation_cycles=total * CORR_CYCLES,
                          complex_accumulations=total * branches,
                          record_bytes=payload + 16,
                          accumulator_bits=count * branches * 2 * bits))
    total = sum(row['samples_per_ms'] for row in pools)
    mix = total * MIX_CYCLES
    corr = total * CORR_CYCLES
    available = CLOCK_HZ // 1000
    reserved = available * 4 // 5
    minimum = dict(mixing=ceil_div(mix, available), correlation=ceil_div(corr, available))
    provisioned = dict(mixing=ceil_div(mix, reserved), correlation=ceil_div(corr, reserved))
    nmix, ncorr = provisioned['mixing'], provisioned['correlation']
    record_bytes = sum(row['channels'] * row['record_bytes'] for row in pools)
    code_bank_bytes = 4 * ceil_div(10230, 32)
    # 码表常驻。每通道固定分到一组；五路读码复制单分量／导频码区。
    code_banks_per_group = 6
    pilot_one_copy = COUNTS[0] * 256 + COUNTS[1] * code_bank_bytes + 64
    pilot_one_copy += COUNTS[3] * code_bank_bytes
    data_codes = (COUNTS[1] + COUNTS[3]) * code_bank_bytes
    storage = dict(raw_iq_sram=0, resident_pilot_codes=5 * pilot_one_copy,
                   resident_data_codes=data_codes,
                   channel_states=sum(COUNTS) * 128,
                   double_result_buffers=2 * record_bytes,
                   coefficient_tables=nmix * 20)
    mixing_per_pool = [5, 18, 2, 4]
    deadlines = []
    for count, lanes, samples in zip(COUNTS, mixing_per_pool, SAMPLES_PER_MS):
        max_channels = ceil_div(count, lanes)
        cycles = max_channels * MIX_CYCLES
        # 当前输入样点在该单元的通道处理量不得超过一个输入周期。
        assert cycles * samples <= available
        deadlines.append(dict(mixing_units=lanes, max_channels_per_unit=max_channels,
                              service_cycles=cycles, service_ns=cycles * 1.25,
                              input_period_ns=1e6 / samples))
    corr_group_M_s = [48 * 7.68, 24 * 30.72, 24 * 30.72, 12 * 10.24 + 36 * 7.68]
    resident_group_bytes = [5 * 48 * 256, 6 * 24 * code_bank_bytes,
                            6 * 24 * code_bank_bytes,
                            5 * (36 * code_bank_bytes + 64) + 36 * code_bank_bytes]
    assert sum(COUNTS) == 144 and total == 2242560
    assert mix == 17940480 and corr == 2242560
    assert minimum == dict(mixing=23, correlation=3)
    assert provisioned == dict(mixing=29, correlation=4)
    assert record_bytes == 7152 and pilot_one_copy == 119872 and data_codes == 107520
    assert sum(storage.values()) == 740196
    assert sum(resident_group_bytes) == 5 * pilot_one_copy + data_codes == 706880
    assert sum(mixing_per_pool) == nmix and max(corr_group_M_s) < 800
    assert sum(row['complex_accumulations'] for row in pools) == 14346240
    assert sum(row['accumulator_bits'] for row in pools) == 36576
    return dict(clock_hz=CLOCK_HZ, channels=sum(COUNTS), counts_by_pool=COUNTS,
                cycles_per_sample=dict(mixing=MIX_CYCLES, correlation=CORR_CYCLES),
                pools=pools, samples_per_ms=total, samples_M_s=total / 1000,
                minimum_parallel=minimum, provisioned_at_80_percent=provisioned,
                minimum_utilization=dict(mixing=mix / (minimum['mixing'] * available),
                                         correlation=corr / (minimum['correlation'] * available)),
                provisioned_utilization=dict(mixing=mix / (nmix * available),
                                             correlation=corr / (ncorr * available)),
                single_unit_M_s=dict(mixing=CLOCK_HZ / MIX_CYCLES / 1e6,
                                     correlation=CLOCK_HZ / CORR_CYCLES / 1e6),
                input_deadline_budget=deadlines,
                correlation_groups_M_s=corr_group_M_s,
                bandwidth_GB_s=dict(raw_iq_sram_read=0, raw_iq_sram_write=0,
                                    baseband_write=total * 2 / 1e6,
                                    baseband_read=total * 2 / 1e6,
                                    baseband_total=total * 4 / 1e6,
                                    four_group_peak_read=ncorr * 1.6),
                code_banks_per_group=code_banks_per_group,
                pilot_one_copy_bytes=pilot_one_copy,
                resident_code_bytes_by_group=resident_group_bytes,
                output_records_per_s=sum(COUNTS) * 1000,
                output_complex_per_ms=sum(n * b for n, b in zip(COUNTS, BRANCHES)),
                result_write_MB_s=record_bytes / 1000,
                storage=storage, known_storage_subtotal_bytes=sum(storage.values()),
                known_storage_subtotal_kib=sum(storage.values()) / 1024,
                baseband_queue=dict(total_slots=None, iq_bytes_per_slot=2,
                                    control_bytes=None, depth_verified=False),
                full_storage_total_bytes=None,
                compute_resources=dict(multipliers=nmix, mixing_add_sub=nmix * 2,
                                       carrier_ncos=nmix, code_ncos=ncorr,
                                       complex_correlators=ncorr * 11,
                                       scalar_accumulators=ncorr * 22,
                                       code_read_ports=ncorr * code_banks_per_group,
                                       active_and_shadow_register_bits=ncorr * 2 * 440),
                rtl_timing_verified=False)


def check_arithmetic():
    """核对混频数值范围及本地码加减，不引入同步或跟踪算法。"""
    values = []
    for c, s in zip(COS, SIN):
        for i in range(-8, 8):
            for q in range(-8, 8):
                values += [(i * c + q * s) >> 4, (q * c - i * s) >> 4]
    assert min(values) == -10 and max(values) == 10
    checks = 0
    for value in range(-10, 11):
        for accumulator in (-100, 0, 100):
            for sign in (-1, 1):
                selected = accumulator + value if sign == 1 else accumulator - value
                assert selected == accumulator + sign * value
                checks += 1
    return dict(mixing_input_vectors=4096, mixing_output_range=[-10, 10],
                signed_accumulation_checks=checks)


class Drawing:
    """黑白模块图；文字边界检查不代替最后的人工看图。"""

    def __init__(self, width, height):
        import matplotlib
        matplotlib.use('Agg')
        matplotlib.rcParams['svg.hashsalt'] = 'tracking-coprocessor-v4'
        import matplotlib.pyplot as plt
        from matplotlib.font_manager import FontProperties
        self.plt = plt
        self.font = FontProperties(fname='/usr/share/fonts/truetype/SUN/simsun.ttc')
        self.figure, self.axis = plt.subplots(figsize=(width / 100, height / 100))
        self.figure.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.axis.set(xlim=(0, width), ylim=(height, 0))
        self.axis.axis('off')
        self.bound_text = []

    def text(self, x, y, label, size=16):
        return self.axis.text(x, y, label, ha='center', va='center', fontsize=size,
                              fontproperties=self.font, linespacing=1.45, color='black')

    def box(self, x, y, width, height, label, size=16):
        from matplotlib.patches import Rectangle
        rect = Rectangle((x, y), width, height, facecolor='white',
                         edgecolor='black', linewidth=1)
        self.axis.add_patch(rect)
        text = self.text(x + width / 2, y + height / 2, label, size)
        self.bound_text.append((rect, text))

    def arrow(self, start, end):
        from matplotlib.patches import FancyArrowPatch
        self.axis.add_patch(FancyArrowPatch(start, end, arrowstyle='-|>',
                                            mutation_scale=12, linewidth=1,
                                            color='black', shrinkA=0, shrinkB=0))

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
    d = Drawing(1200, 255)
    for x, label in [(30, '前端实时I/Q\n每点8 bit'),
                     (265, '混频协处理器\n8拍 / 点'),
                     (500, '基带接口队列\nSRAM，逐点交接'),
                     (735, '相关协处理器\n1拍 / 点'),
                     (970, '积分结果SRAM\n5 / 6 / 11组I/Q')]:
        d.box(x, 65, 190, 85, label)
    for x in [220, 455, 690, 925]:
        d.arrow((x, 107.5), (x + 45, 107.5))
    d.text(600, 207, '144通道实时处理；不存原始I/Q，码表与积分状态按通道常驻')
    d.save('TC-01_总体架构')

    d = Drawing(1200, 350)
    for x, width, label in [(30, 185, '前端实时输入\ns4 I/Q'),
                            (255, 175, '当前样点锁存\n分发至对应通道'),
                            (480, 200, '复数混频\n4次实乘、2次加减'),
                            (730, 180, '算术右移4 bit\ns5 I/Q'),
                            (960, 210, '基带接口输出\n每点2 Byte')]:
        d.box(x, 155, width, 80, label)
    for x1, x2 in [(215, 255), (430, 480), (680, 730), (910, 960)]:
        d.arrow((x1, 195), (x2, 195))
    d.box(255, 25, 175, 70, '载波NCO\n32 bit相位累加')
    d.box(480, 25, 200, 70, '16相位系数表\nsin / cos')
    d.arrow((430, 60), (480, 60))
    d.arrow((580, 95), (580, 155))
    d.text(600, 303, '单路：8拍/点，100 M样点/s；1个实数乘法单元分时复用')
    d.save('TC-02_混频协处理器')

    d = Drawing(1220, 455)
    d.box(40, 40, 180, 80, '码NCO\n码相位逐点累加')
    d.box(290, 40, 190, 80, '五抽头地址\nVE/E/P/L/VL')
    d.box(550, 40, 290, 80, '按通道读取常驻码表\n最多6个独立读口')
    d.arrow((220, 80), (290, 80))
    d.arrow((480, 80), (550, 80))
    d.box(40, 260, 180, 85, '基带接口输入\n每点只读一次I/Q')
    d.box(290, 260, 190, 85, '样点广播\n同时送全部支路')
    d.box(550, 225, 290, 155, '最多11条复相关通路\n22条标量符号累加\n每拍同时更新', 17)
    d.box(930, 260, 245, 85, '积分结果保存\n5 / 6 / 11组I/Q')
    d.arrow((695, 120), (695, 225))
    d.arrow((220, 302.5), (290, 302.5))
    d.arrow((480, 302.5), (550, 302.5))
    d.arrow((840, 302.5), (930, 302.5))
    d.text(610, 424, '全部通道积分常驻；每拍处理1个通道样点，每1 ms保存积分结果')
    d.save('TC-04_相关协处理器')


def check_document(result):
    text = DOC.read_text()
    assert len(re.findall(r'^## \d', text, flags=re.M)) == 4
    for removed in ['4.7', '4.70', '2304', '牵引', '鉴频', '位同步', '五批次',
                    '5拍/点', '5拍/复样点', '软件跟踪环', '算法',
                    '256点', '399360', '32768', '733796', '原始样点读取']:
        assert removed not in text, removed
    assert sum(line.strip() == '$$' for line in text.splitlines()) % 2 == 0
    for needed in ['100 M样点/s', '800 M样点/s', '93.44%', '70.08%', '77.33%',
                   '119872', '599360', '107520', '4.48512', '8.97024',
                   str(result['known_storage_subtotal_bytes']), '722.8', '17940480',
                   '2242560', '100 ns', '30 ns', '60 ns', '90 ns', '$2D$']:
        assert needed in text, needed
    images = re.findall(r'!\[[^\]]*\]\(([^)]+)\)', text)
    assert len(images) == 3
    for image in images:
        path = ROOT / image
        ET.parse(path)
        assert path.with_suffix('.png').exists()
    return dict(chapters=4, images=3, budget_tokens='PASS', removed_sections='PASS')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    result = dict(budget=budget(), arithmetic=check_arithmetic())
    if not args.check_only:
        draw_all()
    result['document'] = check_document(result['budget'])
    output = ROOT / '预算核算.json'
    if args.check_only:
        assert json.loads(output.read_text()) == result, '预算JSON未与文档和脚本同步'
    else:
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(checks='PASS', channels=144, correlation_cycles_per_sample=1,
                         minimum_parallel=result['budget']['minimum_parallel'],
                         provisioned_parallel=result['budget']['provisioned_at_80_percent'],
                         raw_iq_sram_bytes=0,
                         known_storage_subtotal=result['budget']['known_storage_subtotal_bytes'],
                         baseband_queue_depth=None,
                         document=result['document'], rtl_timing_verified=False),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
