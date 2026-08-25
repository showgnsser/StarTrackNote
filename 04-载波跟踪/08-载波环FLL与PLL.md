---
title: 第8章 载波环：FLL预测、校正与PLL精修
tags: [GNSS, StarTrack, FLL, PLL, 载波环]
status: 当前实现
version: V2.0
date: 2026-08-25
cssclasses: [startrack-spec]
---

# 第8章 载波环：FLL预测、校正与PLL精修

> [!abstract] 本章在全流程中的位置
> 第7章得到带Hz单位的观察，本章解释它怎样进入连续控制器。重点是FLL的“每毫秒预测、观察到来时校正”、PLL为何只在强信号状态开放，以及状态换档怎样保留总NCO而不保留不兼容窗口。

## 8.1 观察不是控制

一个频率观察可能每20、160、320或600 ms才成熟，硬件却每1 ms需要载波step。载波环因此分成两种动作：

1. `advanceTo(now)`：没有新观察也按已确认趋势推进；
2. `correct(obs)`：有合格观察时校正频率和趋势。

PLL是叠加在FLL基值上的小修正，不替代FLL连续频率状态。

## 8.2 FLL内部保存什么

用简化符号表示：

- $f_k$：当前连续频率控制，Hz；
- $d_k$：与更新周期对应的频率步进；
- $r_k=d_k/T_u$：物理频率变化率，Hz/s；
- $t_k$：当前环路时间锚。

推进到新时刻$t$：

$$
f^{-}(t)=f_k+r_k(t-t_k).
$$

只要时间轴连续，即使暂时没有新观察，NCO仍跟随最近可信趋势。若gap使中间时间未知，环路必须重新锚定，不能跨缺口盲推。

## 8.3 FLL校正公式

对已经重定时到当前时刻的频率误差$e_f$：

$$
d_k=d_{ref}+\lambda(d_{k-1}-d_{ref})+K_2e_f,
$$

$$
f_k=f_k^{-}+(d_k-d_{k-1})+K_1e_f.
$$

| 项 | 直觉 |
|---|---|
| $K_1e_f$ | 立即纠正当前频率 |
| $K_2e_f$ | 学习持续趋势 |
| $\lambda$ | 遗忘不再可信的旧趋势 |
| $d_{ref}$ | 外部可信rate或状态参考，没有时为0 |

默认由噪声带宽$B_n$和更新周期$T_u$导出：

$$
\omega_n=\frac{B_n}{0.53},
$$

$$
K_1=1.414\omega_nT_u,
\qquad
K_2=(\omega_nT_u)^2.
$$

带宽越大，响应更快但噪声更大；更新周期变长时，同一连续时间设计必须重新离散化，不能只复制系数。

## 8.4 为什么不是所有频率观察都推进趋势

某些观察只说明“方向可能如此”，或缺少可靠参考时刻。它们可以用于诊断，却不应更新高阶趋势。

只有同时满足以下条件的观察才适合控制：

- `ready&&valid&&physical_valid`；
- 有明确Hz单位和NCO参考；
- 时间窗口连续；
- 当前状态策略允许该观察模式；
- 没有在同历元被码slew、同步边界或状态边界撤销。

`freq_valid=true`与`freq_used=true`分开记录，就是为了看清观察质量和策略使用这两件事。

## 8.5 PLL观察是什么

已知符号时，Prompt相位可用四象限：

$$
\widehat\phi
=\frac{1}{2\pi}\operatorname{atan2}(Q_P,I_P),
$$

周期为1 cycle。

数据bit未知时，Costas形式使用：

$$
\widehat\phi
=\frac{1}{2\pi}
\arctan\!\left(\frac{Q_P}{I_P}\right),
$$

周期为0.5 cycle。相位观察比频率观察更怕低SNR，必须经过 `PhaseMonitor` 的有效率和RMS成熟门。

## 8.6 三阶PLL辅助项

设相位误差$\phi_k$以cycle输入，PLL自然频率：

$$
\omega_p=\frac{B_{PLL}}{0.7845}.
$$

StarTrack当前离散更新可写为：

$$
r_{p,k}=r_{p,k-1}+0.25T_u\omega_p^3\phi_k,
$$

$$
i_{p,k}=i_{p,k-1}
+T_u\left(r_{p,k}+0.55\omega_p^2\phi_k\right),
$$

$$
f_{PLL,k}=i_{p,k}+2.4\omega_p\phi_k.
$$

总载波控制：

$$
f_{ctrl}=f_{FLL}+f_{PLL}.
$$

