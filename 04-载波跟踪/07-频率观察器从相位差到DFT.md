---
title: 第7章 频率观察器：从相位差到DFT
tags: [GNSS, StarTrack, FLL观察器, DFT, FMS]
status: 当前实现
version: V2.0
date: 2026-08-25
cssclasses: [startrack-spec]
---

# 第7章 频率观察器：从相位差到DFT

> [!abstract] 本章在全流程中的位置
> 相关器给出复向量，本章把“向量在转”变成带Hz单位的频率观察。会依次讲Cross/Dot、平方FLL、DFT频点、FMS和B1C五抽头主码FLL，并说明无模糊范围、NCO参考和source tap。

![[../90-附件/复相关相位差.svg]]

## 7.1 频差怎样变成相位差

若相关块中心相隔$T$秒，剩余频差为$\Delta f$，相位差为：

$$
\Delta\phi=2\pi\Delta fT.
$$

所以：

$$
\widehat{\Delta f}=\frac{\Delta\phi}{2\pi T}.
$$

真正困难的不是这一步代数，而是：

- 相位是否被数据bit翻转；
- 相位差是否越过$\pm\pi$发生模糊；
- 两个块是否连续；
- 本地NCO是否在块间换字；
- 观察参考时刻在哪里。

## 7.2 Cross/Dot鉴频器

设前后两个复相关为：

$$
z_0=I_0+jQ_0,\qquad z_1=I_1+jQ_1.
$$

复积：

$$
z_0^*z_1
=(I_0I_1+Q_0Q_1)
+j(I_0Q_1-Q_0I_1).
$$

定义：

$$
\operatorname{dot}=I_0I_1+Q_0Q_1,
$$

$$
\operatorname{cross}=I_0Q_1-Q_0I_1.
$$

则：

$$
\Delta\phi=\operatorname{atan2}(\operatorname{cross},\operatorname{dot}).
$$

使用`atan2`而不是`atan(cross/dot)`，因为后者无法区分象限，也会在dot接近0时失真。

## 7.3 无模糊范围

普通相位差位于$(-\pi,\pi]$，所以：

$$
|\Delta f|<\frac{1}{2T}.
$$

例如块间隔20 ms：

$$
|\Delta f|<25\ \text{Hz}.
$$

若残差超出范围，观察会折返到错误频率。此时不能靠放大环路带宽修复，因为输入观察本身已经歧义。

## 7.4 平方FLL为什么能消除$\pm1$

未知bit使相关值乘$s_k\in\{+1,-1\}$。平方后：

$$
q_k=z_k^2,
$$

$$
(s_k z_k)^2=z_k^2.
$$

相邻平方复积累加：

$$
C=\sum_k q_{k-1}^*q_k,
$$

频率为：

$$
\widehat{\Delta f}
=\frac{\operatorname{atan2}(\Im C,\Re C)}{4\pi T}.
$$

分母中的$4\pi$来自二倍角。其无模糊范围也缩为：

$$
|\Delta f|<\frac{1}{4T}.
$$

## 7.5 质量值是什么

常见相干质量定义为：

$$
q=\frac{|C|}{D},
\qquad
D=\sum_k|q_{k-1}|\,|q_k|.
$$

$q$接近1表示相邻复积方向一致，接近0表示方向随机。它是无量纲一致性，不是C/N0，也不是频率精度的直接概率保证。

存在性可以用相干功率与原子功率比较，例如：

$$
\eta=
\frac{\sum_b|Z_b|^2}
{M\sum_b W_b},
$$

$Z_b$是一个主码块的复和，$W_b$是其中1 ms功率和，$M$是块内原子数。质量门$q$与存在性门$\eta$职责不同。

## 7.6 DFT频点搜索

当初始残差可能超出单个Cross/Dot无模糊范围时，可以在一组候选频率$f_m$上去旋：

$$
S(f_m)=\left|
\sum_{k=0}^{N-1}z_ke^{-j2\pi f_m t_k}
\right|^2.
$$

选择最大频点，再用邻点插值或局部鉴频细化。DFT观察器必须报告：

- 频点间隔；
- 搜索范围；
- 最大峰和次峰对比；
- 输出对应的NCO中心；
- 窗口中心时刻。

状态机不应重新计算DFT模糊范围，这些属于观察器物理合同。

## 7.7 FMS是什么

FMS是项目中的频率多点统计观察。它把连续1 ms Prompt映射到固定频率候选，积累bin power，再从主峰与邻域得到频率结果。

