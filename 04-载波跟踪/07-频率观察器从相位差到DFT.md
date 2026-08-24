---
title: 第7章 频率观察器：从相位差到DFT
tags: [GNSS, StarTrack, FLL, DFT, FMS]
status: 当前实现
version: V1.0
date: 2026-08-24
cssclasses: [startrack-spec]
---

# 第7章 频率观察器：从相位差到DFT

> [!abstract] 本章目标
> 看懂StarTrack为什么有多种频率观察器。它们不是重复代码，而是分别解决“近处精测”“未知符号”
> “大残频搜索”“极弱局部测量”和“BOC码偏下Prompt失效”。

## 7.1 频差怎样变成相位差

若残余频率为$\Delta f$，相隔$T$的两个复相关相位差近似：

$$
\Delta\phi=2\pi\Delta fT.
$$

所以：

$$
\widehat{\Delta f}=\frac{\Delta\phi}{2\pi T}.
$$

工程上不用分别求两个角再相减，而是先做共轭积。

## 7.2 Cross/Dot鉴频

设相邻相关为$Z_{k-1}$和$Z_k$：

$$
C_k=Z_{k-1}^{*}Z_k=D_k+jX_k.
$$

其中$D_k$是点积，$X_k$是叉积。频差为：

$$
\widehat{\Delta f}=\frac{\operatorname{atan2}(X_k,D_k)}{2\pi\alpha T}.
$$

$\alpha=1$表示普通相关；平方或二倍角相关的相位转速翻倍，所以$\alpha=2$。

![[90-附件/复相关相位差.svg]]

低SNR时应先把多个$C_k$复数相加，再统一`atan2`。若先对每个噪声点取角再平均，会产生严重圆周统计问题。

## 7.3 平方FLL为什么能消除正负号

若$P_k=d_kA\exp(j\phi_k)$，其中$d_k=\pm1$，平方后：

$$
P_k^2=A^2\exp(j2\phi_k),
$$

因为$d_k^2=1$。数据bit或导频二次码的正负被消除，但相位加倍，模糊范围减半。

StarTrack的`PilotFllObs`在非BOC导频同步前使用Prompt平方。B1C则先按完整10 ms主码相干，再平方。

## 7.4 DFT功率搜索

残频较大时，相邻鉴频可能超模糊范围。DFT对一组候选频率$f_b$重新旋转Prompt：

$$
Z(f_b)=\sum_nP_n\exp(-j2\pi f_bt_n),
$$

$$
J(f_b)=|Z(f_b)|^2.
$$

```mermaid
flowchart LR
    A["多个频率假设"] --> B["各自去旋转"]
    B --> C["同频点复数相干"]
    C --> D["跨未知bit加功率"]
    D --> E["选最大频点"]
    E --> F["邻点插值细化"]
```

`PullInFreqObs`用于普通入口的粗居中；`FreqBinObserver`用于同步后按状态配置的多频点观察。

## 7.5 FMS是什么

FMS可理解为只看当前NCO左右两个很近的频率支路，用能量差估计零点附近小残差。它的优势是极弱时
积累效率高；缺点是单调范围小，输出控制增益也不一定等于无偏物理Hz。

因此`FreqObs`同时保存：

- `freq_hz`：允许送FLL的控制鉴别量；
- `physical_hz`：确认无偏时才用于物理动态统计；
- `physical_valid`：两者是否可等同解释。

不能用FMS输出RMS小就宣称物理频率估计很准。

## 7.6 E1码未居中时的五抽头联合频率牵引

E1 BOC Prompt在约半chip偏差处可能接近零。`PilotPullFreqObs`不能只看Prompt，而是对E1C完整BOC
副本的五个抽头，同时枚举25个二次码相位和频率网格。它要求：

- 最佳二次码相位相对次佳足够突出；
- 最佳频点相对非邻近次峰足够突出；
- 频率峰可做三点抛物线插值；
- 有效结果只执行一次NCO平移，不直接建立长期Hz/s趋势。

码FineCheck通过后冻结预同步频率趋势，使后续500+500 ms PilotSync看到固定NCO模型。

## 7.7 B1C五抽头主码平方FLL

B1C每个抽头先把10条1 ms PDI相干成主码块：

$$
B_{k,t}=\sum_{m=0}^{9}P_{k,m,t},\qquad X_{k,t}=B_{k,t}^2.
$$

相邻主码平方复积：

$$
C_{k,t}=X_{k-1,t}^{*}X_{k,t}.
$$

当前生产配置使用10个相邻主码对，即11块、110 ms输入跨度；每20 ms滑动发布。各PDI的真实NCO
可能不同，因此先旋转到共同参考，再把五抽头复数相加：

$$
C=\sum_{k,t}C_{k,t}\exp\!\left(j4\pi T_b(f_{NCO,k}-f_{ref})\right),
$$

$$
D=\sum_{k,t}|C_{k,t}|,\qquad q=\frac{|C|}{D},
$$

$$
\widehat{\Delta f}=\frac{\arg C}{4\pi T_b},\qquad T_b=10\ \mathrm{ms}.
$$

存在性量：

$$
\eta=\frac{\sum_{k,t}|B_{k,t}|^2}
{10\sum_{k,t,m}|P_{k,m,t}|^2}.
$$

当前门限$q\ge0.65$、$\eta\ge0.14$；物理无模糊范围：

$$
|\Delta f|<\frac{1}{4T_b}=25\ \mathrm{Hz}.
$$

B1C正式移交残频域是$\pm15.625$ Hz，留在这个范围内。锁定前始终保持wide FLL，码居中不会切短Prompt。

## 7.8 观察器选择表

| 场景 | 当前观察器 |
|---|---|
| 数据强入口未同步 | `PromptFllObs` |
| 数据普通入口 | `PullInFreqObs` |
| 非BOC导频未同步 | `PilotFllObs` |
| E1未居中 | `PilotPullFreqObs` |
| B1C未锁定 | `CodePeriodFllObs::addWide()` |
| 同步后常规状态 | `FreqBinObserver`或`FreqObserver` |
| 极弱局部残差 | FMS支路 |

## 7.9 频率粗差门

观察器`valid=true`后，`FreqGuard`还会检查：

- 数值有限；
- 当前状态允许的残差范围；
- 观察NCO与当前控制NCO的绝对频率换算；
- 局部鉴频无模糊范围。

通过才有`freq_used=true`。所以频率观察有效率与使用率是两个不同指标。

## 7.10 本章小结

Cross/Dot适合局部频差，平方FLL抵抗未知正负，DFT负责粗搜，FMS负责极弱局部测量，E1/B1C还需
在码偏导致Prompt失效时使用五抽头专属观察。多种观察器共享同一控制环，但职责和物理解释不同。

---

上一篇：[[../03-同步与积分/06-相干积分与非相干积累|相干积分与非相干积累]]　下一篇：[[08-载波环FLL与PLL|载波环FLL与PLL]]