PLL不是直接改载波相位，而是根据相位误差产生频率修正，使相位逐渐回到0。

## 8.7 为什么只有强信号状态允许PLL

弱信号Prompt相位近似随机。若仍允许PLL控制，随机相位会被积分成持续频率偏置。

StarTrack采用双重阻断：

1. 状态策略必须声明 `phase_control=true`；
2. `CarrierLoop`当前模式也必须为FLL+PLL。

当前只有 `ShortSlow` 承担强信号相位精修。`Sensitivity`、`BitAiding`、`OutdoorBitAiding`、`MidDynamic`和`HighDynamic`均为FLL-only；它们可以记录相位诊断，但不得注入NCO。

## 8.8 PLL带宽怎样选择

PLL带宽依据新鲜C/N0分档：

| C/N0 | PLL带宽 |
|---:|---:|
| $<36$ dB-Hz | 2.4 Hz |
| $[36,38)$ dB-Hz | 4.8 Hz |
| $[38,42)$ dB-Hz | 7.2 Hz |
| $\ge42$ dB-Hz | 9.6 Hz |

这里的带宽选择只在允许PLL的状态生效。不能因为C/N0高就绕过状态策略，也不能拿显示C/N0的平滑值驱动环路。

## 8.9 相位观察失效时怎样清PLL而不跳频

若本历元有有效FLL观察，但相位观察已完整且无效：

1. 先把当前总控制$f_{FLL}+f_{PLL}$吸收到FLL基值；
2. 再清PLL积分状态；
3. 新总控制仍等于清理前的频率；
4. 后续由FLL继续控制。

这样既去掉旧PLL拖尾，又不造成NCO瞬间跳变。

若 `phase.ready=false`，只表示没有新相位，不自动清PLL。缺证据和反证必须区分。

## 8.10 状态换档怎样保持连续

状态变化会改变观察长度、带宽和是否允许PLL，但物理载波不能随状态名跳动。正确换档是：

- 保留当前总NCO；
- 只交接可信Hz/s趋势；
- 清PLL即时积分和不兼容观察窗；
- 不装载载波相位；
- 生成新策略命令；
- 下一PDI确认后再提交状态。

状态切换本身是策略变化，不是重新捕获。

## 8.11 高动态为什么仍可用长观察

高动态状态使用320 ms观察，不代表320 ms内什么都不做。其机制是：

1. FLL已有频率和趋势状态；
2. 每1 ms按趋势预测NCO；
3. 320 ms窗口提供一次低噪声误差校正；
4. `MidDynamic`/`HighDynamic`使用比弱静态状态更高的FLL带宽和趋势权重。

只有趋势已被独立监测确认时，长窗预测才可靠。若趋势不成熟，盲目外推会把噪声当动态。

## 8.12 一个数值例子

假设当前残余频率观察为$e_f=4$ Hz，更新周期$T_u=0.160$ s，带宽$B_n=1$ Hz：

$$
\omega_n\approx1.8868,
$$

$$
K_1\approx0.4267,
\qquad
K_2\approx0.0911.
$$

当前频率立即修正约：

$$
K_1e_f\approx1.71\ \text{Hz},
$$

趋势步进增加约：

$$
K_2e_f\approx0.36\ \text{Hz/更新周期}.
$$

环路不会一次把4 Hz全吃掉，而是结合历史分阶段收敛，避免单个噪声观察把NCO拉飞。

## 8.13 对应源码

| 功能 | 主要位置 |
|---|---|
| FLL状态与离散公式 | `src/carrier_loop/third_order_fll.cpp` |
| 载波总环路 | `src/carrier_loop/carrier_loop.cpp` |
| 相位观察 | `src/carrier_observer/phase_observer.cpp` |
| 相位监测 | `src/monitor/phase_monitor.cpp` |
| 策略带宽和模式 | `src/tracking/track_fsm.cpp` |
| 环路调用与used门 | `src/tracking/track_engine.cpp::updateLoops()` |

## 8.14 本章小结

FLL保存连续频率和趋势，每毫秒预测、有观察时校正；PLL只在强信号ShortSlow里做相位精修。状态变化必须保留总NCO，只清不兼容统计。一个观察能否控制取决于物理有效性、状态许可和同历元边界，不只取决于 `valid`。

---

上一篇：[[07-频率观察器从相位差到DFT|第7章 频率观察器从相位差到DFT]]　下一篇：[[../05-码跟踪/09-BPSK码环与载波辅助DLL|第9章 BPSK码环与载波辅助DLL]]