可以把FMS理解为“为指定状态准备的窄频率功率尺”，而不是卡尔曼滤波器。其频点和范围由Profile配置，不能按signal id在实现里偷偷写死。

## 7.8 E1码未居中时的五抽头FLL

E1 BOC Prompt在某些码偏差下接近相关零点，Prompt-only平方FLL可能无信号。预同步E1因此对VE/E/P/L/VL五条固定tap分别形成平方复积，再在复数域统一相加：

$$
C=\sum_m\sum_{t\in\{VE,E,P,L,VL\}}
\left(P_{m-1,t}^2\right)^*P_{m,t}^2.
$$

$$
D=\sum_m\sum_t
|P_{m-1,t}^2|\,|P_{m,t}^2|.
$$

强tap自然贡献更大，无需每毫秒选择“最大tap”。后者会引入噪声次序偏置和tap切换相位。

## 7.9 B1C五抽头完整主码平方FLL

B1C主码10 ms。对每个tap $t$、第$b$个完整主码：

$$
B_{b,t}=\sum_{m=0}^{9}P_{b,m,t},
$$

$$
W_{b,t}=\sum_{m=0}^{9}|P_{b,m,t}|^2.
$$

对相邻主码平方复积并跨五tap统一累加：

$$
C=\sum_{b=1}^{N}\sum_t
\left(B_{b-1,t}^2\right)^*B_{b,t}^2.
$$

$$
D=\sum_{b=1}^{N}\sum_t
|B_{b-1,t}^2|\,|B_{b,t}^2|.
$$

当前生产配置冻结为：

| 参数 | 值 | 物理含义 |
|---|---:|---|
| adjacent pairs | 10 | 10个相邻10 ms平方复积 |
| blocks | 11 | 首次观察需11个完整主码 |
| span | 110 ms | 输入覆盖时间 |
| update | 20 ms | 成熟后发布节拍 |
| phase baseline | 10 ms | 频率公式相位基线 |
| ambiguity | $\pm25$ Hz | 平方且基线10 ms |
| min quality | 0.65 | 复积方向一致性 |
| min presence | 0.14 | 主码相干存在性 |
| source tap | 3 | 日志表示五抽头组合，不冒充Prompt |

频率公式仍除以$4\pi\cdot0.010$，不能错误除以110 ms。110 ms是处理窗口，10 ms才是相邻相位基线。

## 7.10 NCO参考与物理频率

观察输出至少区分：

$$
f_{\text{absolute}}
=f_{\text{nco,ref}}+f_{\text{physical residual}}.
$$

环路控制使NCO在窗口内变化时，各pair必须按自己的实际NCO旋转到统一参考。日志中的`physical_hz`是相对记录参考NCO的残差，不等于场景真值，也不能再重复扣除BPSK-like边带。

## 7.11 观察器选择表

| 阶段 | 典型观察 | 原因 |
|---|---|---|
| 数据bit未知 | 平方FLL/DFT | 消除$\pm1$ |
| 导频未同步 | 平方Prompt或主码FLL | 二次码未知 |
| E1/B1C码未居中 | 五抽头联合FLL | Prompt可能接近零点 |
| 同步且擦除后强信号 | Cross/Dot + PLL相位 | 低延迟、精度高 |
| 弱/极弱状态 | DFT/FMS/FLL-only | 长积分且阻断噪声PLL |

## 7.12 对应源码

| 功能 | 主要位置 |
|---|---|
| Cross/Dot与通用频率观察 | `src/carrier_observer/` |
| DFT/BinPower/FMS | `src/carrier_observer/` |
| Pilot平方FLL | `src/carrier_observer/pilot_fll_obs.cpp` |
| 主码平方FLL | `src/carrier_observer/code_period_fll_obs.cpp` |
| B1C主码聚合 | `src/sync/code_period_sum.cpp` |
| 观察路由 | `src/tracking/track_engine.cpp::formFreqObs()` |

## 7.13 本章小结

频率观察的核心是把复相关相位差换成Hz，但符号、模糊范围、NCO参考和窗口时刻决定这个Hz是否真实。平方消除$\pm1$的同时缩小无模糊范围；DFT扩展搜索；E1/B1C在码未居中时用五抽头避免Prompt零点。处理窗口长度绝不能冒充相位基线。

---

上一篇：[[../03-同步与积分/06-相干积分与非相干积累|第6章 相干积分与非相干积累]]　下一篇：[[08-载波环FLL与PLL|第8章 载波环FLL与PLL]]
